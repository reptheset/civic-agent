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

from agent.config import (CHECKPOINT_DB, CORS_ORIGIN_REGEX, CORS_ORIGINS, DATA_DIR, HEADLESS, RECEIPT_DIR,
                          SCREENSHOT_DIR, TESTBED_URL)
from agent.graph import build_graph
from agent.runtime import browsers, bus

RUNS: dict[str, dict] = {}      # run_id -> {"status", "pending"}
TASKS: set = set()              # keeps background tasks alive
GRAPH = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global GRAPH
    await browsers.start(headless=HEADLESS)
    async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB)) as saver:
        GRAPH = build_graph(saver)
        yield
    await browsers.stop()


app = FastAPI(title="Civic Agent API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_origin_regex=CORS_ORIGIN_REGEX,
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
        await browsers.close(run_id)
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


# ---------- Plain-language explanations in the citizen's language ----------
from agent.llm import LLMUnavailable, generate_json

LANGS = {
    "hi": ("Hindi", "Devanagari script (for example: \u092f\u094b\u091c\u0928\u093e)", (0x0900, 0x097F)),
    "or": ("Odia", "Odia script (for example: \u0b2f\u0b4b\u0b1c\u0b28\u0b3e)", (0x0B00, 0x0B7F)),
}


class ExplainReq(BaseModel):
    language: str
    verdict: str
    results: list[dict]


class Explanation(BaseModel):
    summary: str
    rules: list[str]


def _script_ok(ex: "Explanation", rng: tuple) -> bool:
    """At least 90% of non-ASCII letters must be in the requested script's Unicode block."""
    text = ex.summary + " ".join(ex.rules)
    letters = [c for c in text if c.isalpha() and ord(c) > 127]
    if not letters:
        return False
    good = sum(rng[0] <= ord(c) <= rng[1] for c in letters)
    return good / len(letters) >= 0.9


@app.post("/explain")
async def explain(body: ExplainReq):
    if body.language not in LANGS:
        raise HTTPException(400, "Unsupported language")
    lang, script, rng = LANGS[body.language]
    lines = "\n".join(f"- {r.get('reason', '')} (official rule: {(r.get('rule') or {}).get('quote', '')})"
                      for r in body.results)
    prompt = (f"Explain this scholarship eligibility result to a student in simple, polite {lang}, "
              f"written ONLY in {script}. Never use Urdu, Arabic, Bengali or any other script. "
              f"Field names like family_income and numbers may stay in English.\n"
              f"Verdict: {body.verdict}\nRule results:\n{lines}\n\n"
              f"Return 'summary' (at most 2 sentences) and 'rules': exactly one short line per rule, "
              f"in the same order. Keep every number exactly as given. Do not add rules, advice or facts "
              f"that are not above. 'needs review' means the data needed to decide is missing.")
    for _ in range(2):
        try:
            ex = await asyncio.to_thread(generate_json, prompt, Explanation)
        except LLMUnavailable:
            raise HTTPException(503, "Model unavailable, try again")
        if _script_ok(ex, rng):
            return ex.model_dump()
    raise HTTPException(502, f"The model did not answer in {lang} script; showing English only")


# ---------- Application tracking after submission ----------
from agent.browser.decide import redact
from agent.browser.loop import run_browser_task
from agent.config import SCREENSHOT_DIR
from agent.graph import REVIEW_JS

TRACK_GOAL = ("Check the status of an already submitted application. Open the Track Application page, "
              "enter the application ID and the applicant's registered mobile number, and click the button that "
              "checks the status. When the page shows the application's status, return done. "
              "Do not log in and do not change anything.")


class StatusExtract(BaseModel):
    status: str


@app.post("/runs/{run_id}/track")
async def track_application(run_id: str):
    snap = await GRAPH.aget_state(_cfg(run_id))
    values = snap.values or {}
    rec = values.get("receipt") or {}
    app_id = rec.get("application_id")
    if not app_id:
        raise HTTPException(409, "No verified receipt for this run yet")
    profile = dict(values.get("profile") or {})
    profile["application_id"] = {"key": "application_id", "value": app_id, "confirmed": True,
                                 "provenance": {"kind": "document", "document_type": "receipt", "confidence": 1.0}}
    page_key = f"{run_id}-track"
    page = await browsers.page_for(page_key)

    async def emit(type_, message, data):
        await bus.publish(run_id, type_, message, data)

    await bus.publish(run_id, "node", f"Tracking application {app_id} on the portal")
    try:
        result = await run_browser_task(page, goal=TRACK_GOAL, profile=profile, documents=[], run_id=page_key,
                                        start_url=values.get("portal_url") or TESTBED_URL, emit=emit, max_rounds=8)
        if result["status"] != "done":
            await bus.publish(run_id, "error", f"Tracking stopped: {result['reason']}")
            raise HTTPException(502, result["reason"])
        text = await page.inner_text("body")
        status = None
        try:
            ex = await asyncio.to_thread(
                generate_json,
                "From this application tracking page, extract the application's current status exactly as written."
                "\n<<<\n" + redact(text[:3000], profile) + "\n>>>", StatusExtract)
            status = ex.status.strip()
        except LLMUnavailable:
            pass
        if not status or status not in text:      # never trust a status that is not on the page
            rows = await page.evaluate(REVIEW_JS)
            status = next((val for lab, val in rows if str(lab).strip().lower() == "status"), None)
        verified = bool(status and status in text)
        shot_rel = f"{page_key}/track.png"
        (SCREENSHOT_DIR / page_key).mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(SCREENSHOT_DIR / shot_rel), full_page=True)
        data = {"application_id": app_id, "status": status, "verified_on_page": verified,
                "checked_at": __import__("time").strftime("%Y-%m-%d %H:%M:%S"), "shot": shot_rel}
        await bus.publish(run_id, "track",
                          f"Status: {status} ({'verified on page' if verified else 'NOT verified'})", data)
        return data
    finally:
        await browsers.close(page_key)


