"""Reliability benchmark: runs the browser agent against the test portal once per fault scenario
and measures what actually happened (from the verified execution log).

The harness plays the citizen: when the agent stops for the OTP, the harness types the OTP from the
test portal's outbox, exactly as a person would read it from their phone. The agent never reads OTPs.

Each run fills the form and stops at the Review page. Nothing is ever submitted.

Usage:   python -m scripts.benchmark            (uses the learned skill, like the real product)
         python -m scripts.benchmark --no-skill (model plans every page; uses more API quota)
         add --show to watch the browser
Needs the test portal running on port 8001.
"""
import argparse
import asyncio
import json
import time
import uuid

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from playwright.async_api import async_playwright

from agent.browser.loop import run_browser_task
from agent.config import CHECKPOINT_DB, DATA_DIR, RECEIPT_DIR, TESTBED_URL
from agent.graph import FILL_GOAL, build_graph, REVIEW_JS, _unverified_rows, reliability
from agent.skills import load_skill
from testbed import db

SCENARIOS = [
    ("baseline", []),
    ("popup", ["popup"]),
    ("layout_drift", ["layout_drift"]),
    ("validation_error", ["validation_error"]),
    ("prompt_injection", ["injection"]),
    ("session_expiry", ["session_expiry"]),
    ("slow_network", ["slow_network"]),
    ("all_faults_together", list(db.FAULTS)),
]
OUT_DIR = DATA_DIR / "benchmark"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def reset_portal():
    with db._conn() as c:
        c.execute("DELETE FROM drafts")
        c.execute("DELETE FROM sessions")
    for f in db.FAULTS:
        db.set_fault(f, False)


def latest_otp(mobile: str):
    with db._conn() as c:
        r = c.execute("SELECT message FROM outbox WHERE mobile=? ORDER BY id DESC LIMIT 1", (mobile,)).fetchone()
    import re
    m = re.search(r"\b(\d{4,8})\b", r["message"]) if r else None
    return m.group(1) if m else None


async def run_one(browser, name, faults, profile, documents, skill):
    reset_portal()
    for f in faults:
        db.set_fault(f, True)
    ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
    page = await ctx.new_page()
    run_id = f"bench-{name}-{uuid.uuid4().hex[:4]}"
    events, history = [], []

    def emit(type_, message, data):
        events.append({"type": type_, "message": message})

    t0 = time.time()
    start, human_steps, result = TESTBED_URL, 0, {"status": "failed", "reason": "not started"}
    while human_steps <= 4:
        result = await run_browser_task(page, goal=FILL_GOAL, profile=profile, documents=documents, run_id=run_id,
                                        start_url=start, emit=emit, history=history, skill=skill)
        start = None
        if result["status"] == "needs_human" and "otp" in result["reason"].lower():
            human_steps += 1
            otp = latest_otp(profile["mobile"]["value"])
            if not otp:
                break
            await page.fill("#otp", otp)          # the "citizen" types the OTP; the agent then clicks Verify
            continue
        break
    seconds = round(time.time() - t0, 1)
    on_review = page.url.rstrip("/").endswith("/review")
    rows = await page.evaluate(REVIEW_JS) if on_review else []
    wrong = _unverified_rows(rows, profile) if on_review else []
    await ctx.close()
    reset_portal()
    rel = reliability(history)
    return {
        "scenario": name, "faults": faults,
        "reached_review": on_review and result["status"] == "done",
        "review_values_correct": on_review and not wrong, "wrong_values": wrong,
        "final_status": result["status"], "reason": result["reason"],
        "seconds": seconds, "otp_steps_by_citizen": human_steps,
        "recover_events": sum(1 for e in events if e["type"] == "recover"),
        "security_events": sum(1 for e in events if e["type"] == "security"),
        **rel,
    }


async def last_confirmed_profile():
    """The profile and documents from the citizen's latest completed run (confirmed by them, verified receipt)."""
    for f in sorted(RECEIPT_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        rec = json.loads(f.read_text())
        if not rec.get("verified_on_page"):
            continue
        async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB)) as saver:
            snap = await build_graph(saver).aget_state({"configurable": {"thread_id": rec["run_id"]}})
        v = snap.values or {}
        if v.get("profile") and v.get("documents"):
            return v["profile"], v["documents"], rec["run_id"]
    raise SystemExit("No completed run found. Complete one application in the UI first.")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-skill", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--only", help="run a single scenario by name")
    args = ap.parse_args()
    profile, documents, source_run = await last_confirmed_profile()
    print(f"Using the confirmed profile from completed run {source_run} ({len(profile)} fields)")
    skill = None if args.no_skill else load_skill(TESTBED_URL)
    db.init()
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not args.show, slow_mo=50 if args.show else 0)
        for name, faults in SCENARIOS:
            if args.only and name != args.only:
                continue
            print(f"\n>>> {name} (faults: {', '.join(faults) or 'none'}) ...", flush=True)
            try:
                r = await run_one(browser, name, faults, profile, documents, skill)
            except Exception as e:
                reset_portal()
                r = {"scenario": name, "faults": faults, "reached_review": False, "review_values_correct": False,
                     "final_status": "crashed", "reason": str(e)[:200]}
            results.append(r)
            print(f"    {'PASS' if r['reached_review'] and r['review_values_correct'] else 'FAIL'}: "
                  f"{r.get('final_status')} - {r.get('reason', '')[:90]}", flush=True)
        await browser.close()

    stamp = time.strftime("%Y%m%d-%H%M%S")
    (OUT_DIR / f"results-{stamp}.json").write_text(json.dumps(results, indent=2))
    head = ["Scenario", "Result", "Values correct", "Verified actions", "Failed checks", "Retries",
            "Model plans", "Replays", "Security", "Time (s)"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in results:
        lines.append("| " + " | ".join(str(x) for x in [
            r["scenario"], "PASS" if r["reached_review"] else "FAIL", "yes" if r["review_values_correct"] else "NO",
            f"{r.get('verified_actions', '-')}/{r.get('actions', '-')}", r.get("failed_checks", "-"),
            r.get("retried_actions", "-"), r.get("model_plans", "-"), r.get("learned_replays", "-"),
            r.get("security_events", "-"), r.get("seconds", "-")]) + " |")
    passed = sum(1 for r in results if r["reached_review"] and r["review_values_correct"])
    summary = (f"\nReached the Review page with every value correct in {passed}/{len(results)} scenarios. "
               f"Skill: {'off' if args.no_skill else 'on'}. Nothing was submitted.")
    table = "\n".join(lines) + summary
    (OUT_DIR / f"results-{stamp}.md").write_text(table + "\n")
    print("\n" + table)
    print(f"\nSaved: data/benchmark/results-{stamp}.json and .md")


if __name__ == "__main__":
    asyncio.run(main())
