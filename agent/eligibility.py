"""Eligibility from a live official source.

fetch (live, timestamped, hashed) -> extract rules with exact quotes (Gemini)
-> keep only rules whose quote is really in the source (Python) -> evaluate (Python).
"""
import hashlib
import re
import time
from typing import Literal

from pydantic import BaseModel

from agent.config import DATA_DIR
from agent.llm import generate_json
from agent.state import EligibilityRule, RuleResult

GUIDELINE_DIR = DATA_DIR / "guidelines"
GUIDELINE_DIR.mkdir(parents=True, exist_ok=True)

# Pointers to official sources only. All criteria are read live from these pages.
SCHEMES = {
    "csss": {
        "name": "Central Sector Scheme of Scholarship for College and University Students (PM-USP)",
        "url": "https://www.myscheme.gov.in/schemes/csss-cus",
    },
}

# Profile fields a rule may refer to. Anything else becomes "other" (manual check).
RULE_FIELDS = {
    "family_income": "annual family income in rupees",
    "class12_percentage": "percentage of marks in Class 12",
    "class12_percentile": "percentile rank in the Class 12 board results",
    "course_level": "UG or PG",
    "study_mode": "regular, correspondence or distance",
    "category": "General, OBC, SC, ST or EWS",
    "other": "any condition that does not fit the fields above",
}


class ExtractedRule(BaseModel):
    field: str
    op: Literal["<=", "<", ">=", ">", "==", "!=", "in"]
    value: str
    quote: str


class RuleSet(BaseModel):
    rules: list[ExtractedRule]


def _norm(s: str) -> str:
    """Lowercase, letters and digits only -- so quote matching ignores punctuation and spacing."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


async def fetch_guideline(browser, url: str) -> dict:
    ctx = await browser.new_context()
    page = await ctx.new_page()
    try:
        await page.goto(url, wait_until="networkidle", timeout=45_000)
        text = await page.inner_text("body")
    finally:
        await ctx.close()
    digest = hashlib.sha256(text.encode()).hexdigest()
    fetched_at = time.strftime("%Y-%m-%d %H:%M:%S")
    (GUIDELINE_DIR / f"{digest[:16]}.txt").write_text(f"URL: {url}\nFETCHED: {fetched_at}\n\n{text}")
    return {"url": url, "text": text, "fetched_at": fetched_at, "sha256": digest}


def extract_rules(source: dict) -> tuple[list[EligibilityRule], list[ExtractedRule]]:
    """Returns (verified rules, dropped rules whose quote was not found in the source)."""
    fields = "\n".join(f"- {k}: {v}" for k, v in RULE_FIELDS.items())
    prompt = f"""From the official scheme page text below, extract every ELIGIBILITY condition as a rule.

Allowed fields:
{fields}

Instructions:
- Amounts in plain rupee digits (e.g. "Rs 4.5 lakh" -> 450000). Percent/percentile as a plain number.
- For op "in", give comma-separated options.
- quote must be copied EXACTLY, word for word, from the text (one sentence or bullet).
- Only include conditions that are actually stated in the text. Do not add any from general knowledge.

OFFICIAL PAGE TEXT:
<<<
{source["text"][:12000]}
>>>"""
    extracted = generate_json(prompt, RuleSet).rules
    source_norm = _norm(source["text"])
    verified, dropped = [], []
    for r in extracted:
        if r.quote and _norm(r.quote) and _norm(r.quote) in source_norm:
            verified.append(EligibilityRule(field=r.field, op=r.op, value=r.value, quote=r.quote,
                                            source_url=source["url"], quote_verified=True))
        else:
            dropped.append(r)
    return verified, dropped


def _num(s: str):
    m = re.search(r"-?\d+(\.\d+)?", str(s).replace(",", ""))
    return float(m.group()) if m else None


def evaluate(rules: list[EligibilityRule], values: dict[str, str]) -> tuple[str, list[RuleResult]]:
    """Deterministic. values: field -> the applicant's verified value."""
    results = []
    for r in rules:
        if r.field not in RULE_FIELDS or r.field == "other":
            results.append(RuleResult(rule=r, passed=None, reason="Needs a manual check (not mapped to applicant data)"))
            continue
        v = values.get(r.field)
        if v in (None, ""):
            results.append(RuleResult(rule=r, passed=None, reason=f"No verified value for {r.field}"))
            continue
        if r.op in ("<=", "<", ">=", ">"):
            a, b = _num(v), _num(r.value)
            if a is None or b is None:
                results.append(RuleResult(rule=r, passed=None, reason="Could not compare as numbers"))
                continue
            passed = {"<=": a <= b, "<": a < b, ">=": a >= b, ">": a > b}[r.op]
        elif r.op in ("==", "!="):
            same = _norm(v) == _norm(r.value)
            passed = same if r.op == "==" else not same
        else:
            passed = _norm(v) in [_norm(x) for x in r.value.split(",")]
        results.append(RuleResult(rule=r, passed=passed,
                                  reason=f"{r.field} {r.op} {r.value}: {'met' if passed else 'not met'}"))
    if any(x.passed is False for x in results):
        verdict = "not_eligible"
    elif any(x.passed is None for x in results) or not results:
        verdict = "needs_review"
    else:
        verdict = "eligible"
    return verdict, results
