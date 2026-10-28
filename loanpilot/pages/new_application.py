"""Guided synthetic personal-loan application intake."""

from datetime import date, datetime
from io import BytesIO
from pathlib import Path
import random
import re
import shutil
from typing import Any
import uuid

import streamlit as st

from loanpilot import config
from loanpilot.agent.policy_engine import pricing_rate
from loanpilot.components import fmt_inr
from loanpilot.data.queries import (
    create_intake_application,
    get_application,
    get_documents,
    get_existing_loans,
    list_applications,
)
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore
from loanpilot.theme import render_disclaimer, render_header

_STEPS = ("Applicant", "Employment and income", "Loan request", "Documents")
_PURPOSES = ("Home improvement", "Medical expenses", "Education", "Travel", "Other")
_EMPLOYMENT_TYPES = ("Salaried", "Self-employed", "Other")
_DOCUMENT_INPUTS = (
    ("intake_payslip", "Payslip"),
    ("intake_bank_statement", "Bank statement"),
    ("intake_kyc_pdf", "KYC"),
)


def estimate_bureau_score(
    income: float,
    existing_emi: float,
    job_months: int,
    experience_months: int,
    pan: str,
) -> int | None:
    """Create a stable synthetic score influenced by declared capacity and tenure."""
    if experience_months < 12:
        return None
    ratio = existing_emi / income if income > 0 else 1.0
    seed = f"{pan}|{income:.2f}|{existing_emi:.2f}|{job_months}|{experience_months}"
    stable_adjustment = random.Random(seed).randint(-8, 8)
    score = 635 + (income / 1000 - 30) * 1.1 + min(job_months, 60) * 0.65
    score -= min(ratio, 1.5) * 110
    return max(300, min(850, round(score + stable_adjustment)))


