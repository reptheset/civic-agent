"""Runs the browser loop against the testbed with a visible browser window."""
import asyncio
import json
import uuid
from pathlib import Path

from playwright.async_api import async_playwright

from agent.browser.loop import run_browser_task
from agent.config import DATA_DIR, TESTBED_URL

PROFILE_FILE = DATA_DIR / "my_profile.json"
FIELDS = [
    ("full_name", "Full name (as on your certificates)"),
    ("father_name", "Father's name"),
    ("dob", "Date of birth (YYYY-MM-DD)"),
    ("gender", "Gender (Male/Female/Transgender)"),
    ("category", "Category (General/OBC/SC/ST/EWS)"),
    ("mobile", "Mobile number (10 digits)"),
    ("institution", "Institution name"),
    ("course", "Course (B.Tech/B.E./B.Sc/B.Com/B.A./M.Tech/Other)"),
    ("current_year", "Current year of study (1-5)"),
    ("last_exam_percentage", "Last exam percentage (e.g. 82.5)"),
    ("family_income", "Annual family income in Rs (digits only)"),
]
DOCS = [
    ("income_certificate", "Path to your income certificate (PDF/JPG)"),
    ("marksheet", "Path to your marksheet (PDF/JPG)"),
]
GOAL = ("Apply for the scholarship on this portal using the applicant's profile and documents. "
        "Log in with the applicant's mobile number, complete every form page, upload the documents, "
        "and stop when the Review page is shown. Never click Final Submit.")


def load_or_ask():
    if PROFILE_FILE.exists():
        saved = json.loads(PROFILE_FILE.read_text())
        return saved["profile"], saved["documents"]
    print("\nEnter YOUR OWN real details. Saved locally in data/ (never committed).\n")
    profile = {}
    for key, question in FIELDS:
        value = input(f"{question}: ").strip()
        profile[key] = {"key": key, "value": value,
                        "provenance": {"kind": "user", "confidence": 1.0}, "confirmed": True}
    documents = []
    for doc_type, question in DOCS:
        raw = input(f"{question}: ").strip().strip("'\"").replace("\\ ", " ")
        p = Path(raw).expanduser()
        if not p.exists():
            print(f"  Warning: {p} does not exist")
        documents.append({"id": doc_type, "filename": p.name, "path": str(p), "doc_type": doc_type})
    PROFILE_FILE.write_text(json.dumps({"profile": profile, "documents": documents}, indent=2))
    return profile, documents


def printer(type_, message, data):
    print(f"[{type_:8}] {message}")
    if type_ == "security" and data.get("flagged"):
        for f in data["flagged"]:
            print(f"           removed: {f[:100]}")


async def main():
    profile, documents = load_or_ask()
    run_id = uuid.uuid4().hex[:8]
    history = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=150)
        page = await browser.new_page()
        start = TESTBED_URL
        while True:
            result = await run_browser_task(page, goal=GOAL, profile=profile, documents=documents,
                                            run_id=run_id, start_url=start, emit=printer, history=history)
            start = None
            print(f"\n=== {result['status'].upper()}: {result['reason']} ===\n")
            if result["status"] == "needs_human":
                input("Do that step in the browser window (OTP is on the admin page), "
                      "then press Enter here to let the agent continue...")
                continue
            break
        print(f"Steps taken: {len(history)}. Screenshots in data/screenshots/{run_id}/")
        input("Press Enter to close the browser...")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
