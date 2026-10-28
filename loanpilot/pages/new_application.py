"""Guided synthetic personal-loan application intake."""

from datetime import date, datetime
from io import BytesIO
import json
from pathlib import Path
import random
import re
import uuid

import streamlit as st
from fpdf import FPDF

from loanpilot import config
from loanpilot.agent.policy_engine import pricing_rate
from loanpilot.components import fmt_inr
from loanpilot.data.queries import create_intake_application, get_application
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore
from loanpilot.theme import render_disclaimer, render_header

_STEPS = ("Applicant", "Employment and income", "Loan request", "Documents")
_PURPOSES = ("Home improvement", "Medical expenses", "Education", "Travel", "Other")
_EMPLOYMENT_TYPES = ("Salaried", "Self-employed", "Other")
_DOC_TYPES = ("payslip", "bank_statement_summary", "kyc_sheet")
_DOC_LABELS = {
    "payslip": "Payslip",
    "bank_statement_summary": "6-month bank statement summary",
    "kyc_sheet": "KYC sheet",
}
_PROBLEMS = (
    "Salary credits about 30% below the payslip",
    "Payslip arithmetic does not add up",
    "Employer name differs",
)


def estimate_bureau_score(
    income: float,
    existing_emi: float,
    job_months: int,
    experience_months: int,
    pan: str,
) -> int | None:
    """Create a stable synthetic score influenced by capacity and tenure."""
    if experience_months < 12:
        return None
    ratio = existing_emi / income if income > 0 else 1.0
    seed = f"{pan}|{income:.2f}|{existing_emi:.2f}|{job_months}|{experience_months}"
    adjustment = random.Random(seed).randint(-8, 8)
    score = 635 + (income / 1000 - 30) * 1.1 + min(job_months, 60) * 0.65
    score -= min(ratio, 1.5) * 110
    return max(300, min(850, round(score + adjustment)))


def _initial_intake() -> dict:
    """Return one canonical intake object independent of transient widgets."""
    return {
        "name": "",
        "dob": date(1990, 1, 1).isoformat(),
        "city": "",
        "pan": f"DEMO{uuid.uuid4().hex[:8].upper()}",
        "mobile": "",
        "employer": "",
        "employment_type": "Salaried",
        "job_months": 12,
        "experience_months": 12,
        "income": 50000.0,
        "existing_emi": 0.0,
        "amount": 200000.0,
        "tenure": 36,
        "purpose": "Other",
        "document_mode": "Generate synthetic documents from my entries",
        "document_problem": False,
        "problem_type": _PROBLEMS[0],
        "uploads": {},
        "consent": False,
        "declaration": False,
        "permanent": False,
    }


def _intake() -> dict:
    """Get or initialize the single source of form state."""
    if "intake" not in st.session_state:
        st.session_state["intake"] = _initial_intake()
    return st.session_state["intake"]


def _widget_values(step: int) -> dict:
    """Read only the currently rendered step's widgets."""
    keys_by_step = {
        0: ("name", "dob", "city", "mobile"),
        1: (
            "employer",
            "employment_type",
            "job_months",
            "experience_months",
            "income",
            "existing_emi",
        ),
        2: ("amount", "tenure", "purpose"),
    }
    if step in keys_by_step:
        values = {
            key: st.session_state[f"intake_widget_{key}"]
            for key in keys_by_step[step]
        }
        if step == 0:
            values["dob"] = values["dob"].isoformat()
        return values
    values = {
        "document_mode": st.session_state["intake_widget_document_mode"],
        "consent": st.session_state["intake_widget_consent"],
        "declaration": st.session_state["intake_widget_declaration"],
        "permanent": st.session_state["intake_widget_permanent"],
        "document_problem": st.session_state["intake_widget_document_problem"],
        "problem_type": st.session_state["intake_widget_problem_type"],
    }
    uploads = {}
    if values["document_mode"] == "Upload my own PDFs":
        for doc_type in _DOC_TYPES:
            uploads[doc_type] = st.session_state.get(f"intake_upload_{doc_type}")
    values["uploads"] = uploads
    return values


def _step_data(step: int) -> dict:
    """Overlay current widget values on the saved intake for validation."""
    return {**_intake(), **_widget_values(step)}


