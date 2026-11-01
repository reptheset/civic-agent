"""Data shapes shared by the agent, the API server and the UI."""
import operator
import time
from typing import Annotated, Literal, Optional, TypedDict
from pydantic import BaseModel, Field


# ---------- Provenance: where every value came from ----------

class Provenance(BaseModel):
    kind: Literal["document", "user"]
    document_id: Optional[str] = None
    document_type: Optional[str] = None
    page: Optional[int] = None
    confidence: float = 1.0


class ProfileField(BaseModel):
    key: str                 # e.g. "dob", "full_name", "family_income"
    value: str
    provenance: Provenance
    confirmed: bool = False  # True once the user has approved this value


class Document(BaseModel):
    id: str
    filename: str
    path: str
    doc_type: str = "unknown"
    extracted: dict[str, str] = Field(default_factory=dict)


class Mismatch(BaseModel):
    field: str
    values: dict[str, str]   # document_id -> value found in that document
    similarity: float
    resolved_value: Optional[str] = None


# ---------- Eligibility ----------

class EligibilityRule(BaseModel):
    field: str
    op: Literal["<=", "<", ">=", ">", "==", "!=", "in", "not_in"]
    value: str               # numbers kept as text; "in" uses comma-separated options
    quote: str               # exact sentence from the official source
    source_url: str
    quote_verified: bool = False


class RuleResult(BaseModel):
    rule: EligibilityRule
    passed: Optional[bool]   # None = could not evaluate (missing data)
    reason: str


# ---------- Browser actions ----------

class Action(BaseModel):
    type: Literal["fill", "select", "click", "check", "upload", "wait", "ask_human", "need_info", "done"]
    element_id: Optional[int] = None
    value_ref: Optional[str] = None   # e.g. "profile.dob" -- never a raw value
    reason: str = ""


class StepLog(BaseModel):
    step: int
    url: str
    action: Action
    ok: bool
    verify_note: str
    recovery_rung: int = 0
    screenshot: Optional[str] = None
    ts: float = Field(default_factory=time.time)


# ---------- Live events streamed to the UI ----------

class AgentEvent(BaseModel):
    run_id: str
    type: Literal["node", "observe", "decide", "act", "verify", "recover",
                  "interrupt", "log", "error", "receipt", "done", "security"]
    message: str
    data: dict = Field(default_factory=dict)
    ts: float = Field(default_factory=time.time)


# ---------- LangGraph run state ----------
# Stored as plain dicts so the checkpointer can save and restore it reliably.

class RunState(TypedDict, total=False):
    run_id: str
    service_request: str
    documents: list[dict]
    profile: dict[str, dict]          # key -> ProfileField as dict
    mismatches: list[dict]
    missing_fields: list[str]
    eligibility: list[dict]           # RuleResult dicts
    eligible: Optional[bool]
    portal_url: str
    step_log: Annotated[list[dict], operator.add]   # appended to, never overwritten
    status: str
    receipt: Optional[dict]
    error: Optional[str]
    phase: str                        # 'fill' or 'submit'
    review_rows: list
    verdict: str
    guideline: dict
    scheme: str


class ActionPlan(BaseModel):
    """All actions for the current page; a click (if any) must be the last one."""
    actions: list[Action]
    reason: str = ""
