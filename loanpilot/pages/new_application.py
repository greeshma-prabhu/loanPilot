"""Guided synthetic personal-loan application intake."""

from datetime import date, datetime
from difflib import SequenceMatcher
from io import BytesIO
import json
import logging
import mimetypes
from pathlib import Path
import random
import re
import uuid

import streamlit as st
from fpdf import FPDF

from loanpilot import config
from loanpilot.agent.policy_engine import pricing_rate
from loanpilot.badges import implementation_badge
from loanpilot.components import fmt_inr
from loanpilot.data.queries import (
    create_intake_application,
    get_application,
    list_intake_customers,
)
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore
from loanpilot.theme import render_disclaimer, render_header

_NEW_STEPS = ("Applicant", "Identity (eKYC)", "Employment and income", "Loan request", "Documents")
_EXISTING_STEPS = ("Applicant", "Employment and income", "Loan request", "Documents")
_NEW_STEP_KINDS = ("applicant", "identity", "employment", "loan", "documents")
_EXISTING_STEP_KINDS = ("applicant", "employment", "loan", "documents")
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
    "eKYC not completed (pending)",
    "Name differs from the identity document (match about 0.70)",
)
_IDENTITY_DOC_TYPES = ("pan_identity", "aadhaar_identity")
_IDENTITY_LABELS = {
    "pan_identity": "PAN-type document",
    "aadhaar_identity": "Aadhaar-type document",
}
_LOGGER = logging.getLogger(__name__)


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
        "customer_type": "New to the bank",
        "customer_id": None,
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
        "kyc": {
            "status": "pending",
            "name_match": 0.0,
            "method": "Not completed",
            "reason": None,
            "document_references": [],
        },
        "identity_mode": "Use demo identity",
        "identity_documents": {},
        "identity_sheet": None,
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


def _step_kinds(data: dict) -> tuple[str, ...]:
    """Return the active step identifiers for the selected customer type."""
    return (
        _EXISTING_STEP_KINDS
        if data.get("customer_type") == "Existing customer"
        else _NEW_STEP_KINDS
    )


def _widget_values(step_kind: str) -> dict:
    """Read values only from widgets rendered for the active step."""
    if step_kind == "applicant":
        customer_type = st.session_state["intake_widget_customer_type"]
        if customer_type == "Existing customer":
            customer_id = st.session_state.get("intake_widget_existing_customer")
            return {
                "customer_type": customer_type,
                "customer_id": customer_id,
                "existing_customer": True,
            }
        return {
            "customer_type": customer_type,
            "customer_id": None,
            "existing_customer": False,
            "name": st.session_state["intake_widget_name"],
            "dob": st.session_state["intake_widget_dob"].isoformat(),
            "city": st.session_state["intake_widget_city"],
            "mobile": st.session_state["intake_widget_mobile"],
        }
    if step_kind == "identity":
        identity_mode = st.session_state.get(
            "intake_widget_identity_mode", "Use demo identity"
        )
        identity_documents = {}
        if identity_mode == "Upload documents":
            for doc_type in _IDENTITY_DOC_TYPES:
                uploaded = st.session_state.get(f"intake_upload_{doc_type}")
                if uploaded is not None:
                    identity_documents[doc_type] = {
                        "name": Path(uploaded.name.replace("\\", "/")).name,
                        "mime_type": mimetypes.guess_type(uploaded.name)[0]
                        or "application/octet-stream",
                        "content": uploaded.getvalue(),
                    }
        return {
            "identity_mode": identity_mode,
            "identity_documents": identity_documents,
        }
    if step_kind == "employment":
        if _intake().get("customer_type") == "Existing customer":
            return {}
        return {
            key: st.session_state[f"intake_widget_{key}"]
            for key in (
                "employer",
                "employment_type",
                "job_months",
                "experience_months",
                "income",
                "existing_emi",
            )
        }
    if step_kind == "loan":
        amount_tenure = {
            "amount": st.session_state["intake_widget_amount"],
            "tenure": st.session_state["intake_widget_tenure"],
            "purpose": st.session_state["intake_widget_purpose"],
        }
        if _intake().get("customer_type") == "Existing customer":
            amount_tenure["tenure"] = _intake()["tenure"]
        return amount_tenure

    saved = _intake()
    values = {
        "document_mode": st.session_state.get(
            "intake_widget_document_mode", saved["document_mode"]
        ),
        "consent": st.session_state.get("intake_widget_consent", saved["consent"]),
        "declaration": st.session_state.get(
            "intake_widget_declaration", saved["declaration"]
        ),
        "permanent": st.session_state.get(
            "intake_widget_permanent", saved["permanent"]
        ),
        "document_problem": st.session_state.get(
            "intake_widget_document_problem", saved["document_problem"]
        ),
        "problem_type": st.session_state.get(
            "intake_widget_problem_type", saved["problem_type"]
        ),
    }
    uploads = {}
    if values["document_mode"] == "Upload my own PDFs":
        for doc_type in _DOC_TYPES:
            uploads[doc_type] = st.session_state.get(f"intake_upload_{doc_type}")
    values["uploads"] = uploads
    return values


