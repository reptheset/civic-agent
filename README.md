# Civic Agent

**An autonomous public-service execution agent that never types a value it can't prove, never claims an action it hasn't verified, and never submits without the citizen's approval.**

Theme 1 (Civic Pulse, Digital Governance & Public Information), Problem Statement 3: Autonomous Public Service & Bureaucracy Execution Agent.

Civic Agent reads a citizen's real documents, checks eligibility against the **live official scheme page**, fills a legacy government-style portal with a browser agent (Playwright + Gemini), survives pop-ups, renamed fields, server errors, expired sessions, slow networks and prompt injection, and returns a **verified receipt**, an **evidence-pack PDF** and the **application status**.

## Live demo

| | Link |
|---|---|
| **App (UI)** | https://civic-agent-mu.vercel.app |
| **Agent API** | https://civic-agent-0spb.onrender.com/docs |

The API runs on Render's free tier: after a period without visitors, the first request can take about a minute while the server wakes up. To try it you need your own documents (e.g. DigiLocker marksheets as PDF). The OTP for the test portal appears in the app's *SMS inbox* panel; you type it yourself.

---

## What makes it different

| # | USP | Evidence |
|---|-----|----------|
| 1 | **Provenance ledger.** The model never outputs values, only references such as `profile.dob\|dd/mm/yyyy`. Code resolves them, and only from a document (checked against the PDF text layer) or a citizen-confirmed value. No source: the agent asks. | Incomplete profile: agent stopped and asked in 8/8 scenarios, never invented a value |
| 2 | **Eligibility with proof.** Rules are extracted live from myScheme, each with an exact official quote that Python verifies word for word; evaluation is deterministic. | 0 invented rules; unknown values are marked *needs review*, never guessed |
| 3 | **Learn once, replay many.** Each portal's verified steps are saved as a versioned skill (labels + references, never values) and replayed without the model; changed pages self-heal. | Model plans per application: 10 then 2; a normal run with a learned skill needs 0 |
| 4 | **Survives chaos.** Observe, plan, act, verify, and a 5-rung recovery ladder. | Benchmark: **8/8 scenarios passed**, including all 6 faults at once |
| 5 | **Can't be tricked into submitting, never submits twice.** Final-submit gate on the live button label, review-page cross-check, safety stop, and a duplicate guard written to disk before the click. | Final Submit clicks per application: 1 |
| 6 | **Crash-proof.** Every LangGraph step is checkpointed in SQLite. | Server killed during approval; run recovered and completed |
| 7 | **Privacy by design.** While browsing, the model sees `[full_name]`, never the value (see the "What the AI saw" panel). | Redacted prompt visible in the UI |
| 8 | **Evidence you can keep, in your language.** Evidence-pack PDF with sources, quotes, hashes and a reliability report; UI in English, Hindi and Odia. | Every receipt comes with a PDF |
| 9 | **Any official scheme, read live.** Paste any official scheme page (`.gov.in` / `.nic.in`): *"What documents do I need?"* lists the required documents and eligibility is checked against that page, each item with an exact quote verified word for word. | NMMSS page: all 7 required documents found, each quote verified |

---

## Pipeline

**Before starting (optional):** paste an official scheme page → *What documents do I need?* → the agent reads the page live and lists the required documents with verified quotes. The same URL is then used for the eligibility check.

```
 1 Read documents ──► 2 Confirm details ⏸ ──► 3 Check eligibility ──► 4 Proceed? ⏸ (add a missing value, re-check)
                                                                              │
 ┌────────────────────────────────────────────────────────────────────────────┘
 ▼
 5 Fill the portal ⇄ OTP / missing value ⏸ ──► 6 Cross-check review page ──► 7 Approve ⏸ ──► 8 Submit
                                                                                              │
                                     10 Track status ◄── 9 Verified receipt + evidence PDF ◄──┘
                                                          + skill learned
 ⏸ = pauses for the citizen (LangGraph interrupt). Every step is checkpointed.
```

**Browser loop (each page):** observe (numbered elements) → guard (strip injection, redact values) → plan (one model call per page, or replay a learned skill) → act (Playwright) → verify (read every field back, check page errors).
**Recovery ladder:** retry after the page settles → type with the keyboard → re-plan with the failure → reload → hand to the human.

## Guardrails (enforced in code, not prompts)

- Provenance ledger: value references only, never values.
- Personal data redacted before the model sees page text.
- Prompt-injection filter; page text treated as untrusted.
- Closed action set and host allow-list.
- Final Submit blocked unless approved, checked on the live button label; stale-page check.
- Duplicate guard: Final Submit at most once per run, recorded on disk before the click.
- OTP, CAPTCHA and passwords are always entered by the citizen.
- Review-page values cross-checked against the verified profile before approval.
- Application ID and status accepted only if they appear on the portal's page.
- Citizen-supplied scheme URLs: only `https` pages on official government domains (`.gov.in`, `.nic.in`) are fetched; anything else is rejected before any request is made.

## Measured results (`python -m scripts.benchmark`)

