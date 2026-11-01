"""Reads the citizen's real documents into a profile where every value has provenance."""
import re
from pathlib import Path
from typing import Literal, Optional

import fitz  # PyMuPDF
from google.genai import types
from pydantic import BaseModel
from rapidfuzz import fuzz

from agent.ledger import FORMATS
from agent.llm import generate_json

DocType = Literal["class10_marksheet", "class10_certificate", "class12_marksheet", "semester_gradesheet",
                  "income_declaration", "income_certificate", "id_card", "other"]

FIELD_KEYS = {
    "full_name": "the student's full name",
    "father_name": "father's name",
    "mother_name": "mother's name",
    "dob": "date of birth, written as YYYY-MM-DD",
    "class10_percentage": "overall percentage, ONLY if printed on a Class 10 document",
    "class12_percentage": "overall percentage, ONLY if printed on a Class 12 document",
    "board": "examination board",
    "year_of_passing": "year the exam was passed",
    "school": "school or examination centre named on the document",
    "family_income": "annual family income in rupees, digits only",
}
TEXT_CHECKED_CONF = 0.95   # value found in the PDF's own text layer
UNCHECKED_CAP = 0.80       # photos / no text layer: always needs user confirmation


class ExtractedField(BaseModel):
    key: str
    value: str
    confidence: float
    evidence: str = ""


class SubjectMark(BaseModel):
    subject: str
    obtained: float
    maximum: float


class Extraction(BaseModel):
    doc_type: DocType
    fields: list[ExtractedField]
    subjects: list[SubjectMark] = []


def _load(path: Path) -> tuple[list, str]:
    """Returns (image parts for Gemini, the document's own text layer if any)."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        doc = fitz.open(path)
        text = "".join(doc[i].get_text() for i in range(doc.page_count))
        parts = [types.Part.from_bytes(data=doc[i].get_pixmap(dpi=150).tobytes("png"), mime_type="image/png")
                 for i in range(min(2, doc.page_count))]
        return parts, text
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".webp": "image/webp", ".heic": "image/heic"}.get(suffix, "image/jpeg")
    return [types.Part.from_bytes(data=path.read_bytes(), mime_type=mime)], ""


def _variants(key: str, value: str) -> set[str]:
    out = {value}
    if key == "dob":
        for f in FORMATS.values():
            try:
                out.add(f(value))
            except Exception:
                pass
    return {re.sub(r"\s+", " ", v).strip().lower() for v in out if v}


def read_document(path: str) -> dict:
    p = Path(path)
    parts, text_layer = _load(p)
    keys = "\n".join(f"- {k}: {v}" for k, v in FIELD_KEYS.items())
    prompt = f"""Identify this Indian document's type and extract its fields.
Use only these keys:
{keys}
Rules: copy values exactly as printed (except dob, which must be YYYY-MM-DD). confidence is 0-1.
evidence is the exact printed text the value came from. Skip keys that are not on the document.
If the document lists subject-wise marks, list each subject with marks obtained and maximum marks.
Never compute totals or percentages yourself."""
    ext = generate_json(parts + [prompt], Extraction)

    has_text = len(text_layer.strip()) > 50
    text_norm = re.sub(r"\s+", " ", text_layer).lower()
    fields = []
    for f in ext.fields:
        if f.key not in FIELD_KEYS or not f.value.strip():
            continue
        if has_text:
            found = any(v in text_norm for v in _variants(f.key, f.value))
            conf, check = (max(f.confidence, TEXT_CHECKED_CONF), "found in text layer") if found \
                else (min(f.confidence, 0.6), "NOT found in text layer")
        else:
            conf, check = min(f.confidence, UNCHECKED_CAP), "image only, needs confirmation"
        fields.append({"key": f.key, "value": f.value.strip(), "confidence": round(conf, 2), "check": check})

    # Percentage is computed here, in code, from the subject marks -- never by the model.
    if ext.subjects and ext.doc_type in ("class10_marksheet", "class12_marksheet"):
        key = "class12_percentage" if ext.doc_type == "class12_marksheet" else "class10_percentage"
        if not any(f["key"] == key for f in fields):
            total_max = sum(s.maximum for s in ext.subjects)
            if total_max > 0:
                pct = round(100 * sum(s.obtained for s in ext.subjects) / total_max, 2)
                fields.append({"key": key, "value": f"{pct:.2f}", "confidence": UNCHECKED_CAP,
                               "check": f"derived in code from {len(ext.subjects)} subjects -- confirm"})
    return {"path": str(p), "filename": p.name, "doc_type": ext.doc_type, "fields": fields,
            "subjects": [s.model_dump() for s in ext.subjects], "has_text_layer": has_text}


NAME_KEYS = {"full_name", "father_name", "mother_name"}
IDENTITY_KEYS = NAME_KEYS | {"dob"}   # only these must match across documents


def _similar(key: str, a: str, b: str) -> float:
    if key in NAME_KEYS:
        return fuzz.token_sort_ratio(a.upper().replace(".", " "), b.upper().replace(".", " "))
    return 100.0 if a.strip().lower() == b.strip().lower() else 0.0


def build_profile(docs: list[dict]) -> tuple[dict, list[dict]]:
    """Merge documents: best-confidence value per key, plus mismatches across documents."""
    candidates: dict[str, list[tuple[dict, dict]]] = {}
    for d in docs:
        for f in d["fields"]:
            candidates.setdefault(f["key"], []).append((f, d))

    profile, mismatches = {}, []
    for key, cands in candidates.items():
        best_f, best_d = max(cands, key=lambda c: c[0]["confidence"])
        profile[key] = {"key": key, "value": best_f["value"], "confirmed": False,
                        "provenance": {"kind": "document", "document_id": best_d["doc_type"],
                                       "document_type": best_d["doc_type"], "confidence": best_f["confidence"]}}
        values = {d["doc_type"]: f["value"] for f, d in cands}
        if key in IDENTITY_KEYS and len(values) > 1:
            vals = list(values.values())
            worst = min(_similar(key, vals[0], v) for v in vals[1:])
            if worst < 92:
                mismatches.append({"field": key, "values": values, "similarity": round(worst, 1)})
                profile[key]["provenance"]["confidence"] = min(best_f["confidence"], 0.5)
    return profile, mismatches