def _validate(data: dict, step: int) -> str:
    """Return a short error when the active step is incomplete or invalid."""
    if step == 0:
        if not data["name"].strip() or not data["city"].strip():
            return "Name and city are required."
        dob = date.fromisoformat(str(data["dob"]))
        today = date.today()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        if not 18 <= age <= 75:
            return "Applicant age must be between 18 and 75."
        if not re.fullmatch(r"\d{10}", str(data["mobile"]).strip()):
            return "Enter a 10-digit mobile number."
    elif step == 1:
        if not data["employer"].strip():
            return "Employer is required."
        if not data["employment_type"]:
            return "Select an employment type."
        if int(data["job_months"]) < 0 or int(data["experience_months"]) < 0:
            return "Experience values cannot be negative."
        if int(data["job_months"]) > int(data["experience_months"]):
            return "Current-job months cannot exceed total experience."
        if float(data["income"]) <= 0 or float(data["existing_emi"]) < 0:
            return "Income must be above zero; EMIs cannot be negative."
    elif step == 2:
        if float(data["amount"]) <= 0:
            return "Loan amount must be above zero."
        if not 12 <= int(data["tenure"]) <= 60:
            return "Tenure must be between 12 and 60 months."
        if data["purpose"] not in _PURPOSES:
            return "Select a loan purpose."
    elif step == 3:
        if data["document_mode"] == "Upload my own PDFs" and any(
            data["uploads"].get(doc_type) is None for doc_type in _DOC_TYPES
        ):
            return "Upload a PDF for each required document."
        if not data["consent"] or not data["declaration"]:
            return "Both consent and declaration are required."
    return ""


def _step_transition(step: int, direction: int) -> None:
    """Save the current step values before moving to another step."""
    current = _intake()
    values = _widget_values(step)
    updated = {**current, **values}
    error = _validate(updated, step) if direction > 0 else ""
    st.session_state["intake"] = updated
    st.session_state["intake_error"] = error
    if not error:
        st.session_state["intake_step"] = min(3, max(0, step + direction))


def _pdf_bytes(title: str, lines: list[str]) -> bytes:
    """Create a one-page, watermarked synthetic PDF in memory."""
    pdf = FPDF()
    pdf.set_title(title)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(25, 65, 62)
    pdf.cell(0, 9, "Aarambh Bank | Synthetic sample document", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(15, 118, 110)
    pdf.line(10, 20, pdf.w - 10, 20)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(210, 220, 218)
    with pdf.rotation(45, x=pdf.w / 2, y=pdf.h / 2):
        pdf.text(x=22, y=pdf.h / 2, text="SYNTHETIC SAMPLE, DEMO ONLY")
    pdf.set_text_color(30, 40, 40)
    pdf.set_font("Helvetica", size=11)
    pdf.set_xy(10, 35)
    for line in lines:
        pdf.multi_cell(
            190,
            7,
            text=line.encode("latin-1", "replace").decode("latin-1"),
        )
    return bytes(pdf.output())


def _document_texts(data: dict) -> dict[str, str]:
    """Build consistent synthetic document text, with an optional chosen mismatch."""
    income = float(data["income"])
    deductions = round(income * 0.18, 2)
    gross = income + deductions
    salary_average = income
    employer = str(data["employer"]).strip()
    issue = data["problem_type"] if data["document_problem"] else ""
    if issue == _PROBLEMS[0]:
        salary_average = round(income * 0.70, 2)
    elif issue == _PROBLEMS[1]:
        gross += 5000
    elif issue == _PROBLEMS[2]:
        employer = f"{employer} Demo Services"
    money = lambda value: f"Rs {value:,.2f}"
    common = [
        f"Applicant: {data['name']}",
        f"City: {data['city']}",
        "Document classification: SYNTHETIC SAMPLE, DEMO ONLY",
    ]
    return {
        "payslip": "\n".join(
            [
                "PERSONAL LOAN DEMO - PAYSLIP",
                *common,
                f"Employer on payslip: {employer}",
                "Pay month: September 2026",
                f"Gross pay: {money(gross)}",
                f"Deductions: {money(deductions)}",
                f"Net pay: {money(income)}",
            ]
        ),
        "bank_statement_summary": "\n".join(
            [
                "PERSONAL LOAN DEMO - BANK STATEMENT SUMMARY",
                *common,
                "Period: April 2026 to September 2026",
                f"Average monthly salary credits: {money(salary_average)}",
            ]
        ),
        "kyc_sheet": "\n".join(
            [
                "PERSONAL LOAN DEMO - KYC SUMMARY",
                *common,
                f"Employer: {data['employer']}",
                f"PAN demo identifier: {data['pan']}",
                "PAN status: Pending synthetic check",
            ]
        ),
    }


def _extract_pdf_text(content: bytes) -> tuple[str, str | None]:
    """Extract PDF text and return a visible flag instead of raising."""
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError, PdfStreamError
    except ImportError:
        return "", "PDF text extraction is unavailable (pypdf is not installed)."
    try:
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages).strip()
    except (OSError, ValueError, TypeError, PdfReadError, PdfStreamError) as error:
        return "", f"PDF could not be read: {type(error).__name__}"
    return (text, None) if text else ("", "PDF contains no extractable text.")


