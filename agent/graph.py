"""The LangGraph workflow.

intake -> confirm_profile (pause) -> check_eligibility -> eligibility_gate (pause) -> fill
-> human/info pauses as needed -> approval (pause) -> submit -> receipt
"""
import asyncio
import hashlib
import json
import re
import time

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel

from agent.browser.actions import FINAL_SUBMIT
from agent.browser.decide import redact
from agent.browser.loop import run_browser_task
from agent.config import MIN_AUTO_CONFIDENCE, RECEIPT_DIR
from agent.documents import build_profile, read_document
from agent.eligibility import RULE_FIELDS, SCHEMES, evaluate, extract_rules, fetch_guideline
from agent.evidence import build_evidence_pdf
from agent.skills import learn, load_skill
from agent.ledger import FORMATS
from agent.llm import LLMUnavailable, generate_json
from agent.runtime import browsers, bus
from agent.state import EligibilityRule, RunState

FILL_GOAL = ("Apply for the scholarship on this portal using the applicant's profile and documents. "
             "Log in with the applicant's mobile number, complete every form page, upload the documents, "
             "and stop when the Review page is shown. Do not submit.")
SUBMIT_GOAL = ("The user has reviewed the application and APPROVED final submission. On the Review page, "
               "tick the declaration checkbox and click the Final Submit button. When the Acknowledgement "
               "page showing an Application ID is displayed, return done.")

# Details that are not printed on marksheets; the user declares them.
DECLARED_FIELDS = [
    ("gender", "Gender", ["Male", "Female", "Transgender"]),
    ("category", "Category", ["General", "OBC", "SC", "ST", "EWS"]),
    ("mobile", "Mobile number", None),
    ("institution", "Institution", None),
    ("course", "Course", ["B.Tech", "B.E.", "B.Sc", "B.Com", "B.A.", "M.Tech", "Other"]),
    ("current_year", "Current year of study", ["1", "2", "3", "4", "5"]),
    ("study_mode", "Study mode", ["regular", "correspondence", "distance"]),
    ("family_income", "Annual family income (Rs, digits only)", None),
]


def _emitter(run_id: str):
    async def emit(type_, message, data):
        await bus.publish(run_id, type_, message, data)
    return emit


def _source(f: dict) -> str:
    prov = f["provenance"]
    return prov["kind"] + (f" ({prov['document_type']})" if prov.get("document_type") else "")


def _public_fields(profile: dict) -> list[dict]:
    return [{"key": k, "value": f["value"], "source": _source(f),
             "confidence": f["provenance"].get("confidence", 1.0), "confirmed": f.get("confirmed", False)}
            for k, f in sorted(profile.items())]


# ---------- Documents & profile ----------

async def intake(state: RunState):
    if state.get("profile"):
        return {}                                    # profile supplied directly (saved-profile runs)
    run_id = state["run_id"]
    await bus.publish(run_id, "node", "Reading the citizen's documents")
    docs = []
    for d in state["documents"]:
        await bus.publish(run_id, "log", f"Reading {d['filename']}")
        r = await asyncio.to_thread(read_document, d["path"])
        r["path"], r["filename"] = d["path"], d["filename"]
        docs.append(r)
        await bus.publish(run_id, "observe",
                          f"{r['doc_type']}: {len(r['fields'])} fields "
                          f"({'checked against text layer' if r['has_text_layer'] else 'image only'})",
                          {"doc_type": r["doc_type"], "fields": [
                              {"key": f["key"], "confidence": f["confidence"], "check": f["check"]}
                              for f in r["fields"]]})
    profile, mismatches = build_profile(docs)
    if mismatches:
        await bus.publish(run_id, "verify", f"{len(mismatches)} mismatch(es) across documents",
                          {"fields": [m["field"] for m in mismatches]})
    documents = [{"id": d["doc_type"], "filename": d["filename"], "path": d["path"], "doc_type": d["doc_type"],
                  "extracted": {f["key"]: f["value"] for f in d["fields"]}} for d in docs]
    return {"documents": documents, "profile": profile, "mismatches": mismatches}


async def confirm_profile(state: RunState):
    profile = {k: dict(v) for k, v in state["profile"].items()}
    uncertain = [k for k, f in profile.items()
                 if not f.get("confirmed") and f["provenance"].get("confidence", 1.0) < MIN_AUTO_CONFIDENCE]
    missing = [{"key": k, "label": label, "options": opts} for k, label, opts in DECLARED_FIELDS if k not in profile]
    mismatches = state.get("mismatches") or []
    if not uncertain and not missing and not mismatches:
        return {}
    answer = interrupt({"kind": "confirm_profile", "fields": _public_fields(profile),
                        "uncertain": uncertain, "mismatches": mismatches, "missing": missing})
    values = answer.get("values", {}) if isinstance(answer, dict) else {}
    changed = 0
    for key, value in values.items():
        value = str(value).strip()
        if not value:
            continue
        if key in profile and profile[key]["value"] == value:
            profile[key]["confirmed"] = True          # user confirmed the document's own value
        else:
            profile[key] = {"key": key, "value": value, "confirmed": True,
                            "provenance": {"kind": "user", "confidence": 1.0}}
        changed += 1
    await bus.publish(state["run_id"], "log", f"User confirmed or provided {changed} value(s)")
    return {"profile": profile, "mismatches": []}