def _step_data(step_kind: str) -> dict:
    """Overlay current widget values on the saved intake for validation."""
    return {**_intake(), **_widget_values(step_kind)}


def _validate(data: dict, step_kind: str) -> str:
    """Return a short error when the active step is incomplete or invalid."""
    if step_kind == "applicant":
        if data.get("customer_type") == "Existing customer":
            return "" if data.get("customer_id") else "Select an existing customer."
        if not data["name"].strip() or not data["city"].strip():
            return "Name and city are required."
        dob = date.fromisoformat(str(data["dob"]))
        today = date.today()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        if not 18 <= age <= 75:
            return "Applicant age must be between 18 and 75."
        if not re.fullmatch(r"\d{10}", str(data["mobile"]).strip()):
            return "Enter a 10-digit mobile number."
    elif step_kind == "employment":
        if data.get("customer_type") == "Existing customer":
            return ""
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
    elif step_kind == "loan":
        if float(data["amount"]) <= 0:
            return "Loan amount must be above zero."
        if not 12 <= int(data["tenure"]) <= 60:
            return "Tenure must be between 12 and 60 months."
        if data["purpose"] not in _PURPOSES:
            return "Select a loan purpose."
    elif step_kind == "documents":
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
    kinds = _step_kinds(current)
    step_kind = kinds[step]
    values = _widget_values(step_kind)
    updated = {**current, **values}
    error = _validate(updated, step_kind) if direction > 0 else ""
    if step_kind == "identity" and direction > 0:
        if updated["identity_mode"] == "Upload documents":
            updated["kyc"] = _uploaded_identity_result(updated)
        elif updated["kyc"].get("status") != "verified":
            updated["kyc"] = _pending_kyc("eKYC was skipped.", updated["pan"])
    st.session_state["intake"] = updated
    st.session_state["intake_error"] = error
    if not error:
        st.session_state["intake_step"] = min(len(kinds) - 1, max(0, step + direction))


def _sync_intake_widget(field: str, widget_key: str) -> None:
    """Keep interactive document options in canonical state across rerenders."""
    data = {**_intake(), field: st.session_state[widget_key]}
    st.session_state["intake"] = data


def _pending_kyc(reason: str, pan_id: str | None = None) -> dict:
    """Return a structured pending identity result for the demo."""
    return {
        "status": "pending",
        "pan_status": "pending",
        "name_match": 0.0,
        "name_match_score": 0.0,
        "method": "Not completed",
        "verified_at": None,
        "reason": reason,
        "document_references": [],
        "pan_demo_id": pan_id or _intake().get("pan"),
        "provider": "Simulated identity check",
        "cersai": "not applicable (unsecured)",
    }


def _sync_customer_type(customers: list[dict]) -> None:
    """Apply the customer type chosen on the currently visible applicant step."""
    customer_type = st.session_state["intake_widget_customer_type"]
    if customer_type == "Existing customer":
        st.session_state["intake"] = {
            **_intake(),
            "customer_type": customer_type,
            "existing_customer": True,
            "kyc": {
                "status": "verified",
                "pan_status": "verified",
                "name_match": 1.0,
                "name_match_score": 1.0,
                "method": "KYC on file (core banking)",
                "verified_at": datetime.now().isoformat(timespec="seconds"),
                "reason": "",
                "document_references": [],
                "provider": "Synthetic core banking record",
            },
        }
        if customers:
            _set_existing_customer(customers[0])
    else:
        reset = _initial_intake()
        reset["customer_type"] = customer_type
        st.session_state["intake"] = reset
        st.session_state["intake_step"] = 0
        reset_widgets = {
            "name": "",
            "dob": date.fromisoformat(reset["dob"]),
            "city": "",
            "mobile": "",
            "employer": "",
            "employment_type": reset["employment_type"],
            "job_months": reset["job_months"],
            "experience_months": reset["experience_months"],
            "income": reset["income"],
            "existing_emi": reset["existing_emi"],
            "amount": reset["amount"],
            "tenure": reset["tenure"],
            "purpose": reset["purpose"],
        }
        for field, value in reset_widgets.items():
            st.session_state[f"intake_widget_{field}"] = value


