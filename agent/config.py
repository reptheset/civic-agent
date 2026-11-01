"""Central configuration. Every other module reads settings from here."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
LLM_TIMEOUT_MS = 30_000

DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
RECEIPT_DIR = DATA_DIR / "receipts"
SCREENSHOT_DIR = DATA_DIR / "screenshots"
CHECKPOINT_DB = DATA_DIR / "checkpoints.sqlite"
for d in (DATA_DIR, UPLOAD_DIR, RECEIPT_DIR, SCREENSHOT_DIR):
    d.mkdir(parents=True, exist_ok=True)

TESTBED_URL = os.getenv("TESTBED_URL", "http://localhost:8001")

# Deployment settings. Locally nothing needs to be set: visible browser, UI on localhost:3000.
HEADLESS = os.getenv("HEADLESS", "0") == "1"
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
CORS_ORIGIN_REGEX = os.getenv("CORS_ORIGIN_REGEX") or None     # e.g. https://.*\.vercel\.app

# The browser agent may only visit these hosts. Enforced in code, not in the prompt.
ALLOWED_HOSTS = {
    "localhost", "127.0.0.1",
    "scholarships.gov.in", "myscheme.gov.in", "www.myscheme.gov.in",
}

# A value extracted from a document below this confidence must be confirmed by the user.
MIN_AUTO_CONFIDENCE = 0.85