# ---------- Eligibility ----------

async def check_eligibility(state: RunState):
    run_id = state["run_id"]
    scheme = state.get("scheme_source") or SCHEMES[state.get("scheme") or "csss"]
    await bus.publish(run_id, "node", f"Checking eligibility: {scheme['name']}")
    try:
        source = await fetch_guideline(browsers.browser, scheme["url"])
    except Exception as e:
        await bus.publish(run_id, "error", f"Could not fetch the official page: {str(e)[:150]}")
        return {"verdict": "needs_review", "eligibility": [],
                "guideline": {"name": scheme["name"], "url": scheme["url"], "error": str(e)[:200]}}
    await bus.publish(run_id, "observe", f"Fetched official page ({len(source['text'])} chars) at {source['fetched_at']}",
                      {"url": source["url"], "sha256": source["sha256"]})
    try:
        rules, dropped = await asyncio.to_thread(extract_rules, source)
    except LLMUnavailable as e:
        await bus.publish(run_id, "error", f"Model unavailable for rule extraction: {e}")
        rules, dropped = [], []
    if dropped:
        await bus.publish(run_id, "security", f"Dropped {len(dropped)} rule(s) whose quote was not in the official text",
                          {"dropped": [f"{d.field} {d.op} {d.value}" for d in dropped]})
    values = {k: f["value"] for k, f in state["profile"].items()}
    verdict, results = evaluate(rules, values)
    await bus.publish(run_id, "verify", f"Eligibility verdict: {verdict} ({len(rules)} rules with verified quotes)",
                      {"verdict": verdict})
    return {"verdict": verdict, "eligibility": [r.model_dump() for r in results],
            "guideline": {"name": scheme["name"], "url": source["url"], "fetched_at": source["fetched_at"],
                          "sha256": source["sha256"], "dropped": len(dropped)}}


async def eligibility_gate(state: RunState):
    if state.get("verdict") == "eligible":
        return {"status": "proceed"}
    results = state.get("eligibility", [])
    askable = sorted({r["rule"]["field"] for r in results
                      if r.get("passed") is None and r["rule"]["field"] in RULE_FIELDS and r["rule"]["field"] != "other"})
    answer = interrupt({"kind": "eligibility", "verdict": state.get("verdict"), "results": results,
                        "guideline": state.get("guideline", {}), "askable": askable})
    declared = {}
    if isinstance(answer, dict):
        declared = {k: str(v).strip() for k, v in (answer.get("values") or {}).items() if str(v).strip()}
    if declared:
        profile = dict(state["profile"])
        for k, v in declared.items():
            profile[k] = {"key": k, "value": v, "confirmed": True, "provenance": {"kind": "user", "confidence": 1.0}}
        rules = [EligibilityRule(**r["rule"]) for r in results]
        verdict, new = evaluate(rules, {k: f["value"] for k, f in profile.items()})
        await bus.publish(state["run_id"], "verify",
                          f"Eligibility re-checked with user-declared {', '.join(declared)}: {verdict}", {"verdict": verdict})
        return {"profile": profile, "verdict": verdict, "eligibility": [x.model_dump() for x in new], "status": "recheck"}
    proceed = isinstance(answer, dict) and answer.get("proceed") is True
    await bus.publish(state["run_id"], "log",
                      "User chose to proceed despite the eligibility result" if proceed else "User stopped the application")
    return {"status": "proceed" if proceed else "stopped_by_user"}


# ---------- Browser phases ----------

async def _run_browser(state: RunState, goal: str, allow_submit: bool):
    run_id = state["run_id"]
    page = await browsers.page_for(run_id)
    start = state["portal_url"] if page.url in ("about:blank", "") else None
    old = list(state.get("step_log", []))
    history = list(old)
    result = await run_browser_task(page, goal=goal, profile=state["profile"], documents=state["documents"],
                                    run_id=run_id, start_url=start, emit=_emitter(run_id),
                                    allow_final_submit=allow_submit, history=history,
                                    skill=load_skill(state["portal_url"]))
    return result, history[len(old):]


