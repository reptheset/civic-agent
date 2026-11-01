"""The observe -> decide -> act -> verify -> recover loop.

It stops and returns whenever it needs something it must not do alone:
a human step (OTP/CAPTCHA), missing information, or the goal is reached.
"""
import asyncio
import re
from urllib.parse import urlparse

from agent.browser.actions import ActionBlocked, execute, verify_click, verify_field
from agent.browser.decide import decide
from agent.browser.observe import observe
from agent.config import ALLOWED_HOSTS, SCREENSHOT_DIR
from agent.ledger import BadReference, MissingProvenance
from agent.llm import LLMUnavailable
from agent.state import Action, StepLog

HUMAN_FIELD = re.compile(r"\botp\b|one[- ]time|captcha|password|verification code", re.I)


async def _emit(emit, type_: str, message: str, **data):
    if emit:
        r = emit(type_, message, data)
        if asyncio.iscoroutine(r):
            await r


def human_step_needed(obs: dict):
    for e in obs["elements"]:
        if (e["tag"] in ("input", "textarea") and e.get("type") not in ("file", "checkbox", "radio", "submit")
                and HUMAN_FIELD.search(e["label"]) and not e.get("filled")):
            return f"The page needs a human step: {e['label']}"
    return None


async def act_with_recovery(page, action: Action, obs: dict, profile, documents, emit,
                            allow_final_submit: bool) -> tuple[bool, str, int]:
    """Rungs 1-2 happen here. Rung 3 (re-plan) happens when the failure note reaches the LLM."""
    last_error = ""
    for rung in (0, 1, 2):
        try:
            if rung == 1:
                await _emit(emit, "recover", "Rung 1: waiting for the page to settle, then retrying")
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
            if rung == 2:
                if action.type != "fill":
                    break
                await _emit(emit, "recover", "Rung 2: typing with the keyboard instead")
            expected = await execute(page, action, obs, profile, documents,
                                     allow_final_submit, keyboard=(rung == 2))
            if action.type == "click":
                after = await observe(page)
                ok, note = verify_click(obs, after)
            else:
                ok, note = await verify_field(page, action, expected)
            return ok, note, rung
        except (MissingProvenance,):
            raise
        except (BadReference, ActionBlocked) as e:
            return False, str(e), rung          # retrying the same thing will not help
        except Exception as e:
            last_error = str(e).split("\n")[0][:200]
    await _emit(emit, "recover", "Rung 3: reporting the failure to the planner to re-plan")
    return False, f"action failed: {last_error}", 3


async def run_browser_task(page, *, goal: str, profile: dict, documents: list, run_id: str,
                           start_url: str | None = None, emit=None, max_rounds: int = 25,
                           allow_final_submit: bool = False, history: list | None = None) -> dict:
    """Each round: observe once, get a plan for the page from one model call, execute it
    action by action with verification. Re-plan when the page changes or an action fails."""
    history = history if history is not None else []
    shots = SCREENSHOT_DIR / run_id
    shots.mkdir(parents=True, exist_ok=True)
    if start_url:
        await page.goto(start_url, wait_until="domcontentloaded")

    failures = 0
    flagged_urls = set()
    for _ in range(max_rounds):
        host = urlparse(page.url).hostname
        if host not in ALLOWED_HOSTS:
            await _emit(emit, "security", f"Blocked navigation to non-allowed host '{host}'; going back")
            await page.go_back()
            continue

        obs = await observe(page)
        if obs["injection_flags"] and obs["url"] not in flagged_urls:
            flagged_urls.add(obs["url"])
            await _emit(emit, "security", "Possible prompt injection removed from page text",
                        flagged=obs["injection_flags"])
        await _emit(emit, "observe", f"{obs['title']} - {len(obs['elements'])} elements",
                    url=obs["url"], alerts=obs["alerts"], dialogs=obs["dialogs"])

        reason = human_step_needed(obs)
        if reason:
            return {"status": "needs_human", "reason": reason, "url": page.url, "history": history}

        try:
            plan = await asyncio.to_thread(decide, goal, obs, profile, documents, history)
        except LLMUnavailable as e:
            await _emit(emit, "error", f"Model unavailable: {e}")
            return {"status": "failed", "reason": "model unavailable", "url": page.url, "history": history}

        actions = plan.actions[:12] or [Action(type="done", reason=plan.reason or "goal reached")]
        await _emit(emit, "decide", f"Plan with {len(actions)} action(s): {plan.reason}",
                    plan=[a.model_dump() for a in actions])
        if actions[0].type == "done":
            return {"status": "done", "reason": actions[0].reason, "url": page.url, "history": history}
        if actions[0].type == "need_info":
            key = (actions[0].value_ref or "").split("|")[0].replace("profile.", "") or "unknown"
            return {"status": "needs_info", "reason": f"No value on record for '{key}': {actions[0].reason}",
                    "url": page.url, "history": history}
        if actions[0].type == "ask_human":
            return {"status": "needs_human", "reason": actions[0].reason, "url": page.url, "history": history}

        for action in actions:
            if action.type in ("done", "ask_human", "need_info"):
                break                       # handled on the next round, after re-observing
            step = len(history) + 1
            await _emit(emit, "act", f"{action.type} el={action.element_id} ref={action.value_ref} - {action.reason}")
            try:
                ok, note, rung = await act_with_recovery(page, action, obs, profile, documents, emit,
                                                         allow_final_submit)
            except MissingProvenance as e:
                return {"status": "needs_info", "reason": str(e), "url": page.url, "history": history}

            shot = shots / f"{step:03d}.png"
            try:
                await page.screenshot(path=str(shot))
            except Exception:
                shot = None
            history.append(StepLog(step=step, url=page.url, action=action, ok=ok, verify_note=note,
                                   recovery_rung=rung, screenshot=str(shot) if shot else None).model_dump())
            await _emit(emit, "verify", f"{'OK' if ok else 'FAILED'}: {note}", ok=ok, rung=rung)

            failures = 0 if ok else failures + 1
            if not ok or action.type == "click":
                break                       # page changed or something failed: re-observe and re-plan

        if failures == 4:
            await _emit(emit, "recover", "Rung 4: 4 failures in a row, reloading the page")
            await page.reload(wait_until="domcontentloaded")
        if failures >= 6:
            return {"status": "needs_human", "reason": "Stuck after repeated failures", "url": page.url,
                    "history": history}

    return {"status": "failed", "reason": "round limit reached", "url": page.url, "history": history}