def _set_existing_customer(customer: dict) -> None:
    """Copy one selected core record into canonical intake state."""
    customer_id = customer["customer_id"]
    intake = {
        **_intake(),
        "customer_type": "Existing customer",
        "existing_customer": True,
        "customer_id": customer_id,
        "name": customer["name"],
        "dob": customer["dob"],
        "city": customer["city"],
        "mobile": customer.get("mobile", ""),
        "employer": customer["employer"],
        "employment_type": customer["employment_type"],
        "job_months": int(customer["current_tenure_months"]),
        "experience_months": int(customer["total_experience_months"]),
        "income": float(customer["net_monthly_income"]),
        "existing_emi": 0.0,
        "pan": customer["pan_demo_id"],
        "tenure": int(customer["prior_tenure_months"]),
        "kyc": {
            "status": "verified",
            "pan_status": "verified",
            "name_match": 1.0,
            "name_match_score": 1.0,
            "method": "KYC on file (core banking)",
            "verified_at": datetime.now().isoformat(timespec="seconds"),
            "reason": "",
            "document_references": [],
            "provider": "Synthetic core banking record",
        },
        "identity_mode": "KYC on file (core banking)",
        "identity_documents": {},
        "identity_sheet": None,
    }
    st.session_state["intake"] = intake
    st.session_state["intake_widget_existing_customer"] = customer_id
    for field in ("name", "city", "mobile", "employer"):
        st.session_state[f"intake_widget_{field}"] = intake[field]
    st.session_state["intake_widget_dob"] = date.fromisoformat(intake["dob"])
    for field in ("employment_type", "job_months", "experience_months", "income", "existing_emi", "tenure"):
        st.session_state[f"intake_widget_{field}"] = intake[field]


def _select_existing_customer(customers: list[dict]) -> None:
    """Copy the selected core record into canonical intake state."""
    customer_id = st.session_state["intake_widget_existing_customer"]
    customer = next(
        (row for row in customers if row["customer_id"] == customer_id), None
    )
    if customer is None:
        raise ValueError(f"Unknown existing customer id: {customer_id}")
    _set_existing_customer(customer)


def _identity_text_name(text: str) -> str | None:
    """Read an explicitly labelled holder name from extracted document text."""
    match = re.search(
        r"(?im)^\s*(?:holder\s+)?name(?:\s+of\s+holder)?\s*[:\-]\s*(.+?)\s*$",
        text,
    )
    return match.group(1).strip() if match else None