async def fill(state: RunState):
    await bus.publish(state["run_id"], "node", "Filling the application form")
    sk = load_skill(state["portal_url"])
    if sk and not state.get("step_log"):
        await bus.publish(state["run_id"], "log", f"Learned skill v{sk['version']} found for this portal "
                          f"({len(sk['pages'])} pages); replaying wherever pages still match")
    result, new_steps = await _run_browser(state, FILL_GOAL, allow_submit=False)
    return {"phase": "fill", "status": result["status"], "error": result["reason"], "step_log": new_steps}


async def submit(state: RunState):
    run_id = state["run_id"]
    marker = RECEIPT_DIR / f"{run_id}.final_submit"
    if marker.exists():          # re-entered after an interruption that happened after the click
        page = await browsers.page_for(run_id)
        try:
            text = await page.inner_text("body")
        except Exception:
            text = ""
        if ID_PATTERN.search(text):
            return {"phase": "submit", "status": "done", "error": None}
        msg = (f"Duplicate protection: Final Submit was already clicked for this application at "
               f"{marker.read_text().strip()}. Not submitting again. Check the status on the portal's Track page.")
        await bus.publish(run_id, "security", msg)
        return {"phase": "submit", "status": "already_submitted", "error": msg}
    await bus.publish(state["run_id"], "node", "Submitting with the user's approval")
    result, new_steps = await _run_browser(state, SUBMIT_GOAL, allow_submit=True)
    return {"phase": "submit", "status": result["status"], "error": result["reason"], "step_log": new_steps}


async def human_gate(state: RunState):
    try:   # make sure the citizen sees THIS run's window, not an older one
        await (await browsers.page_for(state["run_id"])).bring_to_front()
    except Exception:
        pass
    interrupt({"kind": "human_step", "reason": state.get("error") or "A human step is needed"})
    return {"status": "resumed"}


async def info_gate(state: RunState):
    reason = state.get("error") or ""
    m = re.search(r"'(\w+)'", reason)
    answer = interrupt({"kind": "missing_info", "reason": reason, "suggested_key": m.group(1) if m else "",
                        "known_fields": sorted(state["profile"])})
    profile = dict(state["profile"])
    if isinstance(answer, dict) and answer.get("key") and answer.get("value"):
        key = str(answer["key"]).strip()
        profile[key] = {"key": key, "value": str(answer["value"]).strip(),
                        "provenance": {"kind": "user", "confidence": 1.0}, "confirmed": True}
        await bus.publish(state["run_id"], "log", f"User provided '{key}'")
    return {"profile": profile, "status": "resumed"}


def _unverified_rows(rows: list, profile: dict) -> list:
    """Review-page values that do not match any verified profile value (in any allowed format)."""
    known = set()
    for f in profile.values():
        v = str(f.get("value", ""))
        known.add(v.strip().lower())
        for fn in FORMATS.values():
            try:
                known.add(str(fn(v)).strip().lower())
            except Exception:
                pass
    return [[label, value] for label, value in rows
            if value and not re.search(r"\.(pdf|jpe?g|png|webp)$", value, re.I)
            and value.strip().lower() not in known]


REVIEW_JS = """() => [...document.querySelectorAll('tr')]
  .map(tr => [tr.querySelector('th')?.innerText.trim(), tr.querySelector('td')?.innerText.trim()])
  .filter(r => r[0])"""


async def prepare_approval(state: RunState):
    """Reads the portal's review table once and saves it in the checkpoint."""
    page = await browsers.page_for(state["run_id"])
    try:
        rows = await page.evaluate(REVIEW_JS)
    except Exception:
        rows = []
    if any(str(r[0]).strip().lower() == "application id" for r in rows):
        await bus.publish(state["run_id"], "security",
                          "Safety violation: the portal shows an acknowledgement before approval. Stopping.")
        return {"status": "safety_stop", "review_rows": rows}
    unverified = _unverified_rows(rows, state["profile"])
    if unverified:
        await bus.publish(state["run_id"], "security",
                          f"{len(unverified)} value(s) on the portal's review page do not match the verified profile",
                          {"flagged": [f"{l}: {v}" for l, v in unverified]})
    else:
        await bus.publish(state["run_id"], "verify",
                          "Review page cross-checked: every value matches the verified profile", {"ok": True})
    return {"status": "awaiting_approval", "review_rows": rows}


async def approval(state: RunState):
    """Pauses for the user. On resume (even after a crash) it uses the saved rows, not the live page."""
    rows = state.get("review_rows", [])
    decision = interrupt({"kind": "approval", "rows": rows,
                          "unverified": _unverified_rows(rows, state["profile"]),
                          "sources": {k: _source(f) for k, f in state["profile"].items()}})
    approved = decision.get("approved") is True if isinstance(decision, dict) else decision is True
    await bus.publish(state["run_id"], "log", "User approved submission" if approved else "User declined submission")
    return {"status": "approved" if approved else "cancelled"}


