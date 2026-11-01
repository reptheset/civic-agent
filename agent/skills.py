"""Learn once, replay many.

A skill = for each page of a portal, the verified steps that worked, identified by the
element's LABEL (not its position) plus the value REFERENCE (never the value).
Replay uses it only when every learned label is present on the live page; otherwise the
model plans as usual and the next successful run updates the skill (self-healing).
"""
import json
import re
import time
from urllib.parse import urlparse

from agent.browser.actions import FINAL_SUBMIT
from agent.config import DATA_DIR
from agent.state import Action

SKILL_DIR = DATA_DIR / "skills"
SKILL_DIR.mkdir(parents=True, exist_ok=True)


def _key(url: str) -> str:
    p = urlparse(url)
    return f"{p.hostname}_{p.port or 80}"


def page_path(url: str) -> str:
    return urlparse(url).path or "/"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def load_skill(url: str):
    f = SKILL_DIR / f"{_key(url)}.json"
    return json.loads(f.read_text()) if f.exists() else None


def learn(url: str, history: list):
    """Builds page plans from a successful run's verified steps. Returns the skill if it changed."""
    groups, cur = [], None
    for h in history:
        pp = h.get("page_path")
        if not pp:
            continue
        if cur is None or cur["path"] != pp:
            cur = {"path": pp, "steps": []}
            groups.append(cur)
        cur["steps"].append(h)

    pages, stop = {}, None
    for g in groups:
        steps = g["steps"]
        if any(s["action"]["type"] == "click" and FINAL_SUBMIT.search((s.get("target") or {}).get("label", ""))
               for s in steps):
            stop = g["path"]                      # never learned: final submission stays with the user + model
            continue
        last_fail = max((i for i, s in enumerate(steps) if not s["ok"]), default=-1)
        tail = [s for s in steps[last_fail + 1:] if s["action"]["type"] != "wait"]
        if not tail or tail[-1]["action"]["type"] != "click" or any(not s.get("target") for s in tail):
            continue
        pages[g["path"]] = [{"type": s["action"]["type"], "value_ref": s["action"].get("value_ref"),
                             "target": s["target"]} for s in tail]
    if not pages:
        return None

    old = load_skill(url) or {"version": 0, "pages": {}, "stop_path": None}
    merged = {**old["pages"], **pages}
    new_stop = stop or old.get("stop_path")
    if merged == old["pages"] and new_stop == old.get("stop_path"):
        return None
    skill = {"portal": _key(url), "version": old["version"] + 1, "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
             "pages": merged, "stop_path": new_stop}
    (SKILL_DIR / f"{_key(url)}.json").write_text(json.dumps(skill, indent=2))
    return skill


def match_plan(skill: dict, obs: dict):
    """The learned actions for this page, mapped to today's element ids -- or None if anything differs."""
    steps = (skill or {}).get("pages", {}).get(page_path(obs["url"]))
    if not steps:
        return None
    actions = []
    for s in steps:
        t = s.get("target") or {}
        el = next((e for e in obs["elements"]
                   if e["tag"] == t.get("tag") and _norm(e["label"]) == _norm(t.get("label"))), None)
        if el is None:
            return None
        actions.append(Action(type=s["type"], element_id=el["id"], value_ref=s.get("value_ref"),
                              reason=f"learned step: {t.get('label', '')[:40]}"))
    return actions
