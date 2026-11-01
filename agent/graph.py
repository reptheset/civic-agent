"""The LangGraph workflow: fill -> (human / missing-info pauses) -> approval -> submit -> receipt."""
import asyncio
import hashlib
import json
import re
import time

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel

from agent.browser.decide import redact
from agent.browser.loop import run_browser_task
from agent.config import RECEIPT_DIR
from agent.llm import LLMUnavailable, generate_json
from agent.runtime import browsers, bus
from agent.state import RunState

FILL_GOAL = ("Apply for the scholarship on this portal using the applicant's profile and documents. "
             "Log in with the applicant's mobile number, complete every form page, upload the documents, "
             "and stop when the Review page is shown. Do not submit.")
SUBMIT_GOAL = ("The user has reviewed the application and APPROVED final submission. On the Review page, "
               "tick the declaration checkbox and click the Final Submit button. When the Acknowledgement "
               "page showing an Application ID is displayed, return done.")


def _emitter(run_id: str):
    async def emit(type_, message, data):
        await bus.publish(run_id, type_, message, data)
    return emit


async def _run_browser(state: RunState, goal: str, allow_submit: bool):
    run_id = state["run_id"]
    page = await browsers.page_for(run_id)
    # A blank page means a new browser (first run, or after a server restart): open the portal.
    start = state["portal_url"] if page.url in ("about:blank", "") else None
    old = list(state.get("step_log", []))
    history = list(old)
    result = await run_browser_task(page, goal=goal, profile=state["profile"], documents=state["documents"],
                                    run_id=run_id, start_url=start, emit=_emitter(run_id),
                                    allow_final_submit=allow_submit, history=history)
    return result, history[len(old):]


# ---------- Nodes ----------

async def fill(state: RunState):
    await bus.publish(state["run_id"], "node", "Filling the application form")
    result, new_steps = await _run_browser(state, FILL_GOAL, allow_submit=False)
    return {"phase": "fill", "status": result["status"], "error": result["reason"], "step_log": new_steps}


async def submit(state: RunState):
    await bus.publish(state["run_id"], "node", "Submitting with the user's approval")
    result, new_steps = await _run_browser(state, SUBMIT_GOAL, allow_submit=True)
    return {"phase": "submit", "status": result["status"], "error": result["reason"], "step_log": new_steps}


async def human_gate(state: RunState):
    interrupt({"kind": "human_step", "reason": state.get("error") or "A human step is needed"})
    return {"status": "resumed"}


async def info_gate(state: RunState):
    answer = interrupt({"kind": "missing_info", "reason": state.get("error"),
                        "known_fields": sorted(state["profile"])})
    profile = dict(state["profile"])
    if isinstance(answer, dict) and answer.get("key") and answer.get("value"):
        key = str(answer["key"]).strip()
        profile[key] = {"key": key, "value": str(answer["value"]).strip(),
                        "provenance": {"kind": "user", "confidence": 1.0}, "confirmed": True}
        await bus.publish(state["run_id"], "log", f"User provided '{key}'")
    return {"profile": profile, "status": "resumed"}


REVIEW_JS = """() => [...document.querySelectorAll('tr')]
  .map(tr => [tr.querySelector('th')?.innerText.trim(), tr.querySelector('td')?.innerText.trim()])
  .filter(r => r[0])"""


async def approval(state: RunState):
    page = await browsers.page_for(state["run_id"])
    try:
        rows = await page.evaluate(REVIEW_JS)
    except Exception:
        rows = []
    sources = {}
    for key, f in state["profile"].items():
        prov = f["provenance"]
        sources[key] = prov["kind"] + (f" ({prov['document_type']})" if prov.get("document_type") else "")
    decision = interrupt({"kind": "approval", "rows": rows, "sources": sources})
    approved = decision.get("approved") is True if isinstance(decision, dict) else decision is True
    await bus.publish(state["run_id"], "log", "User approved submission" if approved else "User declined submission")
    return {"status": "approved" if approved else "cancelled", "review_rows": rows}


class AckExtract(BaseModel):
    application_id: str
    status: str = ""


ID_PATTERN = re.compile(r"Application ID\s*[:\-]?\s*([A-Z0-9][A-Z0-9/-]{5,})", re.I)


async def receipt(state: RunState):
    run_id = state["run_id"]
    page = await browsers.page_for(run_id)
    await bus.publish(run_id, "node", "Capturing the acknowledgement receipt")
    text = await page.inner_text("body")

    app_id, status, method = None, "", "model"
    try:
        ext = await asyncio.to_thread(
            generate_json,
            "Extract the application or reference ID and the application status from this "
            "acknowledgement page.\n<<<\n" + redact(text[:3000], state["profile"]) + "\n>>>",
            AckExtract)
        app_id, status = ext.application_id.strip(), ext.status.strip()
    except LLMUnavailable:
        pass
    if not app_id or app_id not in text:          # never trust an ID that is not on the page
        m = ID_PATTERN.search(text)
        app_id, method = (m.group(1) if m else None), "pattern"
    verified = bool(app_id and app_id in text)

    shot = RECEIPT_DIR / f"{run_id}_ack.png"
    await page.screenshot(path=str(shot), full_page=True)
    rec = {
        "run_id": run_id,
        "application_id": app_id,
        "status": status,
        "verified_on_page": verified,
        "extraction_method": method,
        "url": page.url,
        "screenshot": str(shot),
        "screenshot_sha256": hashlib.sha256(shot.read_bytes()).hexdigest(),
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "steps_taken": len(state.get("step_log", [])),
        "review_rows": state.get("review_rows", []),
    }
    (RECEIPT_DIR / f"{run_id}.json").write_text(json.dumps(rec, indent=2))
    await bus.publish(run_id, "receipt",
                      f"Receipt captured: {app_id} ({'verified on page' if verified else 'NOT verified'})", rec)
    return {"receipt": rec, "status": "completed"}


# ---------- Routing ----------

def after_browser(state: RunState):
    s = state["status"]
    if s == "done":
        return "approval" if state["phase"] == "fill" else "receipt"
    if s == "needs_human":
        return "human_gate"
    if s == "needs_info":
        return "info_gate"
    return END


def back_to_phase(state: RunState):
    return state.get("phase", "fill")


def after_approval(state: RunState):
    return "submit" if state["status"] == "approved" else END


def build_graph(checkpointer):
    g = StateGraph(RunState)
    for name, fn in [("fill", fill), ("submit", submit), ("human_gate", human_gate),
                     ("info_gate", info_gate), ("approval", approval), ("receipt", receipt)]:
        g.add_node(name, fn)
    g.add_edge(START, "fill")
    g.add_conditional_edges("fill", after_browser, ["approval", "human_gate", "info_gate", END])
    g.add_conditional_edges("submit", after_browser, ["receipt", "human_gate", "info_gate", END])
    g.add_conditional_edges("human_gate", back_to_phase, ["fill", "submit"])
    g.add_conditional_edges("info_gate", back_to_phase, ["fill", "submit"])
    g.add_conditional_edges("approval", after_approval, ["submit", END])
    g.add_edge("receipt", END)
    return g.compile(checkpointer=checkpointer)
