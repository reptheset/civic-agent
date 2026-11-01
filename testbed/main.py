"""CivicTest Scholarship Portal: a live test environment that behaves like a legacy portal."""
import asyncio
import re
import time

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from testbed import db
from testbed.forms import PAGES, fields_for, html_name, label_for
from testbed.templates import env

db.init()
app = FastAPI(title="CivicTest Scholarship Portal")
UPLOADS = db.DATA / "testbed_uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)
SESSION_TTL = 15 * 60


def render(name: str, status: int = 200, **ctx) -> HTMLResponse:
    return HTMLResponse(env.get_template(name).render(**ctx), status_code=status)


def go(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def current_session(request: Request):
    sid = request.cookies.get("sid")
    s = db.get_session(sid) if sid else None
    if not s or not s["verified"] or time.time() - s["created"] > SESSION_TTL:
        return None
    return s


@app.middleware("http")
async def slow_network(request: Request, call_next):
    if not request.url.path.startswith("/admin") and db.fault_on("slow_network"):
        await asyncio.sleep(3)
    return await call_next(request)


# ---------- Home & login ----------

@app.get("/")
def home():
    return render("home", title="Home")


@app.get("/login")
def login_page(request: Request):
    return render("login", title="Login", expired=request.query_params.get("expired"), errors=[])


@app.post("/login")
async def login(request: Request):
    form = await request.form()
    mobile = (form.get("mobile") or "").strip()
    if not re.match(r"^[6-9]\d{9}$", mobile):
        return render("login", title="Login", expired=None, errors=["Enter a valid 10-digit mobile number"])
    sid = db.create_session(mobile)
    resp = go("/otp")
    resp.set_cookie("sid", sid, httponly=True)
    return resp


@app.get("/otp")
def otp_page():
    return render("otp", title="Verify OTP", errors=[])


@app.post("/otp")
async def otp(request: Request):
    form = await request.form()
    sid = request.cookies.get("sid")
    if not sid or not db.verify_session(sid, form.get("otp") or ""):
        return render("otp", title="Verify OTP", errors=["Invalid or expired OTP"])
    s = db.get_session(sid)
    _, step = db.get_draft(s["mobile"])
    return go("/review" if step > 3 else f"/apply/{step}")


# ---------- Application form ----------

@app.get("/apply/{n}")
def apply_page(n: int, request: Request):
    s = current_session(request)
    if not s:
        return go("/login?expired=1")
    if n not in PAGES:
        return go("/apply/1")
    data, step = db.get_draft(s["mobile"])
    if n > step:
        return go(f"/apply/{step}")
    return _render_form(n, data, [])


def _render_form(n: int, values: dict, errors: list, status: int = 200):
    drift = db.fault_on("layout_drift")
    return render("form", status=status, title=PAGES[n]["title"], n=n, page_title=PAGES[n]["title"],
                  fields=fields_for(n, drift), values=values, errors=errors,
                  popup=db.fault_on("popup"), injection=db.fault_on("injection"))


@app.post("/apply/{n}")
async def apply_submit(n: int, request: Request):
    s = current_session(request)
    if not s:
        return go("/login?expired=1")
    if db.fault_on("session_expiry"):
        db.set_fault("session_expiry", False)
        db.delete_session(s["id"])
        return go("/login?expired=1")
    if n not in PAGES:
        return go("/apply/1")

    drift = db.fault_on("layout_drift")
    form = await request.form()
    data, step = db.get_draft(s["mobile"])
    new, errors = {}, []

    for f in PAGES[n]["fields"]:
        label = label_for(f, drift)
        raw = form.get(html_name(f, drift))
        if raw is None:
            raw = form.get(html_name(f, not drift))
        if f["type"] == "file":
            if raw is not None and getattr(raw, "filename", ""):
                content = await raw.read()
                if len(content) > 5_000_000:
                    errors.append(f"{label}: file must be under 5 MB")
                    continue
                safe = re.sub(r"[^A-Za-z0-9._-]", "_", raw.filename)
                (UPLOADS / f"{s['mobile']}_{f['name']}_{safe}").write_bytes(content)
                new[f["name"]] = safe
            elif f["required"] and not data.get(f["name"]):
                errors.append(f"{label} is required")
            continue
        val = (raw or "").strip()
        if not val:
            if f["required"]:
                errors.append(f"{label} is required")
        elif f.get("options") and val not in f["options"]:
            errors.append(f"{label}: invalid selection")
        elif f.get("pattern") and not re.match(f["pattern"], val):
            errors.append(f["pattern_msg"])
        else:
            new[f["name"]] = val

    merged = {**data, **new}
    if not errors and n == 2 and db.fault_on("validation_error"):
        db.set_fault("validation_error", False)
        merged.pop("course", None)
        errors.append("Data could not be saved due to a server error. Please re-select Course and submit again.")

    if errors:
        # Like many legacy portals: valid entries are kept, invalid ones are cleared.
        db.save_draft(s["mobile"], merged, step)
        return _render_form(n, merged, errors, status=422)

    db.save_draft(s["mobile"], merged, max(step, n + 1))
    return go(f"/apply/{n + 1}" if n < 3 else "/review")


# ---------- Review & submit ----------

def _review_rows(data: dict):
    rows = []
    for n in sorted(PAGES):
        for f in PAGES[n]["fields"]:
            rows.append((f["label"], data.get(f["name"], "")))
    return rows


@app.get("/review")
def review(request: Request):
    s = current_session(request)
    if not s:
        return go("/login?expired=1")
    data, step = db.get_draft(s["mobile"])
    if step <= 3:
        return go(f"/apply/{step}")
    return render("review", title="Review", rows=_review_rows(data), errors=[])


@app.post("/submit")
async def submit(request: Request):
    s = current_session(request)
    if not s:
        return go("/login?expired=1")
    data, step = db.get_draft(s["mobile"])
    if step <= 3:
        return go(f"/apply/{step}")
    form = await request.form()
    if form.get("declaration") != "yes":
        return render("review", status=422, title="Review", rows=_review_rows(data),
                      errors=["Please accept the declaration before submitting"])
    app_id = db.create_application(s["mobile"], data)
    db.delete_draft(s["mobile"])
    return go(f"/ack/{app_id}")


@app.get("/ack/{app_id}")
def ack(app_id: str):
    a = db.get_application(app_id)
    if not a:
        return go("/track")
    return render("ack", title="Acknowledgement", app=a,
                  submitted=time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(a["created"])))


# ---------- Tracking ----------

@app.get("/track")
def track_page():
    return render("track", title="Track Application", app=None, errors=[])


@app.post("/track")
async def track(request: Request):
    form = await request.form()
    a = db.get_application(form.get("app_id") or "")
    if not a or a["mobile"] != (form.get("mobile") or "").strip():
        return render("track", title="Track Application", app=None,
                      errors=["No application found for this ID and mobile number"])
    return render("track", title="Track Application", app=a, errors=[])


# ---------- Admin ----------

@app.get("/admin")
def admin():
    return render("admin", title="Admin", faults=db.all_faults(),
                  outbox=db.latest_outbox(), apps=db.latest_applications())


@app.post("/admin/fault/{name}")
def toggle_fault(name: str):
    if name in db.FAULTS:
        db.set_fault(name, not db.fault_on(name))
    return go("/admin")