def _initialize_form() -> None:
    """Set form defaults before their widgets are created."""
    defaults: dict[str, Any] = {
        "intake_step": 0,
        "intake_name": "",
        "intake_dob": date(1990, 1, 1),
        "intake_city": "",
        "intake_pan": f"DEMO{uuid.uuid4().hex[:8].upper()}",
        "intake_mobile": "",
        "intake_employer": "",
        "intake_employment_type": "Salaried",
        "intake_job_months": 12,
        "intake_experience_months": 12,
        "intake_income": 50000.0,
        "intake_existing_emi": 0.0,
        "intake_amount": 200000.0,
        "intake_tenure": 36,
        "intake_purpose": "Other",
        "intake_sample_persona": "",
        "intake_sample_pack": False,
        "intake_consent": False,
        "intake_declaration": False,
        "intake_error": "",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _load_sample_applicant() -> None:
    """Copy a persona profile into the intake widget state."""
    application_id = st.session_state.get("intake_sample_persona")
    if not application_id:
        return
    store = SQLiteStore()
    application = get_application(application_id, store)
    if application.empty:
        st.session_state["intake_error"] = (
            "The selected sample case is not available in this database."
        )
        return
    case = application.iloc[0]
    loan_rows = get_existing_loans(case["customer_id"], store)
    st.session_state.update(
        {
            "intake_name": case["name"],
            "intake_dob": date.fromisoformat(str(case["dob"])),
            "intake_city": case["city"],
            "intake_pan": f"DEMO-{case['persona_key']}",
            "intake_mobile": "9000000000",
            "intake_employer": case["employer"],
            "intake_employment_type": case["employment_type"],
            "intake_job_months": int(case["current_tenure_months"]),
            "intake_experience_months": int(case["total_experience_months"]),
            "intake_income": float(case["net_monthly_income"]),
            "intake_amount": float(case["requested_amount"]),
            "intake_tenure": int(case["tenure_months"]),
            "intake_purpose": case["purpose"]
            if case["purpose"] in _PURPOSES
            else "Other",
            "intake_existing_emi": float(loan_rows["emi"].sum()) if not loan_rows.empty else 0.0,
            "intake_sample_pack": False,
            "intake_error": "",
        }
    )


def _go_back() -> None:
    """Move to the preceding intake step."""
    st.session_state["intake_step"] = max(0, st.session_state["intake_step"] - 1)
    st.session_state["intake_error"] = ""


def _validate_step(step: int) -> str:
    """Return one concise inline validation message for the active step."""
    state = st.session_state
    if step == 0:
        if not state["intake_name"].strip() or not state["intake_city"].strip():
            return "Enter the applicant name and city."
        if not re.fullmatch(r"DEMO[A-Z0-9-]{4,24}", state["intake_pan"].strip().upper()):
            return "Use a synthetic PAN identifier beginning with DEMO."
        if not re.fullmatch(r"\d{10}", state["intake_mobile"].strip()):
            return "Enter a 10-digit demo mobile number."
        if state["intake_dob"] >= date.today():
            return "Date of birth must be in the past."
    elif step == 1:
        if not state["intake_employer"].strip():
            return "Enter an employer."
        if int(state["intake_job_months"]) > int(state["intake_experience_months"]):
            return "Current-job tenure cannot exceed total work experience."
        if float(state["intake_income"]) <= 0 or int(state["intake_experience_months"]) < 0:
            return "Income must be positive and experience cannot be negative."
    elif step == 2:
        if float(state["intake_amount"]) <= 0:
            return "Loan amount must be greater than zero."
    elif step == 3:
        if not state["intake_consent"] or not state["intake_declaration"]:
            return "Consent and the synthetic-data declaration are required."
        if not state["intake_sample_pack"] and any(
            state.get(key) is None for key, _ in _DOCUMENT_INPUTS
        ):
            return "Upload all three PDFs or attach a persona sample pack."
    return ""


def _go_next() -> None:
    """Validate the current step and move forward when it is complete."""
    step = int(st.session_state["intake_step"])
    error = _validate_step(step)
    st.session_state["intake_error"] = error
    if not error:
        st.session_state["intake_step"] = min(len(_STEPS) - 1, step + 1)


def _use_sample_pack() -> None:
    """Select the sample persona's registered documents for this new case."""
    if not st.session_state.get("intake_sample_persona"):
        st.session_state["intake_error"] = "Select a sample applicant before using a sample pack."
        return
    st.session_state["intake_sample_pack"] = True
    st.session_state["intake_error"] = ""


def _load_sample_cases(store: SQLiteStore) -> None:
    """Load persona data when an empty database has no sample applicants."""
    if store.table_counts().get("cur_applications", 0):
        st.warning("Sample data was not loaded because this database now contains applications.")
        return
    counts = seed_demo_data(store)
    st.toast(
        "Synthetic sample cases loaded. "
        + ", ".join(f"{table}: {count}" for table, count in counts.items())
    )


def _extract_pdf_text(content: bytes) -> tuple[str, str | None]:
    """Extract PDF text, returning an explicit document flag for unreadable files."""
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:
        return "", "PDF text extraction is unavailable (pypdf is not installed)."
    try:
        pages = PdfReader(BytesIO(content), strict=False).pages
        text = "\n".join(page.extract_text() or "" for page in pages).strip()
    except (PdfReadError, OSError, ValueError, TypeError) as error:
        return "", f"PDF could not be read: {type(error).__name__}"
    if not text:
        return "", "PDF contains no extractable text."
    return text, None


def _prepare_documents(
    application_id: str,
    store: SQLiteStore,
) -> list[dict[str, str]]:
    """Save uploaded or selected persona PDFs and prepare RAW document records."""
    folder = config.DATA_DIR / "uploads" / application_id
    folder.mkdir(parents=True, exist_ok=True)
    prepared: list[dict[str, str]] = []
    if st.session_state.get("intake_sample_pack"):
        sample_id = st.session_state.get("intake_sample_persona")
        sample_docs = get_documents(sample_id, store)
        if sample_docs.empty:
            raise ValueError("The selected persona has no registered sample documents.")
        for doc in sample_docs.to_dict("records"):
            source = (config.PROJECT_ROOT / Path(doc["file_path"])).resolve()
            if not source.is_relative_to(config.PROJECT_ROOT):
                raise ValueError("Sample document path is outside the project root.")
            if not source.is_file():
                raise FileNotFoundError(f"Persona sample document is missing: {source}")
            target = folder / Path(doc["file_name"]).name
            shutil.copyfile(source, target)
            prepared.append(
                {
                    "doc_type": doc["doc_type"],
                    "file_name": target.name,
                    "file_path": target.relative_to(config.PROJECT_ROOT).as_posix(),
                    "text_content": doc["text_content"],
                }
            )
        return prepared

    input_to_type = {
        "intake_payslip": "payslip",
        "intake_bank_statement": "bank_statement_summary",
        "intake_kyc_pdf": "kyc_sheet",
    }
    for key, label in _DOCUMENT_INPUTS:
        uploaded = st.session_state.get(key)
        if uploaded is None:
            continue
        if not uploaded.name.lower().endswith(".pdf"):
            raise ValueError(f"{label} must be uploaded as a PDF.")
        safe_name = Path(uploaded.name.replace("\\", "/")).name
        target = folder / f"{input_to_type[key]}.pdf"
        content = uploaded.getvalue()
        target.write_bytes(content)
        extracted, flag = _extract_pdf_text(content)
        if flag:
            extracted = f"[DOCUMENT FLAG: {flag}]"
        prepared.append(
            {
                "doc_type": input_to_type[key],
                "file_name": safe_name,
                "file_path": target.relative_to(config.PROJECT_ROOT).as_posix(),
                "text_content": extracted,
            }
        )
    return prepared


def _submit_application(store: SQLiteStore) -> None:
    """Validate, persist intake data, and navigate to its AI Assessment."""
    error = _validate_step(3)
    if error:
        st.session_state["intake_error"] = error
        return
    state = st.session_state
    dob = state["intake_dob"]
    today = date.today()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    income = float(state["intake_income"])
    existing_emi = float(state["intake_existing_emi"])
    job_months = int(state["intake_job_months"])
    experience_months = int(state["intake_experience_months"])
    pan = state["intake_pan"].strip().upper()
    score = estimate_bureau_score(
        income, existing_emi, job_months, experience_months, pan
    )
    thin_file = experience_months < 12
    bureau = {
        "provider": "Synthetic bureau simulator",
        "score": score,
        "thin_file": thin_file,
        "active_accounts": 0,
        "enquiries_6m": 0 if thin_file else 1,
        "max_dpd_24m": 0,
        "written_off": False,
        "utilization_pct": 0.0,
        "document_flags": [],
    }
    kyc = {
        "provider": "Synthetic KYC simulator",
        "pan_status": "pending",
        "name_match_score": 1.0,
        "pan_demo_id": pan,
        "cersai": "not applicable (unsecured)",
    }
    submitted_at = datetime.now().isoformat(timespec="seconds")
    generated_app_id = f"APP-NEW-{uuid.uuid4().hex[:12].upper()}"
    try:
        documents = _prepare_documents(generated_app_id, store)
    except (OSError, ValueError) as error:
        state["intake_error"] = str(error)
        return
    expected_types = {"payslip", "bank_statement_summary", "kyc_sheet"}
    actual_types = {document["doc_type"] for document in documents}
    flags = sorted(expected_types - actual_types)
    flags.extend(
        f"{document['doc_type']}: unreadable"
        for document in documents
        if document["text_content"].startswith("[DOCUMENT FLAG:")
    )
    bureau["document_flags"] = flags
    applicant = {
        "name": state["intake_name"].strip(),
        "dob": dob.isoformat(),
        "age": age,
        "city": state["intake_city"].strip(),
        "mobile": state["intake_mobile"].strip(),
        "employer": state["intake_employer"].strip(),
        "employment_type": state["intake_employment_type"],
        "current_tenure_months": job_months,
        "total_experience_months": experience_months,
        "net_monthly_income": income,
        "existing_emi": existing_emi,
        "pan_demo_id": pan,
    }
    application = {
        "requested_amount": float(state["intake_amount"]),
        "tenure_months": int(state["intake_tenure"]),
        "purpose": state["intake_purpose"],
        "submitted_at": submitted_at,
    }
    application_id = create_intake_application(
        applicant,
        application,
        bureau,
        kyc,
        documents,
        store,
        application_id=generated_app_id,
    )
    state["selected_application"] = application_id
    state["assessment_application_selector"] = application_id
    state["intake_application_id"] = application_id
    from loanpilot.navigation import OPERATE_PAGES

    st.switch_page(OPERATE_PAGES["ai_assessment"])


def _render_stepper(step: int) -> None:
    """Display the four intake steps with explicit text and icon status."""
    columns = st.columns(4)
    for index, (column, label) in enumerate(zip(columns, _STEPS, strict=True)):
        state = "Done" if index < step else "Current" if index == step else "Upcoming"
        icon = "✓" if index < step else "●" if index == step else "○"
        with column:
            st.markdown(
                f'<div class="lp-pipeline-card {"is-done" if index < step else "is-ready" if index == step else ""}">'
                f'<div class="lp-pipeline-state">{icon} {state}</div>'
                f'<div class="lp-pipeline-label">{index + 1}. {label}</div></div>',
                unsafe_allow_html=True,
            )


def _render_applicant_step() -> None:
    """Render personal identity fields."""
    st.text_input("Full name *", key="intake_name")
    first, second = st.columns(2)
    with first:
        st.date_input("Date of birth *", key="intake_dob", max_value=date.today())
        st.text_input("City *", key="intake_city")
    with second:
        st.text_input("Fake PAN ID (DEMO… only) *", key="intake_pan")
        st.text_input("Mobile number *", key="intake_mobile", max_chars=10)


def _render_employment_step() -> None:
    """Render employment and declared income details."""
    st.text_input("Employer *", key="intake_employer")
    first, second, third = st.columns(3)
    with first:
        st.selectbox("Employment type *", _EMPLOYMENT_TYPES, key="intake_employment_type")
    with second:
        st.number_input("Months in current job *", min_value=0, max_value=600, key="intake_job_months")
    with third:
        st.number_input("Total experience (months) *", min_value=0, max_value=600, key="intake_experience_months")
    first, second = st.columns(2)
    with first:
        st.number_input("Net monthly income (Rs) *", min_value=1.0, step=1000.0, key="intake_income")
    with second:
        st.number_input("Existing monthly EMIs (Rs)", min_value=0.0, step=1000.0, key="intake_existing_emi")


def _render_loan_step() -> None:
    """Render loan request details and indicative policy-grid pricing."""
    first, second = st.columns(2)
    with first:
        st.number_input("Requested amount (Rs) *", min_value=1000.0, step=5000.0, key="intake_amount")
    with second:
        st.slider("Tenure (months) *", min_value=12, max_value=60, step=1, key="intake_tenure")
    st.selectbox("Purpose *", _PURPOSES, key="intake_purpose")
    score = estimate_bureau_score(
        float(st.session_state["intake_income"]),
        float(st.session_state["intake_existing_emi"]),
        int(st.session_state["intake_job_months"]),
        int(st.session_state["intake_experience_months"]),
        str(st.session_state["intake_pan"]),
    )
    rate = pricing_rate(score)
    if rate is None:
        st.info("Indicative EMI: no grid rate yet (thin-file profile).")
    else:
        monthly = rate / 12
        months = int(st.session_state["intake_tenure"])
        factor = (1 + monthly) ** months
        emi = float(st.session_state["intake_amount"]) * monthly * factor / (factor - 1)
        st.metric("Indicative EMI", fmt_inr(emi), help=f"Illustrative grid rate: {rate:.2%} p.a.")


def _render_documents_step(store: SQLiteStore) -> None:
    """Render PDF uploads, sample pack option, and required acknowledgements."""
    state = st.session_state
    st.subheader("Review your entries")
    st.caption("Read-only summary before submission.")
    st.dataframe(
        [
            {"Item": "Applicant", "Your entry": state["intake_name"]},
            {"Item": "Date of birth", "Your entry": state["intake_dob"].strftime("%d %b %Y")},
            {"Item": "City", "Your entry": state["intake_city"]},
            {"Item": "Fake PAN ID", "Your entry": state["intake_pan"]},
            {"Item": "Employer", "Your entry": state["intake_employer"]},
            {"Item": "Employment", "Your entry": state["intake_employment_type"]},
            {"Item": "Job tenure", "Your entry": f"{state['intake_job_months']} months"},
            {"Item": "Monthly income", "Your entry": fmt_inr(state["intake_income"])},
            {"Item": "Existing EMIs", "Your entry": fmt_inr(state["intake_existing_emi"])},
            {"Item": "Loan request", "Your entry": fmt_inr(state["intake_amount"])},
            {"Item": "Tenure", "Your entry": f"{state['intake_tenure']} months"},
            {"Item": "Purpose", "Your entry": state["intake_purpose"]},
        ],
        width="stretch",
        hide_index=True,
    )
    st.subheader("Documents and declarations")
    st.write("Upload synthetic PDFs or attach the registered documents for a sample applicant.")
    for key, label in _DOCUMENT_INPUTS:
        st.file_uploader(f"{label} PDF", type=["pdf"], key=key)
    st.button(
        "Use sample pack",
        on_click=_use_sample_pack,
        key="use_sample_pack",
    )
    if st.session_state["intake_sample_pack"]:
        st.success("Persona sample PDFs will be copied and attached.")
    elif not any(st.session_state.get(key) for key, _ in _DOCUMENT_INPUTS):
        st.caption("No documents selected. Missing or unreadable files will be flagged during assessment.")
    st.checkbox("I consent to this synthetic demo application being processed. *", key="intake_consent")
    st.checkbox("I confirm these are fictional demonstration details. *", key="intake_declaration")


def render(store: SQLiteStore | None = None) -> None:
    """Render the four-step guided intake workflow."""
    render_disclaimer()
    _initialize_form()
    store = store or SQLiteStore()
    create_schema(store)
    render_header(
        "New Application",
        "Capture a fictional applicant and prepare a case for the deterministic assessment workflow.",
        "OPERATE  /  GUIDED INTAKE",
    )
    samples = list_applications({"demo_only": True}, store)
    if samples.empty and store.table_counts().get("cur_applications", 0) == 0:
        st.info("No sample cases are loaded. You can continue with a custom applicant or load the synthetic personas.")
        st.button(
            "Load sample cases",
            on_click=_load_sample_cases,
            args=(store,),
            key="intake_load_sample_cases",
        )
    elif samples.empty:
        st.caption("No sample personas are loaded; you can continue with a custom applicant.")
    sample_options = ["", *samples["application_id"].tolist()]
    st.selectbox(
        "Load sample applicant",
        sample_options,
        format_func=lambda value: (
            "Choose a persona to prefill the form"
            if not value
            else str(
                samples.loc[
                    samples.application_id == value, "applicant"
                ].iloc[0]
            )
        ),
        key="intake_sample_persona",
        on_change=_load_sample_applicant,
    )
    if st.session_state["intake_sample_persona"]:
        with st.expander("Selected sample reference"):
            st.code(str(st.session_state["intake_sample_persona"]))
    _render_stepper(int(st.session_state["intake_step"]))
    st.progress((int(st.session_state["intake_step"]) + 1) / len(_STEPS))
    if st.session_state.get("intake_error"):
        st.warning(st.session_state["intake_error"])
    step = int(st.session_state["intake_step"])
    if step == 0:
        _render_applicant_step()
    elif step == 1:
        _render_employment_step()
    elif step == 2:
        _render_loan_step()
    else:
        _render_documents_step(store)

    left, right = st.columns(2)
    with left:
        st.button(
            "Back",
            on_click=_go_back,
            key="intake_back",
            disabled=step == 0,
            width="stretch",
        )
    with right:
        if step < len(_STEPS) - 1:
            st.button("Next", on_click=_go_next, key="intake_next", type="primary", width="stretch")
        else:
            st.button(
                "Submit application",
                on_click=_submit_application,
                args=(store,),
                key="submit_application",
                type="primary",
                width="stretch",
            )