def _uploaded_identity_result(data: dict) -> dict:
    """Read uploaded synthetic IDs and compute a deterministic name match."""
    from loanpilot.agent.llm import extract_identity_holder_name

    documents = data.get("identity_documents", {})

    def pending_result() -> dict:
        result = _pending_kyc("could not read documents", data.get("pan"))
        result["method"] = "eKYC document upload (simulated registry check)"
        result["document_references"] = [
            document["name"] for document in documents.values()
        ]
        return result

    if any(doc_type not in documents for doc_type in _IDENTITY_DOC_TYPES):
        return pending_result()

    extracted_names: dict[str, str] = {}
    readable_text: dict[str, str] = {}
    extracted_pan = ""
    for doc_type in _IDENTITY_DOC_TYPES:
        document = documents[doc_type]
        content = document["content"]
        mime_type = document["mime_type"]
        gemini_result = extract_identity_holder_name(content, mime_type)
        name = gemini_result.get("holder_name") if gemini_result else None
        if doc_type == "pan_identity" and gemini_result:
            extracted_pan = gemini_result.get("pan_number", "")
        text = ""
        if mime_type == "application/pdf":
            text, _ = _extract_pdf_text(content)
            name = name or _identity_text_name(text)
            if doc_type == "pan_identity" and not extracted_pan:
                pan_match = re.search(
                    r"(?:PAN(?:\s+(?:number|identifier))?\s*[:\-]\s*)?([A-Z]{5}\d{4}[A-Z]|DEMO[A-Z0-9]+)",
                    text.upper(),
                )
                extracted_pan = pan_match.group(1) if pan_match else ""
        if not name:
            return pending_result()
        extracted_names[doc_type] = name
        document["extracted_name"] = name
        readable_text[doc_type] = text

    holder_name = extracted_names.get("pan_identity") or extracted_names["aadhaar_identity"]
    normalized_name = " ".join(str(data["name"]).casefold().split())
    normalized_holder = " ".join(holder_name.casefold().split())
    match_score = SequenceMatcher(None, normalized_name, normalized_holder).ratio()
    pan_text = readable_text.get("pan_identity", "")
    pan_found = bool(
        str(data["pan"]).casefold() == extracted_pan.casefold()
        or re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", extracted_pan.upper())
    )
    pan_status = "verified" if pan_found else "not_found"
    status = (
        "invalid"
        if pan_status == "not_found"
        else "verified"
        if match_score >= 0.85
        else "pending"
    )
    references = [document["name"] for document in documents.values()]
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "status": status,
        "pan_status": pan_status,
        "name_match": round(match_score, 2),
        "name_match_score": round(match_score, 2),
        "method": "eKYC document upload (simulated registry check)",
        "verified_at": now,
        "reason": "" if match_score >= 0.85 else "manual identity review",
        "document_references": references,
        "pan_demo_id": data["pan"],
        "provider": "Simulated identity check",
        "cersai": "not applicable (unsecured)",
    }


def _verify_identity_documents() -> None:
    """Capture and evaluate uploaded documents from the active identity step."""
    data = {**_intake(), **_widget_values("identity")}
    data["kyc"] = _uploaded_identity_result(data)
    st.session_state["intake"] = data


def _skip_identity() -> None:
    """Record an explicit eKYC skip without blocking the next step."""
    st.session_state["intake"] = {
        **_intake(),
        "kyc": _pending_kyc("eKYC was skipped.", _intake().get("pan")),
    }


def _use_demo_identity() -> None:
    """Generate a consistent watermarked synthetic identity sheet."""
    data = _intake()
    text = "\n".join(
        (
            "SYNTHETIC IDENTITY SHEET",
            f"Name: {data['name']}",
            f"PAN demo identifier: {data['pan']}",
            "Registry result: verified (simulated)",
            "SYNTHETIC SAMPLE, DEMO ONLY",
        )
    )
    content = _pdf_bytes("Synthetic identity sheet", text.splitlines())
    now = datetime.now().isoformat(timespec="seconds")
    data["identity_sheet"] = {"name": "identity_sheet.pdf", "content": content, "text": text}
    data["kyc"] = {
        "status": "verified",
        "pan_status": "verified",
        "name_match": 1.0,
        "name_match_score": 1.0,
        "method": "Demo identity",
        "verified_at": now,
        "reason": "",
        "document_references": ["identity_sheet.pdf"],
        "pan_demo_id": data["pan"],
        "provider": "Simulated identity check",
        "cersai": "not applicable (unsecured)",
    }
    st.session_state["intake"] = data


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


def _save_identity_documents(application_id: str, data: dict) -> list[dict[str, str]]:
    """Persist identity evidence under uploads and return RAW document records."""
    folder = config.DATA_DIR / "uploads" / application_id / "kyc"
    records: list[dict[str, str]] = []
    identity_sheet = data.get("identity_sheet")
    uploaded_documents = data.get("identity_documents", {})
    if identity_sheet:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "identity_sheet.pdf"
        path.write_bytes(identity_sheet["content"])
        records.append(
            {
                "doc_type": "identity_sheet",
                "file_name": path.name,
                "file_path": path.relative_to(config.PROJECT_ROOT).as_posix(),
                "text_content": identity_sheet["text"],
            }
        )
    for doc_type, document in uploaded_documents.items():
        folder.mkdir(parents=True, exist_ok=True)
        suffix = Path(document["name"]).suffix.casefold()
        if suffix not in {".pdf", ".png", ".jpg", ".jpeg"}:
            raise ValueError(f"Unsupported identity document type: {suffix or 'unknown'}")
        filename = f"{doc_type}{suffix}"
        path = folder / filename
        path.write_bytes(document["content"])
        extracted_name = document.get("extracted_name", "")
        text_content = (
            f"Document type: {doc_type}\nHolder name: {extracted_name}"
            if extracted_name
            else "[DOCUMENT FLAG: could not read documents]"
        )
        records.append(
            {
                "doc_type": doc_type,
                "file_name": Path(document["name"]).name,
                "file_path": path.relative_to(config.PROJECT_ROOT).as_posix(),
                "text_content": text_content,
            }
        )
    return records


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
        if key not in {
            "uploads",
            "identity_documents",
            "identity_sheet",
            "consent",
            "declaration",
            "permanent",
        }
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


