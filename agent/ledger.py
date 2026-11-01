"""The provenance ledger.

The LLM never types values. It asks for a reference like "profile.dob" (optionally with
a format, "profile.dob|dd/mm/yyyy"), and this module returns the real value only if it
has a trusted source. Formatting is deterministic code, never the LLM.
"""
import re
from datetime import datetime
from pathlib import Path

from agent.config import MIN_AUTO_CONFIDENCE
from agent.state import ProfileField


class MissingProvenance(Exception):
    """No trusted value exists. The user must provide or confirm it."""


class BadReference(Exception):
    """The LLM produced an invalid reference. Fed back to it so it can correct itself."""


def _iso(v: str) -> datetime:
    return datetime.strptime(v.strip(), "%Y-%m-%d")


FORMATS = {
    "dd/mm/yyyy": lambda v: _iso(v).strftime("%d/%m/%Y"),
    "dd-mm-yyyy": lambda v: _iso(v).strftime("%d-%m-%Y"),
    "yyyy-mm-dd": lambda v: _iso(v).strftime("%Y-%m-%d"),
    "digits": lambda v: re.sub(r"\D", "", v),
    "mobile10": lambda v: re.sub(r"\D", "", v)[-10:],
    "upper": str.upper,
    "lower": str.lower,
}


def resolve_value_ref(profile: dict[str, dict], ref: str) -> str:
    if not ref:
        raise BadReference("Action is missing a value_ref")
    base, _, fmt = ref.partition("|")
    base = base.strip()
    if not base.startswith("profile."):
        raise BadReference(f"'{base}' is not a profile reference")
    key = base.split(".", 1)[1]
    raw = profile.get(key)
    if raw is None:
        raise MissingProvenance(f"No value on record for '{key}'")
    field = ProfileField(**raw)
    if not field.confirmed and field.provenance.confidence < MIN_AUTO_CONFIDENCE:
        raise MissingProvenance(
            f"'{key}' was extracted with low confidence "
            f"({field.provenance.confidence:.2f}) and needs user confirmation")
    value = field.value
    if fmt.strip():
        f = FORMATS.get(fmt.strip().lower())
        if f is None:
            raise BadReference(f"Unknown format '{fmt.strip()}'. Allowed: {', '.join(FORMATS)}")
        try:
            value = f(value)
        except ValueError:
            raise BadReference(f"'{key}' cannot be formatted as {fmt.strip()}")
    return value


def resolve_file_ref(documents: list[dict], ref: str) -> str:
    if not ref or not ref.startswith("file."):
        raise BadReference(f"'{ref}' is not a file reference")
    doc_type = ref.split(".", 1)[1].strip()
    for d in documents:
        if d["doc_type"] == doc_type:
            p = Path(d["path"])
            if not p.exists():
                raise MissingProvenance(f"File for '{doc_type}' not found on disk")
            return str(p)
    raise MissingProvenance(f"No document of type '{doc_type}' has been provided")


def available_refs(profile: dict[str, dict]) -> list[str]:
    """References shown to the LLM. Keys only, never values."""
    return [f"profile.{k}" for k in sorted(profile)]


def available_file_refs(documents: list[dict]) -> list[str]:
    return [f"file.{d['doc_type']}" for d in documents]


def value_variants(profile: dict[str, dict]) -> dict[str, str]:
    """Every way a profile value might appear on a page -> its key. Used for redaction."""
    out = {}
    for key, raw in profile.items():
        v = str(raw.get("value", ""))
        candidates = {v}
        for f in FORMATS.values():
            try:
                candidates.add(f(v))
            except Exception:
                pass
        for c in candidates:
            if len(c.strip()) >= 3:
                out[c.strip()] = key
    return out