def _save_documents(application_id: str, data: dict) -> list[dict[str, str]]:
    """Generate or register uploaded PDFs beneath the configured project root."""
    folder = config.DOCUMENTS_DIR / application_id
    folder.mkdir(parents=True, exist_ok=True)
    texts = _document_texts(data)
    documents = []
    for doc_type in _DOC_TYPES:
        filename = f"{doc_type}.pdf"
        if data["document_mode"] == "Upload my own PDFs":
            uploaded = data["uploads"].get(doc_type)
            content = uploaded.getvalue() if uploaded is not None else b""
            filename = Path(uploaded.name.replace("\\", "/")).name if uploaded else filename
            text, flag = _extract_pdf_text(content)
            if flag:
                text = f"[DOCUMENT FLAG: {flag}]"
        else:
            text = texts[doc_type]
            title = _DOC_LABELS[doc_type]
            lines = text.splitlines()
            content = _pdf_bytes(title, lines)
            target = folder / filename
            target.write_bytes(content)
        if data["document_mode"] == "Upload my own PDFs":
            (folder / f"{doc_type}.pdf").write_bytes(content)
        documents.append(
            {
                "doc_type": doc_type,
                "file_name": filename,
                "file_path": (folder / f"{doc_type}.pdf").relative_to(config.PROJECT_ROOT).as_posix(),
                "text_content": text,
            }
        )
    return documents


def _next_custom_application_id() -> str:
    """Choose the next stable identifier for a permanent synthetic case."""
    path = config.CUSTOM_CASES_PATH
    entries = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    return f"APP-CUSTOM-{len(entries) + 1}"


def _permanent_case_entry(data: dict, application_id: str) -> None:
    """Persist only canonical case inputs and selected generated-document options."""
    path = config.CUSTOM_CASES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    saved = {
        key: value
        for key, value in data.items()
        if key not in {"uploads", "consent", "declaration", "permanent"}
    }
    saved["document_mode"] = "Generate synthetic documents from my entries"
    entries.append({"application_id": application_id, "inputs": saved})
    path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _run_assessment(application_id: str) -> None:
    """Open AI Assessment with the submitted application selected."""
    from loanpilot.navigation import OPERATE_PAGES

    st.session_state["selected_application"] = application_id
    st.session_state["assessment_application_selector"] = application_id
    st.switch_page(OPERATE_PAGES["ai_assessment"])


def _add_another() -> None:
    """Clear the completed intake and return to step one."""
    st.session_state["intake"] = _initial_intake()
    st.session_state["intake_step"] = 0
    st.session_state.pop("intake_application_id", None)
    st.session_state.pop("intake_error", None)


def _submit_application(store: SQLiteStore) -> None:
    """Validate canonical state, persist the case and show post-submit actions."""
    data = _intake()
    data.update(_widget_values(3))
    error = _validate(data, 3)
    if error:
        st.session_state["intake"] = data
        st.session_state["intake_error"] = error
        return
    dob = date.fromisoformat(data["dob"])
    today = date.today()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    score = estimate_bureau_score(
        float(data["income"]),
        float(data["existing_emi"]),
        int(data["job_months"]),
        int(data["experience_months"]),
        str(data["pan"]),
    )
    application_id = (
        _next_custom_application_id()
        if data["permanent"]
        else f"APP-NEW-{uuid.uuid4().hex[:12].upper()}"
    )
    try:
        documents = _save_documents(application_id, data)
    except (OSError, ValueError) as error:
        st.session_state["intake_error"] = str(error)
        return
    flags = [
        f"{document['doc_type']}: unreadable"
        for document in documents
        if document["text_content"].startswith("[DOCUMENT FLAG:")
    ]
    bureau = {
        "provider": "Synthetic bureau simulator",
        "score": score,
        "thin_file": int(data["experience_months"]) < 12,
        "active_accounts": 0,
        "enquiries_6m": 0 if int(data["experience_months"]) < 12 else 1,
        "max_dpd_24m": 0,
        "written_off": False,
        "utilization_pct": 0.0,
        "document_flags": flags,
    }
    kyc = {
        "provider": "Synthetic KYC simulator",
        "pan_status": "pending",
        "name_match_score": 1.0,
        "pan_demo_id": data["pan"],
        "cersai": "not applicable (unsecured)",
    }
    applicant = {
        "name": data["name"].strip(),
        "dob": dob.isoformat(),
        "age": age,
        "city": data["city"].strip(),
        "mobile": data["mobile"].strip(),
        "employer": data["employer"].strip(),
        "employment_type": data["employment_type"],
        "current_tenure_months": int(data["job_months"]),
        "total_experience_months": int(data["experience_months"]),
        "net_monthly_income": float(data["income"]),
        "existing_emi": float(data["existing_emi"]),
        "pan_demo_id": data["pan"],
    }
    application = {
        "requested_amount": float(data["amount"]),
        "tenure_months": int(data["tenure"]),
        "purpose": data["purpose"],
        "submitted_at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        application_id = create_intake_application(
            applicant, application, bureau, kyc, documents, store,
            application_id=application_id,
        )
        if data["permanent"]:
            _permanent_case_entry(data, application_id)
    except (OSError, ValueError) as error:
        st.session_state["intake_error"] = str(error)
        return
    st.session_state["intake_application_id"] = application_id
    st.session_state["selected_application"] = application_id