def _autofill_demo() -> None:
    """Replace intake entries with a fictional example without pre-consenting."""
    data = _initial_intake()
    data.update(
        {
            "name": "Demo Applicant",
            "dob": "1990-01-01",
            "city": "Pune",
            "mobile": "9000000000",
            "employer": "Aarambh Demo Services",
            "employment_type": "Salaried",
            "job_months": 24,
            "experience_months": 60,
            "income": 60000.0,
            "existing_emi": 5000.0,
            "amount": 250000.0,
            "tenure": 36,
            "purpose": "Education",
        }
    )
    st.session_state["intake"] = data
    st.session_state["intake_step"] = 0
    st.session_state.pop("intake_error", None)
    widget_values = {
        "customer_type": "New to the bank",
        "name": data["name"],
        "dob": date.fromisoformat(data["dob"]),
        "city": data["city"],
        "mobile": data["mobile"],
        "employer": data["employer"],
        "employment_type": data["employment_type"],
        "job_months": data["job_months"],
        "experience_months": data["experience_months"],
        "income": data["income"],
        "existing_emi": data["existing_emi"],
        "amount": data["amount"],
        "tenure": data["tenure"],
        "purpose": data["purpose"],
        "document_mode": data["document_mode"],
        "document_problem": data["document_problem"],
        "problem_type": data["problem_type"],
        "consent": data["consent"],
        "declaration": data["declaration"],
        "permanent": data["permanent"],
        "identity_mode": data["identity_mode"],
    }
    for field, value in widget_values.items():
        st.session_state[f"intake_widget_{field}"] = value
    st.session_state.pop("intake_widget_existing_customer", None)
    for doc_type in _IDENTITY_DOC_TYPES:
        st.session_state.pop(f"intake_upload_{doc_type}", None)
    for key in list(st.session_state):
        if key.startswith("intake_upload_"):
            st.session_state.pop(key, None)


def _apply_identity_problem(data: dict) -> None:
    """Apply only the selected synthetic KYC demo issue to the stored response."""
    if not data["document_problem"]:
        return
    if data["problem_type"] == "eKYC not completed (pending)":
        data["kyc"] = _pending_kyc(
            "eKYC was not completed for the demo.", data.get("pan")
        )
    elif data["problem_type"] == "Name differs from the identity document (match about 0.70)":
        data["kyc"] = {
            **data["kyc"],
            "status": "pending",
            "pan_status": "verified",
            "name_match": 0.70,
            "name_match_score": 0.70,
            "method": "Demo identity (name mismatch demo)",
            "reason": "manual identity review",
            "demo_problem": "name_mismatch",
        }


def _submit_application(store: SQLiteStore) -> None:
    """Validate canonical state, persist the case and show post-submit actions."""
    data = _intake()
    data.update(_widget_values("documents"))
    error = _validate(data, "documents")
    if error:
        st.session_state["intake"] = data
        st.session_state["intake_error"] = error
        return
    _apply_identity_problem(data)
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
        documents.extend(_save_identity_documents(application_id, data))
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
        **data["kyc"],
        "status": data["kyc"].get("status", "pending"),
        "pan_status": data["kyc"].get("pan_status", data["kyc"].get("status", "pending")),
        "name_match": float(data["kyc"].get("name_match", 0.0)),
        "name_match_score": float(data["kyc"].get("name_match", 0.0)),
        "method": data["kyc"].get("method", "Not completed"),
        "verified_at": data["kyc"].get("verified_at"),
        "document_references": data["kyc"].get("document_references", []),
        "pan_demo_id": data["pan"],
        "provider": data["kyc"].get("provider", "Simulated identity check"),
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
        "existing_customer": data.get("customer_type") == "Existing customer",
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
            customer_id=data.get("customer_id"),
            owner=str(st.session_state.get("auth", {}).get("name", "")),
        )
        if data["permanent"]:
            _permanent_case_entry(data, application_id)
    except (OSError, ValueError) as error:
        st.session_state["intake_error"] = str(error)
        return
    st.session_state["intake_application_id"] = application_id
    st.session_state["selected_application"] = application_id


