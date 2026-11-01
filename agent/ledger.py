"""The provenance ledger.

The LLM never types values. It asks for a reference like "profile.dob",
and this module returns the real value only if it has a trusted source.
"""
from agent.config import MIN_AUTO_CONFIDENCE
from agent.state import ProfileField


class MissingProvenance(Exception):
    """Raised when a value has no trusted source. The agent must ask the user."""


def resolve_value_ref(profile: dict[str, dict], ref: str) -> str:
    if not ref or not ref.startswith("profile."):
        raise MissingProvenance(f"Invalid value reference: {ref!r}")
    key = ref.split(".", 1)[1]
    raw = profile.get(key)
    if raw is None:
        raise MissingProvenance(f"No value on record for '{key}'")
    field = ProfileField(**raw)
    if not field.confirmed and field.provenance.confidence < MIN_AUTO_CONFIDENCE:
        raise MissingProvenance(
            f"'{key}' was extracted with low confidence "
            f"({field.provenance.confidence:.2f}) and needs user confirmation"
        )
    return field.value


def available_refs(profile: dict[str, dict]) -> list[str]:
    """The list of references shown to the LLM. Keys only, never values."""
    return [f"profile.{k}" for k in sorted(profile)]