def _render_stepper(step: int) -> None:
    """Render the four-step progress labels."""
    st.progress((step + 1) / len(_STEPS), text=f"Step {step + 1} of 4 · {_STEPS[step]}")
    st.caption("Applicant  →  Employment and income  →  Loan request  →  Documents")


def _render_applicant(data: dict) -> None:
    """Render required identity details and a read-only demo PAN."""
    st.text_input("Full name *", value=data["name"], key="intake_widget_name")
    left, right = st.columns(2)
    left.date_input(
        "Date of birth *",
        value=date.fromisoformat(data["dob"]),
        min_value=date(1900, 1, 1),
        max_value=date.today(),
        key="intake_widget_dob",
    )
    right.text_input("City *", value=data["city"], key="intake_widget_city")
    left.text_input("Fake PAN ID · demo only", value=data["pan"], disabled=True, key="intake_pan_display")
    right.text_input("Mobile number *", value=data["mobile"], max_chars=10, key="intake_widget_mobile")


def _render_employment(data: dict) -> None:
    """Render employment and income fields."""
    st.text_input("Employer *", value=data["employer"], key="intake_widget_employer")
    left, right = st.columns(2)
    left.selectbox(
        "Employment type *", _EMPLOYMENT_TYPES,
        index=_EMPLOYMENT_TYPES.index(data["employment_type"]),
        key="intake_widget_employment_type",
    )
    right.number_input(
        "Months in current job *", min_value=0, max_value=600,
        value=int(data["job_months"]), key="intake_widget_job_months",
    )
    left.number_input(
        "Total experience (months) *", min_value=0, max_value=600,
        value=int(data["experience_months"]), key="intake_widget_experience_months",
    )
    right.number_input(
        "Net monthly income (Rs) *", min_value=1.0,
        value=float(data["income"]), step=1000.0, key="intake_widget_income",
    )
    st.number_input(
        "Existing monthly EMIs (Rs) *", min_value=0.0,
        value=float(data["existing_emi"]), step=1000.0, key="intake_widget_existing_emi",
    )


def _render_loan(data: dict) -> None:
    """Render loan request fields and live indicative EMI."""
    left, right = st.columns(2)
    left.number_input(
        "Requested amount (Rs) *", min_value=1000.0,
        value=float(data["amount"]), step=5000.0, key="intake_widget_amount",
    )
    right.slider(
        "Tenure (months) *", 12, 60, int(data["tenure"]), key="intake_widget_tenure",
    )
    st.selectbox(
        "Purpose *", _PURPOSES, index=_PURPOSES.index(data["purpose"]),
        key="intake_widget_purpose",
    )
    income = float(data["income"])
    score = estimate_bureau_score(
        income,
        float(data["existing_emi"]),
        int(data["job_months"]),
        int(data["experience_months"]),
        str(data["pan"]),
    )
    rate = pricing_rate(score)
    if rate is None:
        st.info("Indicative EMI: no grid rate yet.")
    else:
        amount = float(st.session_state["intake_widget_amount"])
        tenure = int(st.session_state["intake_widget_tenure"])
        monthly = rate / 12
        factor = (1 + monthly) ** tenure
        emi = amount * monthly * factor / (factor - 1)
        st.metric("Indicative EMI", fmt_inr(emi), help=f"Illustrative grid rate: {rate:.2%} p.a.")