# ---------- Hosted mode: the citizen's side of the human step, from the UI ----------
# On a server there is no visible browser window, so the citizen types the OTP into the UI and
# it is placed in the portal's field. The agent itself never reads, decides or types it.
from agent.browser.loop import HUMAN_FIELD
from testbed import db as portal_db


class HumanInput(BaseModel):
    value: str


@app.post("/runs/{run_id}/human-input")
async def human_input(run_id: str, body: HumanInput):
    run = RUNS.get(run_id)
    if not run or run["status"] != "waiting" or (run.get("pending") or {}).get("kind") != "human_step":
        raise HTTPException(409, "Run is not waiting for a human step")
    value = body.value.strip()
    if not value or len(value) > 64:
        raise HTTPException(400, "Enter the code")
    page = await browsers.page_for(run_id)
    for loc in await page.locator("input:not([type=hidden]):not([type=file]):not([type=checkbox])").all():
        label = await loc.evaluate("""e => ((e.labels && e.labels[0] && e.labels[0].innerText) || e.name ||
                                          e.id || e.placeholder || e.getAttribute('aria-label') || '')""")
        if HUMAN_FIELD.search(label or "") and await loc.is_visible():
            await loc.fill(value)
            await bus.publish(run_id, "log", "Citizen entered the code (the agent never sees or types it)")
            _launch(run_id, Command(resume={"done": True}))
            return {"ok": True}
    raise HTTPException(404, "No OTP field found on the current page")


@app.get("/runs/{run_id}/sms")
async def sms_inbox(run_id: str):
    """The test portal's simulated SMS to the citizen's own mobile number (stands in for their phone)."""
    snap = await GRAPH.aget_state(_cfg(run_id))
    mobile = (((snap.values or {}).get("profile") or {}).get("mobile") or {}).get("value", "")
    digits = "".join(c for c in str(mobile) if c.isdigit())[-10:]
    if not digits:
        return {"messages": []}
    with portal_db._conn() as c:
        rows = c.execute("SELECT message, created FROM outbox WHERE mobile=? ORDER BY id DESC LIMIT 3",
                         (digits,)).fetchall()
    return {"messages": [{"message": r["message"], "created": r["created"]} for r in rows]}


@app.get("/portal/faults")
async def portal_faults():
    return {"faults": portal_db.all_faults()}


@app.post("/portal/faults/{name}")
async def toggle_portal_fault(name: str):
    if name not in portal_db.FAULTS:
        raise HTTPException(404, "Unknown fault")
    portal_db.set_fault(name, not portal_db.fault_on(name))
    return {"faults": portal_db.all_faults()}
