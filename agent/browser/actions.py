"""Executes one action with Playwright, then verifies it actually worked."""
import re

from agent.ledger import resolve_file_ref, resolve_value_ref
from agent.state import Action

# Irreversible buttons. Clicking these is refused in code unless the user approved it.
FINAL_SUBMIT = re.compile(r"final submit|submit application|confirm (and )?submit|make payment|pay now", re.I)
TIMEOUT = 5_000


class ActionBlocked(Exception):
    """The action is not allowed or not possible as specified. Retrying will not help."""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _element(obs: dict, element_id):
    return next((e for e in obs["elements"] if e["id"] == element_id), None)


async def execute(page, action: Action, obs: dict, profile: dict, documents: list,
                  allow_final_submit: bool = False, keyboard: bool = False):
    """Performs the action. Returns the expected value (for verification) or None."""
    if action.type == "wait":
        await page.wait_for_timeout(1500)
        return None
    el = _element(obs, action.element_id)
    if el is None:
        raise ActionBlocked(f"Element {action.element_id} is not on the current page")
    loc = page.locator(f'[data-agent-id="{action.element_id}"]')

    if action.type == "fill":
        value = resolve_value_ref(profile, action.value_ref)
        if keyboard:                      # recovery rung 2: type like a human
            await loc.click(timeout=TIMEOUT)
            await page.keyboard.press("Meta+A")
            await page.keyboard.type(value, delay=30)
        else:
            await loc.fill(value, timeout=TIMEOUT)
        return value

    if action.type == "select":
        value = resolve_value_ref(profile, action.value_ref)
        match = next((o for o in el.get("options", []) if _norm(o) == _norm(value)), None)
        if match is None:
            raise ActionBlocked(f"Element {action.element_id} has no option matching the referenced value")
        await loc.select_option(label=match, timeout=TIMEOUT)
        return match

    if action.type == "check":
        await loc.check(timeout=TIMEOUT)
        return None

    if action.type == "upload":
        await loc.set_input_files(resolve_file_ref(documents, action.value_ref), timeout=TIMEOUT)
        return None

    if action.type == "click":
        if FINAL_SUBMIT.search(el["label"]) and not allow_final_submit:
            raise ActionBlocked("Final submission requires the user's explicit approval")
        await loc.click(timeout=TIMEOUT)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:
            pass
        return None

    raise ActionBlocked(f"Unsupported action type: {action.type}")


async def verify_field(page, action: Action, expected) -> tuple[bool, str]:
    """Reads the field back to confirm the action took effect. Notes never contain values."""
    loc = page.locator(f'[data-agent-id="{action.element_id}"]')
    try:
        if action.type == "fill":
            ok = _norm(await loc.input_value(timeout=3000)) == _norm(expected)
            return ok, "value confirmed in field" if ok else "value did not stick in field"
        if action.type == "select":
            actual = await loc.evaluate(
                "e => e.selectedIndex > 0 ? e.options[e.selectedIndex].text.trim() : ''")
            ok = _norm(actual) == _norm(expected)
            return ok, "option confirmed" if ok else "option did not stick"
        if action.type == "check":
            ok = await loc.is_checked()
            return ok, "checkbox confirmed" if ok else "checkbox not checked"
        if action.type == "upload":
            ok = await loc.evaluate("e => e.files ? e.files.length > 0 : false")
            return ok, "file attached" if ok else "file not attached"
    except Exception:
        return False, "could not read the field back"
    return True, "no field check needed"


def verify_click(before: dict, after: dict) -> tuple[bool, str]:
    """After a click: new errors mean failure; otherwise look for evidence of progress."""
    if after["alerts"] and (after["url"] == before["url"] or after["alerts"] != before["alerts"]):
        return False, "page reported: " + "; ".join(after["alerts"])[:300]
    if after["url"] != before["url"]:
        return True, "moved to a new page"
    if len(after["dialogs"]) < len(before["dialogs"]):
        return True, "dialog dismissed"
    if after["headings"] != before["headings"]:
        return True, "page content changed"
    return True, "clicked; no visible change"