def _render_document_step(data: dict) -> None:
    """Render generated/uploaded documents, full summary and declarations."""
    st.radio(
        "Document option",
        ("Generate synthetic documents from my entries", "Upload my own PDFs"),
        index=0 if data["document_mode"].startswith("Generate") else 1,
        key="intake_widget_document_mode",
    )
    mode = st.session_state["intake_widget_document_mode"]
    if mode.startswith("Generate"):
        st.checkbox(
            "Add a document problem for the demo",
            value=bool(data["document_problem"]),
            key="intake_widget_document_problem",
        )
        if st.session_state["intake_widget_document_problem"]:
            options = st.selectbox(
                "Choose document problem",
                _PROBLEMS,
                index=_PROBLEMS.index(data["problem_type"]),
                key="intake_widget_problem_type",
            )
        else:
            options = data["problem_type"]
            st.session_state["intake_widget_problem_type"] = options
        st.caption("The three PDFs are watermarked SYNTHETIC SAMPLE, DEMO ONLY.")
    else:
        st.session_state.setdefault("intake_widget_document_problem", False)
        st.session_state.setdefault("intake_widget_problem_type", _PROBLEMS[0])
        for doc_type in _DOC_TYPES:
            st.file_uploader(
                f"{_DOC_LABELS[doc_type]} PDF *",
                type=["pdf"],
                key=f"intake_upload_{doc_type}",
            )
        st.caption("Unreadable PDFs are registered with a document flag.")

    summary = [
        ("Applicant", data["name"]),
        ("Date of birth", date.fromisoformat(data["dob"]).strftime("%d %b %Y")),
        ("City", data["city"]),
        ("Fake PAN ID", data["pan"]),
        ("Mobile", data["mobile"]),
        ("Employer", data["employer"]),
        ("Employment type", data["employment_type"]),
        ("Months in current job", str(data["job_months"])),
        ("Total experience", str(data["experience_months"])),
        ("Net monthly income", fmt_inr(data["income"])),
        ("Existing EMIs", fmt_inr(data["existing_emi"])),
        ("Loan amount", fmt_inr(data["amount"])),
        ("Tenure", f"{data['tenure']} months"),
        ("Purpose", data["purpose"]),
    ]
    st.subheader("Review your entries")
    st.table([{"Item": label, "Your entry": value} for label, value in summary])
    st.checkbox(
        "I consent to this synthetic demo application being processed. *",
        value=bool(data["consent"]), key="intake_widget_consent",
    )
    st.checkbox(
        "I confirm these are fictional demonstration details. *",
        value=bool(data["declaration"]), key="intake_widget_declaration",
    )
    st.checkbox(
        "Save as a permanent demo case",
        value=bool(data["permanent"]), key="intake_widget_permanent",
    )


def render(store: SQLiteStore | None = None) -> None:
    """Render the four-step intake and post-submit actions."""
    render_disclaimer()
    store = store or SQLiteStore()
    create_schema(store)
    render_header(
        "New Application",
        "Enter synthetic applicant details and prepare a case for assessment.",
        "OPERATE  /  GUIDED INTAKE",
    )
    application_id = st.session_state.get("intake_application_id")
    if application_id:
        saved = get_application(str(application_id), store)
        applicant = str(saved.iloc[0]["name"]) if not saved.empty else "Applicant"
        with st.container(border=True):
            st.success(f"Application submitted for {applicant}.")
            st.caption(f"Case reference: {application_id} · Stage: Submitted")
            st.button(
                "Run AI assessment now",
                type="primary",
                width="stretch",
                key="intake_run_assessment",
                on_click=_run_assessment,
                args=(str(application_id),),
            )
            st.button("Add another", key="intake_add_another", on_click=_add_another)
        return

    if "intake_step" not in st.session_state:
        st.session_state["intake_step"] = 0
    data = _intake()
    step = int(st.session_state["intake_step"])
    _render_stepper(step)
    if st.session_state.get("intake_error"):
        st.warning(st.session_state["intake_error"])
    if step == 0:
        _render_applicant(data)
    elif step == 1:
        _render_employment(data)
    elif step == 2:
        _render_loan(data)
    else:
        _render_document_step(data)

    candidate = _step_data(step)
    validation = _validate(candidate, step)
    left, right = st.columns(2)
    with left:
        st.button(
            "Back",
            disabled=step == 0,
            key="intake_back",
            width="stretch",
            on_click=_step_transition,
            args=(step, -1),
        )
    with right:
        if step < 3:
            st.button(
                "Next",
                disabled=bool(validation),
                type="primary",
                key="intake_next",
                width="stretch",
                on_click=_step_transition,
                args=(step, 1),
            )
        else:
            st.button(
                "Submit application",
                disabled=bool(validation),
                type="primary",
                key="submit_application",
                width="stretch",
                on_click=_submit_application,
                args=(store,),
            )
    if validation:
        st.caption(validation)
