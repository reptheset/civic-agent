"""API server: starts runs, streams events, accepts answers to pauses, recovers after a crash."""
import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from pydantic import BaseModel

from agent.config import CHECKPOINT_DB, DATA_DIR, RECEIPT_DIR, SCREENSHOT_DIR, TESTBED_URL
from agent.graph import build_graph
from agent.runtime import browsers, bus

RUNS: dict[str, dict] = {}      # run_id -> {"status", "pending"}
TASKS: set = set()              # keeps background tasks alive
GRAPH = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global GRAPH
    await browsers.start(headless=False)
    async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB)) as saver:
        GRAPH = build_graph(saver)
        yield
    await browsers.stop()


app = FastAPI(title="Civic Agent API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"],
                   allow_methods=["*"], allow_headers=["*"])
app.mount("/screenshots", StaticFiles(directory=SCREENSHOT_DIR), name="screenshots")
app.mount("/receipts", StaticFiles(directory=RECEIPT_DIR), name="receipts")


def _cfg(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}, "recursion_limit": 60}


async def _pending_interrupt(run_id: str, result):
    intr = result.get("__interrupt__") if isinstance(result, dict) else None
    if not intr:
        snap = await GRAPH.aget_state(_cfg(run_id))
        intr = [i for t in snap.tasks for i in getattr(t, "interrupts", ())]
    return intr[0].value if intr else None


INTERRUPT_TEXT = {
    "human_step": "Waiting for you: complete the step in the browser window",
    "missing_info": "Waiting for you: information is missing",
    "approval": "Waiting for your approval before final submission",
    "confirm_profile": "Waiting for you: please confirm your details",
    "eligibility": "Waiting for you: eligibility needs your decision",
}


async def _drive(run_id: str, payload):
    """Runs the graph until it pauses or finishes, then reports which."""
    RUNS[run_id].update(status="running", pending=None)
    try:
        result = await GRAPH.ainvoke(payload, _cfg(run_id))
    except Exception as e:
        RUNS[run_id]["status"] = "error"
        await bus.publish(run_id, "error", f"Workflow error: {str(e)[:300]}")
        return
    pending = await _pending_interrupt(run_id, result)
    if pending:
        RUNS[run_id].update(status="waiting", pending=pending)
        await bus.publish(run_id, "interrupt", INTERRUPT_TEXT.get(pending.get("kind"), "Waiting for you"), pending)
    else:
        status = result.get("status", "finished") if isinstance(result, dict) else "finished"
        RUNS[run_id]["status"] = status
        await bus.publish(run_id, "done", f"Workflow finished: {status}",
                          {"receipt": result.get("receipt") if isinstance(result, dict) else None})


def _launch(run_id: str, payload):
    t = asyncio.create_task(_drive(run_id, payload))
    TASKS.add(t)
    t.add_done_callback(TASKS.discard)


class StartRun(BaseModel):
    service_request: str = "Post-matric merit scholarship application"


class Resume(BaseModel):
    value: Any = None


@app.post("/runs")
async def start_run(body: StartRun):
    pf = DATA_DIR / "my_profile.json"
    if not pf.exists():
        raise HTTPException(400, "No saved profile yet")
    saved = json.loads(pf.read_text())
    run_id = uuid.uuid4().hex[:8]
    RUNS[run_id] = {"status": "starting", "pending": None}
    state = {"run_id": run_id, "service_request": body.service_request, "profile": saved["profile"],
             "documents": saved["documents"], "portal_url": TESTBED_URL, "step_log": [],
             "status": "starting", "phase": "fill"}
    _launch(run_id, state)
    return {"run_id": run_id}


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    if run_id not in RUNS:
        raise HTTPException(404, "Unknown run (if the server restarted, use /recover)")
    return {"run_id": run_id, **RUNS[run_id], "events": len(bus.history[run_id])}


@app.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, body: Resume):
    run = RUNS.get(run_id)
    if not run or run["status"] != "waiting":
        raise HTTPException(409, "Run is not waiting for input")
    _launch(run_id, Command(resume=body.value))
    return {"ok": True}


@app.post("/runs/{run_id}/recover")
async def recover_run(run_id: str):
    """After a server restart: continue a run from its last checkpoint."""
    snap = await GRAPH.aget_state(_cfg(run_id))
    if not snap.values:
        raise HTTPException(404, "No checkpoint for this run")
    RUNS[run_id] = {"status": "recovering", "pending": None}
    await bus.publish(run_id, "log", "Recovering run from its last checkpoint")
    pending = [i for t in snap.tasks for i in getattr(t, "interrupts", ())]
    if pending:
        RUNS[run_id].update(status="waiting", pending=pending[0].value)
        await bus.publish(run_id, "interrupt", INTERRUPT_TEXT.get(pending[0].value.get("kind"), "Waiting for you"),
                          pending[0].value)
    elif snap.next:
        _launch(run_id, None)
    else:
        RUNS[run_id]["status"] = snap.values.get("status", "finished")
    return {"ok": True, "next": list(snap.next)}


@app.websocket("/runs/{run_id}/events")
async def events(ws: WebSocket, run_id: str):
    await ws.accept()
    for ev in list(bus.history[run_id]):
        await ws.send_json(ev)
    q = bus.subscribe(run_id)
    try:
        while True:
            await ws.send_json(await q.get())
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(run_id, q)


# ---------- Start a run from uploaded documents ----------
import shutil
from fastapi import File, Form, UploadFile
from agent.config import UPLOAD_DIR


@app.post("/runs/upload")
async def start_from_documents(files: list[UploadFile] = File(...), scheme: str = Form("csss")):
    if not files:
        raise HTTPException(400, "Upload at least one document")
    run_id = uuid.uuid4().hex[:8]
    folder = UPLOAD_DIR / run_id
    folder.mkdir(parents=True, exist_ok=True)
    documents = []
    for f in files:
        name = "".join(c if c.isalnum() or c in "._-" else "_" for c in (f.filename or "document"))
        dest = folder / name
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        documents.append({"filename": name, "path": str(dest)})
    RUNS[run_id] = {"status": "starting", "pending": None}
    state = {"run_id": run_id, "service_request": "Scholarship application", "scheme": scheme,
             "profile": {}, "documents": documents, "portal_url": TESTBED_URL, "step_log": [],
             "status": "starting", "phase": "fill"}
    _launch(run_id, state)
    return {"run_id": run_id}