def _render_stepper(step: int, step_names: tuple[str, ...]) -> None:
    """Render the active four- or five-step progress labels."""
    st.progress(
        (step + 1) / len(step_names),
        text=f"Step {step + 1} of {len(step_names)} · {step_names[step]}",
    )
    st.caption("  →  ".join(step_names))


def _render_applicant(data: dict, customers: list[dict]) -> None:
    """Render customer type selection and new- or existing-customer details."""
    st.session_state.setdefault(
        "intake_widget_customer_type", data["customer_type"]
    )
    st.radio(
        "Are you an existing Aarambh Bank customer?",
        ("Existing customer", "New to the bank"),
        key="intake_widget_customer_type",
        on_change=_sync_customer_type,
        args=(customers,),
    )
    if data["customer_type"] == "Existing customer":
        if not customers:
            st.info("No synthetic core banking customers are available yet.")
            return
        current_id = data.get("customer_id") or customers[0]["customer_id"]
        st.selectbox(
            "Search existing customers",
            [customer["customer_id"] for customer in customers],
            index=next(
                (index for index, customer in enumerate(customers)
                 if customer["customer_id"] == current_id),
                0,
            ),
            format_func=lambda customer_id: next(
                f"{customer['name']} · {customer['city']} · {customer['employer']}"
                for customer in customers
                if customer["customer_id"] == customer_id
            ),
            key="intake_widget_existing_customer",
            on_change=_select_existing_customer,
            args=(customers,),
        )
        customer = next(
            (
                item for item in customers
                if item["customer_id"] == current_id
            ),
            customers[0],
        )
        st.caption("From core banking")
        st.dataframe(
            [
                {"Field": "Name", "Value": customer["name"]},
                {"Field": "Date of birth", "Value": customer["dob"]},
                {"Field": "City", "Value": customer["city"]},
                {"Field": "Employer", "Value": customer["employer"]},
                {"Field": "Monthly income", "Value": fmt_inr(customer["net_monthly_income"])},
                {"Field": "Current job tenure", "Value": f"{customer['current_tenure_months']} months"},
            ],
            width="stretch",
            hide_index=True,
        )
        return
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


def _render_identity(data: dict) -> None:
    """Render simulated identity-document verification without blocking Next."""
    st.text_input(
        "Fake PAN ID · demo only",
        value=data["pan"],
        disabled=True,
        key="intake_identity_pan_display",
    )
    st.markdown(
        f"Registry check: {implementation_badge('simulated')}",
        unsafe_allow_html=True,
    )
    st.warning(
        "Use fake or sample documents only. Do not upload real ID documents."
    )
    st.radio(
        "Identity method",
        ("Upload documents", "Use demo identity"),
        index=0 if data["identity_mode"] == "Upload documents" else 1,
        key="intake_widget_identity_mode",
        on_change=_sync_intake_widget,
        args=("identity_mode", "intake_widget_identity_mode"),
    )
    mode = st.session_state["intake_widget_identity_mode"]
    if mode == "Upload documents":
        for doc_type in _IDENTITY_DOC_TYPES:
            st.file_uploader(
                _IDENTITY_LABELS[doc_type],
                type=["pdf", "png", "jpg", "jpeg"],
                key=f"intake_upload_{doc_type}",
            )
        st.button(
            "Check identity documents",
            key="intake_check_identity",
            on_click=_verify_identity_documents,
        )
    else:
        st.caption("Creates a watermarked synthetic identity sheet from this applicant's name and fake PAN.")
        st.button(
            "Generate demo identity",
            key="intake_generate_identity",
            on_click=_use_demo_identity,
        )
    kyc = data["kyc"]
    if kyc.get("status") == "verified":
        st.success(f"Identity verified (simulated) · name match {kyc.get('name_match', 0):.2f}")
    elif kyc.get("reason") and not (
        kyc.get("reason") == "could not read documents"
        and kyc.get("method") == "Not completed"
    ):
        st.info(str(kyc["reason"]))
    st.button("Skip for now", key="intake_skip_identity", on_click=_skip_identity)


