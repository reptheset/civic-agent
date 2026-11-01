"""Builds data/my_profile.json from your real documents, with confirmation of uncertain values."""
import json
import shutil
from pathlib import Path

from agent.config import DATA_DIR
from agent.documents import build_profile, read_document

DOCS_DIR = DATA_DIR / "my_docs"
DOCS_DIR.mkdir(parents=True, exist_ok=True)
DECLARED = [
    ("gender", "Gender (Male/Female/Transgender)"),
    ("category", "Category (General/OBC/SC/ST/EWS)"),
    ("mobile", "Mobile number (10 digits)"),
    ("institution", "Institution name"),
    ("course", "Course (B.Tech/B.E./B.Sc/B.Com/B.A./M.Tech/Other)"),
    ("current_year", "Current year of study (1-5)"),
    ("study_mode", "Study mode (regular/correspondence/distance)"),
]


def mask(v: str) -> str:
    return " ".join(w[:2] + "*" * max(0, len(w) - 2) for w in str(v).split())


def ask_path(prompt: str):
    while True:
        raw = input(prompt).strip()
        if not raw:
            return None
        p = Path(raw.strip("'\"").replace("\\ ", " ")).expanduser()
        if p.is_file():
            return p
        print(f"  Not found: {p} -- drag it again, or press Enter to stop adding files")


def main():
    print("Drag each REAL document into this window and press Enter. Press Enter on an empty line when done.\n")
    docs = []
    while True:
        src = ask_path(f"Document {len(docs) + 1}: ")
        if src is None:
            break
        print("  reading...")
        d = read_document(str(src))
        dest = DOCS_DIR / f"{d['doc_type']}{src.suffix.lower()}"
        shutil.copy(src, dest)
        d["path"], d["filename"] = str(dest.resolve()), dest.name
        docs.append(d)
        print(f"  type: {d['doc_type']} | text layer: {d['has_text_layer']} | subjects: {len(d['subjects'])}")
        for f in d["fields"]:
            print(f"    {f['key']:20} {mask(f['value']):28} conf {f['confidence']:.2f}  ({f['check']})")

    profile, mismatches = build_profile(docs)
    print(f"\nMismatches across documents: {len(mismatches)}")
    for m in mismatches:
        print(f"  {m['field']}: similarity {m['similarity']}  " +
              ", ".join(f"{k}={mask(v)}" for k, v in m["values"].items()))
        choice = input(f"  Type the correct {m['field']} exactly as it should appear on forms: ").strip()
        if choice:
            profile[m["field"]].update(value=choice, confirmed=True)
            profile[m["field"]]["provenance"].update(kind="user", confidence=1.0)

    print("\nConfirm uncertain values (Enter = correct, or type the corrected value):")
    for key, f in profile.items():
        if not f["confirmed"] and f["provenance"]["confidence"] < 0.85:
            ans = input(f"  {key} = '{f['value']}' ? ").strip()
            if ans:
                f.update(value=ans)
                f["provenance"].update(kind="user", confidence=1.0)
            f["confirmed"] = True

    print("\nDetails not found on documents:")
    for key, question in DECLARED:
        if key in profile and profile[key]["confirmed"]:
            continue
        default = profile.get(key, {}).get("value", "")
        ans = input(f"  {question}{' [' + default + ']' if default else ''}: ").strip() or default
        if ans:
            profile[key] = {"key": key, "value": ans, "confirmed": True,
                            "provenance": {"kind": "user", "confidence": 1.0}}

    documents = [{"id": d["doc_type"], "filename": d["filename"], "path": d["path"], "doc_type": d["doc_type"],
                  "extracted": {f["key"]: f["value"] for f in d["fields"]}} for d in docs]
    (DATA_DIR / "my_profile.json").write_text(json.dumps(
        {"profile": profile, "documents": documents, "mismatches": mismatches}, indent=2))
    print("\nSaved data/my_profile.json")
    print("Sources:", ", ".join(f"{k}={v['provenance']['kind']}"
                                + (f"({v['provenance'].get('document_type')})" if v['provenance'].get('document_type') else "")
                                for k, v in profile.items()))


if __name__ == "__main__":
    main()
