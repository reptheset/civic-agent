"""The application form's structure. Field rules only -- no applicant data."""

PAGES = {
    1: {"title": "Personal Details", "fields": [
        {"name": "full_name", "label": "Full Name (as per Class 10 certificate)", "type": "text", "required": True},
        {"name": "father_name", "label": "Father's Name", "type": "text", "required": True},
        {"name": "dob", "label": "Date of Birth (DD/MM/YYYY)", "type": "text", "required": True,
         "pattern": r"^\d{2}/\d{2}/\d{4}$", "pattern_msg": "Date of Birth must be in DD/MM/YYYY format"},
        {"name": "gender", "label": "Gender", "type": "select", "required": True,
         "options": ["Male", "Female", "Transgender"]},
        {"name": "category", "label": "Category", "type": "select", "required": True,
         "options": ["General", "OBC", "SC", "ST", "EWS"]},
        {"name": "mobile", "label": "Mobile Number", "type": "text", "required": True,
         "pattern": r"^[6-9]\d{9}$", "pattern_msg": "Enter a valid 10-digit mobile number"},
    ]},
    2: {"title": "Academic & Income Details", "fields": [
        {"name": "institution", "label": "Name of Institution", "type": "text", "required": True},
        {"name": "course", "label": "Course", "type": "select", "required": True,
         "options": ["B.Tech", "B.E.", "B.Sc", "B.Com", "B.A.", "M.Tech", "Other"]},
        {"name": "current_year", "label": "Current Year of Study", "type": "select", "required": True,
         "options": ["1", "2", "3", "4", "5"]},
        {"name": "last_exam_percentage", "label": "Percentage in Last Qualifying Exam", "type": "text",
         "required": True, "pattern": r"^\d{1,3}(\.\d{1,2})?$",
         "pattern_msg": "Enter percentage as a number, e.g. 78.40"},
        {"name": "family_income", "label": "Annual Family Income (in Rs.)", "type": "text", "required": True,
         "pattern": r"^\d+$", "pattern_msg": "Income must be digits only, without commas"},
    ]},
    3: {"title": "Upload Documents", "fields": [
        {"name": "income_certificate", "label": "Income Certificate (PDF/JPG)", "type": "file", "required": True},
        {"name": "marksheet", "label": "Last Exam Marksheet (PDF/JPG)", "type": "file", "required": True},
    ]},
}

# Used when the layout_drift fault is on: the same fields, described differently.
DRIFT_LABELS = {
    "full_name": "Applicant Name",
    "father_name": "Name of Father/Guardian",
    "dob": "D.O.B. (dd/mm/yyyy)",
    "institution": "College / University",
    "last_exam_percentage": "Marks % (previous exam)",
    "family_income": "Gross Annual Household Income (Rs.)",
}


def html_name(field: dict, drift: bool) -> str:
    return f"app_{field['name']}" if drift else field["name"]


def label_for(field: dict, drift: bool) -> str:
    return DRIFT_LABELS.get(field["name"], field["label"]) if drift else field["label"]


def fields_for(n: int, drift: bool) -> list[dict]:
    out = []
    for f in PAGES[n]["fields"]:
        g = dict(f)
        g["html_name"] = html_name(f, drift)
        g["label"] = label_for(f, drift)
        out.append(g)
    return list(reversed(out)) if drift else out