def _render_employment(data: dict) -> None:
    """Render employment and income fields."""
    if data.get("customer_type") == "Existing customer":
        st.caption("From core banking · these profile values are read-only.")
        st.dataframe(
            [
                {"Field": "Employer", "Value": data["employer"]},
                {"Field": "Employment type", "Value": data["employment_type"]},
                {"Field": "Current job tenure", "Value": f"{data['job_months']} months"},
                {"Field": "Total experience", "Value": f"{data['experience_months']} months"},
                {"Field": "Net monthly income", "Value": fmt_inr(data["income"])},
            ],
            width="stretch",
            hide_index=True,
        )
        return
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
        "Tenure (months) *",
        12,
        60,
        int(data["tenure"]),
        key="intake_widget_tenure",
        disabled=data.get("customer_type") == "Existing customer",
    )
    if data.get("customer_type") == "Existing customer":
        st.caption("Loan tenure is prefilled from the latest core banking application.")
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
        on_change=_sync_intake_widget,
        args=("document_mode", "intake_widget_document_mode"),
    )
    mode = st.session_state["intake_widget_document_mode"]
    generated_documents = mode.startswith("Generate")
    if "intake_widget_document_problem" not in st.session_state:
        st.session_state["intake_widget_document_problem"] = bool(
            data["document_problem"]
        )
    st.checkbox(
        "Add a document problem for the demo",
        value=bool(data["document_problem"]),
        key="intake_widget_document_problem",
        disabled=not generated_documents,
        on_change=_sync_intake_widget,
        args=("document_problem", "intake_widget_document_problem"),
    )
    st.session_state["intake"] = {
        **_intake(),
        "document_problem": bool(
            st.session_state["intake_widget_document_problem"]
        ),
    }
    if mode.startswith("Generate"):
        if st.session_state["intake_widget_document_problem"]:
            if "intake_widget_problem_type" not in st.session_state:
                st.session_state["intake_widget_problem_type"] = data["problem_type"]
            st.selectbox(
                "Choose document problem",
                _PROBLEMS,
                index=_PROBLEMS.index(data["problem_type"]),
                key="intake_widget_problem_type",
                on_change=_sync_intake_widget,
                args=("problem_type", "intake_widget_problem_type"),
            )
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
        ("Customer type", data["customer_type"]),
        ("Fake PAN ID", data["pan"]),
        ("Identity status", data["kyc"].get("status", "pending")),
        ("Identity method", data["kyc"].get("method", "Not completed")),
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
        on_change=_sync_intake_widget,
        args=("consent", "intake_widget_consent"),
    )
    st.checkbox(
        "I confirm these are fictional demonstration details. *",
        value=bool(data["declaration"]), key="intake_widget_declaration",
        on_change=_sync_intake_widget,
        args=("declaration", "intake_widget_declaration"),
    )
    st.checkbox(
        "Save as a permanent demo case",
        value=bool(data["permanent"]), key="intake_widget_permanent",
        on_change=_sync_intake_widget,
        args=("permanent", "intake_widget_permanent"),
    )


def render(store: SQLiteStore | None = None) -> None:
    """Render customer-aware intake and post-submit actions."""
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

    st.button(
        "Auto-fill synthetic example",
        key="intake_autofill_demo",
        help="Replaces current entries with fictional demo details. Consent remains unchecked.",
        on_click=_autofill_demo,
        width="stretch",
    )
    if "intake_step" not in st.session_state:
        st.session_state["intake_step"] = 0
    data = _intake()
    customers = list_intake_customers(store).to_dict("records")
    step_kinds = _step_kinds(data)
    step_names = _EXISTING_STEPS if data.get("customer_type") == "Existing customer" else _NEW_STEPS
    step = min(int(st.session_state["intake_step"]), len(step_kinds) - 1)
    st.session_state["intake_step"] = step
    step_kind = step_kinds[step]
    _render_stepper(step, step_names)
    if st.session_state.get("intake_error"):
        st.warning(st.session_state["intake_error"])
    if step_kind == "applicant":
        _render_applicant(data, customers)
    elif step_kind == "identity":
        _render_identity(data)
    elif step_kind == "employment":
        _render_employment(data)
    elif step_kind == "loan":
        _render_loan(data)
    else:
        _render_document_step(data)

    candidate = _step_data(step_kind)
    validation = _validate(candidate, step_kind)
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
        if step < len(step_kinds) - 1:
            st.button(
                "Next",
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