| Scenario | Result | Values correct | Verified actions | Failed checks | Model plans | Replays | Security | Time (s) |
|---|---|---|---|---|---|---|---|---|
| Baseline | PASS | yes | 20/20 | 0 | 0 | 6 | 0 | 0.9 |
| Blocking pop-up | PASS | yes | 34/36 | 2 | 5 | 6 | 0 | 30.1 |
| Layout drift | PASS | yes | 20/20 | 0 | 2 | 4 | 0 | 4.2 |
| Server validation error | PASS | yes | 21/22 | 1 | 1 | 6 | 0 | 2.0 |
| Prompt injection | PASS | yes | 20/20 | 0 | 0 | 6 | 3 | 0.8 |
| Session expiry | PASS | yes | 29/30 | 1 | 1 | 8 | 0 | 2.4 |
| Slow network | PASS | yes | 15/20 | 5 | 0 | 6 | 0 | 41.3 |
| **All 6 faults at once** | PASS | yes | 31/46 | 15 | 15 | 5 | 4 | 138.3 |

8/8 scenarios reached the Review page with every value correct; nothing was submitted. The benchmark script plays the citizen for the OTP; the agent never enters it.

---

## Architecture

| Layer | Files | Libraries |
|---|---|---|
| Workflow | `agent/graph.py` (11 nodes, pauses, routing) | LangGraph, SQLite checkpoints |
| Browser agent | `agent/browser/observe.py, decide.py, actions.py, loop.py` | Playwright (Chromium) |
| Provenance | `agent/ledger.py` | - |
| Skills | `agent/skills.py` (learn, replay, self-heal, versions) | - |
| Documents | `agent/documents.py` (extraction, text-layer check, consistency) | Gemini, PyMuPDF, RapidFuzz |
| Eligibility | `agent/eligibility.py` (live fetch, quote check, evaluation) | Gemini, Playwright |
| Evidence | `agent/evidence.py` | ReportLab |
| Model access | `agent/llm.py` (timeouts, retries, rate limits) | google-genai |
| API | `agent/server.py` (runs, events, resume, recover, track, explain, scheme documents, SMS inbox, citizen OTP input, fault switches) | FastAPI, WebSocket |
| Test portal | `testbed/` (legacy-style portal, 6 switchable faults, admin page) | FastAPI, Jinja2, SQLite |
| UI | `web/src/app/page.tsx`, `i18n.ts` | Next.js, Tailwind |
| Deployment | `Dockerfile`, `start.sh` (API + test portal + headless Chromium in one container) | Render (API), Vercel (UI) |

Model: `gemini-3.5-flash-lite` (Google AI Studio).

## Run it

Requirements: Python 3.12, Node 20+, a Google AI Studio API key.

```bash
conda create -n civic python=3.12 -y && conda activate civic
pip install -r requirements.txt
playwright install chromium
printf "GEMINI_API_KEY=your_key_here\nGEMINI_MODEL=gemini-3.5-flash-lite\n" > .env
cd web && npm install && cd ..
```

Four terminals (each with `conda activate civic`, from the repo root):

```bash
uvicorn testbed.main:app --port 8001 --reload   # 1. test portal  -> http://localhost:8001 (admin: /admin)
uvicorn agent.server:app --port 8000            # 2. agent API
cd web && npm run dev                           # 3. UI           -> http://localhost:3000
python -m scripts.benchmark                     # 4. benchmark (optional, after one completed run)
```

In the UI: choose a language, optionally paste an official scheme page and click *What documents do I need?*, upload your documents, start the agent, confirm details, decide on eligibility, type the OTP from the *SMS inbox* panel, approve, then download the evidence pack and check the status. Failures can be switched on at any time from the *Test portal: inject failures* card (or `http://localhost:8001/admin`). Locally the agent's Chromium window is visible.

## Deploy

The UI and the backend are deployed separately; the code is the same as the local version, only settings differ.

**Backend (Render, Docker):** New → Web Service → this repo → Language *Docker* (uses the `Dockerfile`; the test portal runs inside the same container, Chromium runs headless). Environment variables:

| Variable | Value |
|---|---|
| `GEMINI_API_KEY` | your Google AI Studio key (secret) |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` |
| `CORS_ORIGIN_REGEX` | `https://.*\.vercel\.app` |

**UI (Vercel):** import this repo, Root Directory `web`, framework Next.js, environment variable `NEXT_PUBLIC_API` = the Render URL (no trailing slash).

Without these variables everything defaults to local development (visible browser, `localhost`).

## Data and honesty

- **Real data only.** Documents are the citizen's own DigiLocker marksheets. Eligibility rules and required documents are fetched live on every run from the official myScheme page (`myscheme.gov.in/schemes/csss-cus` by default, or the official page the citizen pastes), saved with a timestamp and SHA-256.
- **The portal is a test environment.** Applications go to the *CivicTest Scholarship Portal*, built by the team and clearly labelled as not a government website. Real portals require Aadhaar, OTP and CAPTCHA, and submitting test applications to them would be inappropriate. The agent contains no portal-specific code.
- `.env`, `data/` (documents, receipts, profiles) and databases are git-ignored.

## Future work

Filling real government portals for genuine applicants (same agent, the portal added to the allow-list); more services (licence renewal, subsidy claims); DigiLocker integration; a hosted browser with a live view for the citizen; shared portal skills across citizens (labels and references only, never values); scheduled status tracking with consent.

---

Made with ❤️ by Ashu & Aviral