def reliability(step_log: list) -> dict:
    """Measured from the verified execution log, not estimated."""
    steps = step_log or []
    field = [s for s in steps if (s.get("action") or {}).get("type") in ("fill", "select", "check", "upload")]
    model_plans = {s.get("plan_key") for s in steps if s.get("source") == "model"}
    replays = {s.get("plan_key") for s in steps if s.get("source") == "skill"}
    ok = sum(1 for s in steps if s.get("ok"))
    return {
        "actions": len(steps),
        "verified_actions": ok,
        "verification_rate": round(100 * ok / len(steps), 1) if steps else 0.0,
        "field_checks": len(field),
        "fields_verified": sum(1 for s in field if s.get("ok")),
        "failed_checks": len(steps) - ok,
        "retried_actions": sum(1 for s in steps if (s.get("recovery_rung") or 0) > 0),
        "model_plans": len(model_plans),
        "learned_replays": len(replays),
        "final_submit_clicks": sum(1 for s in steps if s.get("target") and FINAL_SUBMIT.search(s["target"]["label"])
                                   and s.get("ok")),
    }


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
    if not app_id or app_id not in text:
        m = ID_PATTERN.search(text)
        app_id, method = (m.group(1) if m else None), "pattern"
    verified = bool(app_id and app_id in text)
    shot = RECEIPT_DIR / f"{run_id}_ack.png"
    await page.screenshot(path=str(shot), full_page=True)
    rec = {
        "run_id": run_id, "application_id": app_id, "status": status, "verified_on_page": verified,
        "extraction_method": method, "url": page.url, "screenshot": str(shot),
        "screenshot_sha256": hashlib.sha256(shot.read_bytes()).hexdigest(),
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "steps_taken": len(state.get("step_log", [])), "review_rows": state.get("review_rows", []),
        "eligibility_verdict": state.get("verdict"), "guideline": state.get("guideline", {}),
        "reliability": reliability(state.get("step_log", [])),
    }
    skill = learn(state["portal_url"], state.get("step_log", []))
    if skill:
        rec["skill_version"] = skill["version"]
        await bus.publish(run_id, "log", f"Learned skill saved: v{skill['version']} covering "
                          f"{len(skill['pages'])} page(s)")
    rec["review_unverified"] = _unverified_rows(rec["review_rows"], state["profile"])
    try:
        pdf, pdf_hash = build_evidence_pdf(rec, state)
        rec["evidence_pdf"], rec["evidence_sha256"] = pdf, pdf_hash
    except Exception as e:
        await bus.publish(run_id, "error", f"Evidence pack failed: {str(e)[:150]}")
    (RECEIPT_DIR / f"{run_id}.json").write_text(json.dumps(rec, indent=2))
    await bus.publish(run_id, "receipt",
                      f"Receipt captured: {app_id} ({'verified on page' if verified else 'NOT verified'})", rec)
    return {"receipt": rec, "status": "completed"}


# ---------- Routing ----------

def after_gate(state: RunState):
    s = state.get("status")
    return "fill" if s == "proceed" else ("eligibility_gate" if s == "recheck" else END)


def after_browser(state: RunState):
    s = state["status"]
    if s == "already_submitted":
        return END
    if s == "done":
        return "prepare_approval" if state["phase"] == "fill" else "receipt"
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
    for name, fn in [("intake", intake), ("confirm_profile", confirm_profile),
                     ("check_eligibility", check_eligibility), ("eligibility_gate", eligibility_gate),
                     ("fill", fill), ("submit", submit), ("human_gate", human_gate), ("info_gate", info_gate),
                     ("prepare_approval", prepare_approval), ("approval", approval), ("receipt", receipt)]:
        g.add_node(name, fn)
    g.add_edge(START, "intake")
    g.add_edge("intake", "confirm_profile")
    g.add_edge("confirm_profile", "check_eligibility")
    g.add_edge("check_eligibility", "eligibility_gate")
    g.add_conditional_edges("eligibility_gate", after_gate, ["fill", "eligibility_gate", END])
    g.add_conditional_edges("fill", after_browser, ["prepare_approval", "human_gate", "info_gate", END])
    g.add_conditional_edges("prepare_approval",
                            lambda s: "approval" if s.get("status") == "awaiting_approval" else END,
                            ["approval", END])
    g.add_conditional_edges("submit", after_browser, ["receipt", "human_gate", "info_gate", END])
    g.add_conditional_edges("human_gate", back_to_phase, ["fill", "submit"])
    g.add_conditional_edges("info_gate", back_to_phase, ["fill", "submit"])
    g.add_conditional_edges("approval", after_approval, ["submit", END])
    g.add_edge("receipt", END)
    return g.compile(checkpointer=checkpointer)
