"""Human-approved sanction documents and explicitly simulated disbursement."""

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from typing import Any

from fpdf import FPDF

from loanpilot.config import BANK_NAME, DATA_DIR, PROJECT_ROOT
from loanpilot.decisions import action_code_for_label, evaluate_human_action
from loanpilot.data.queries import (
    create_sanction,
    get_application,
    get_sanction,
    record_disbursement,
    update_sanction_conditions,
)
from loanpilot.data.store import SQLiteStore

PROCESSING_FEE_RATE = 0.02
DEFAULT_CONDITIONS = [
    "E-mandate registration",
    "Updated payslip",
    "Employer confirmation",
]


def reducing_balance_emi(amount: float, annual_rate: float, months: int) -> float:
    """Calculate the monthly reducing-balance payment."""
    if amount <= 0 or months <= 0 or annual_rate < 0:
        raise ValueError("Amount and tenure must be positive and rate cannot be negative.")
    monthly_rate = annual_rate / 12
    if monthly_rate == 0:
        return amount / months
    factor = (1 + monthly_rate) ** months
    return amount * monthly_rate * factor / (factor - 1)


def modified_terms_preview(
    amount: float,
    tenure_months: int,
    annual_rate: float,
    existing_emi: float,
    verified_income: float,
) -> dict[str, Any]:
    """Recalculate modified EMI and FOIR using observed verified income."""
    emi = reducing_balance_emi(amount, annual_rate, tenure_months)
    foir = (
        (existing_emi + emi) / verified_income if verified_income > 0 else None
    )
    return {
        "amount": amount,
        "tenure_months": tenure_months,
        "rate": annual_rate,
        "emi": emi,
        "foir_verified": foir,
        "foir_over_limit": foir is not None and foir > 0.45,
    }


def _apr_from_cashflows(
    net_amount: float, emi: float, months: int
) -> float:
    """Estimate effective annual APR from net proceeds and level repayments."""
    if net_amount <= 0:
        raise ValueError("Net proceeds must be positive to calculate APR.")
    low, high = 0.0, 1.0
    for _ in range(100):
        monthly_rate = (low + high) / 2
        factor = (1 + monthly_rate) ** months
        present_value = emi * (factor - 1) / (monthly_rate * factor) if monthly_rate else emi * months
        if present_value > net_amount:
            low = monthly_rate
        else:
            high = monthly_rate
    return (1 + (low + high) / 2) ** 12 - 1


def build_key_fact_statement(
    amount: float,
    tenure_months: int,
    annual_rate: float,
    emi: float,
) -> dict[str, Any]:
    """Build an illustrative KFS preview, not a compliance determination."""
    fee = round(amount * PROCESSING_FEE_RATE, 2)
    net_disbursed = round(amount - fee, 2)
    total_interest = round(emi * tenure_months - amount, 2)
    total_payable = round(emi * tenure_months + fee, 2)
    return {
        "label": "Illustrative; verify against the official RBI Digital Lending Guidelines",
        "loan_amount": round(amount, 2),
        "annual_rate": annual_rate,
        "apr": _apr_from_cashflows(net_disbursed, emi, tenure_months),
        "emi": round(emi, 2),
        "tenure_months": tenure_months,
        "processing_fee": fee,
        "fee_basis": "Illustrative 2% of approved amount",
        "net_disbursed": net_disbursed,
        "total_interest": total_interest,
        "total_amount_payable": total_payable,
        "repayment_schedule_summary": {
            "installments": tenure_months,
            "monthly_installment": round(emi, 2),
            "first_installment_estimate": round(emi, 2),
            "last_installment_estimate": round(emi, 2),
        },
        "grievance_contact": "demo-grievance@aarambh.example",
        "cooling_off_note": (
            "Illustrative demo note: applicable cooling-off terms should be confirmed "
            "and disclosed by the responsible lender."
        ),
    }


class _SanctionPDF(FPDF):
    """One-page synthetic sanction letter with a diagonal watermark."""

    def __init__(self) -> None:
        super().__init__()
        self.set_auto_page_break(auto=True, margin=18)

    def header(self) -> None:
        """Print fictional bank header and the demo-only watermark."""
        self.set_font("Helvetica", "B", 15)
        self.cell(0, 9, BANK_NAME, new_x="LMARGIN", new_y="NEXT", align="C")
        self.set_font("Helvetica", "", 10)
        self.cell(
            0,
            6,
            "Synthetic personal loan sanction letter",
            new_x="LMARGIN",
            new_y="NEXT",
            align="C",
        )
        with self.rotation(45, x=self.w / 2, y=self.h / 2):
            self.set_text_color(220, 220, 220)
            self.set_font("Helvetica", "B", 30)
            self.text(22, self.h / 2, "SYNTHETIC SAMPLE, DEMO ONLY")
        self.set_text_color(0, 0, 0)
        self.ln(10)


def generate_sanction_letter(
    application_id: str,
    sanction_ref: str,
    amount: float,
    tenure_months: int,
    annual_rate: float,
    emi: float,
    conditions: list[dict[str, Any]],
) -> Path:
    """Create the synthetic sanction PDF beneath the configured project data path."""
    path = DATA_DIR / "sanctions" / f"{application_id}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = _SanctionPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 7, f"Application: {application_id}\nSanction reference: {sanction_ref}")
    pdf.ln(3)
    lines = [
        f"Approved amount: Rs {amount:,.2f}",
        f"Tenure: {tenure_months} months",
        f"Annual reducing-balance rate: {annual_rate:.2%}",
        f"Indicative monthly EMI: Rs {emi:,.2f}",
        "Conditions:",
    ]
    lines.extend(
        f"- {item['name']}" for item in conditions if item.get("required", True)
    )
    if not conditions:
        lines.append("- None")
    lines.extend(
        [
            "",
            "This is a synthetic demonstration document, not a real offer.",
            "Sanction is subject to completion of applicable conditions.",
        ]
    )
    pdf.multi_cell(0, 7, "\n".join(lines))
    pdf.output(str(path))
    return path


def approve_and_sanction(
    application_id: str,
    approved_amount: float,
    tenure_months: int,
    rate: float,
    reason: str,
    reviewer: str,
    *,
    conditions: list[str] | None = None,
    decision_action: str | None = None,
    store: SQLiteStore | None = None,
) -> dict[str, Any]:
    """Record a human approval and create its sanction and KFS artifacts."""
    store = store or SQLiteStore()
    application = get_application(application_id, store)
    if application.empty:
        raise ValueError(f"Unknown application: {application_id}")
    app = application.iloc[0]
    if app["stage"] != "Human Review":
        raise ValueError("Only a case in Human Review can be approved.")
    ai_decision = app["ai_recommendation"]
    decision = decision_action or (
        "Approve with conditions" if conditions else "Approve"
    )
    if decision not in {"Approve", "Approve with conditions", "Modify terms"}:
        raise ValueError(f"Unsupported approval action: {decision}")
    override = evaluate_human_action(
        ai_decision,
        action_code_for_label(decision),
    ).is_override
    now = datetime.now().isoformat(timespec="seconds")
    from loanpilot.data.queries import record_human_decision

    checklist = [
        {"name": name, "required": True, "complete": False}
        for name in (conditions or [])
    ]
    emi = reducing_balance_emi(approved_amount, rate, tenure_months)
    kfs = build_key_fact_statement(approved_amount, tenure_months, rate, emi)
    sanction_ref = f"SAN-{uuid4().hex[:12].upper()}"
    letter = generate_sanction_letter(
        application_id,
        sanction_ref,
        approved_amount,
        tenure_months,
        rate,
        emi,
        checklist,
    )
    record_human_decision(
        application_id,
        decision,
        reason,
        override,
        reviewer,
        now,
        "Sanction",
        store,
    )
    create_sanction(
        application_id,
        sanction_ref,
        approved_amount,
        tenure_months,
        rate,
        emi,
        json.dumps(checklist, sort_keys=True),
        str(letter.relative_to(PROJECT_ROOT)),
        json.dumps(kfs, sort_keys=True),
        now,
        store,
    )
    return {
        "application_id": application_id,
        "sanction_ref": sanction_ref,
        "approved_amount": approved_amount,
        "tenure_months": tenure_months,
        "rate": rate,
        "emi": emi,
        "conditions": checklist,
        "letter_path": letter,
        "kfs": kfs,
        "override": override,
    }


def update_conditions(
    application_id: str,
    conditions: list[dict[str, Any]],
    reviewer: str,
    store: SQLiteStore | None = None,
) -> None:
    """Persist checked condition states before simulated disbursement."""
    update_sanction_conditions(
        application_id,
        json.dumps(conditions, sort_keys=True),
        datetime.now().isoformat(timespec="seconds"),
        reviewer,
        store,
    )


def run_simulated_disbursement(
    application_id: str,
    store: SQLiteStore | None = None,
) -> dict[str, Any]:
    """Create a simulated disbursement after all conditions have been checked."""
    store = store or SQLiteStore()
    sanctions = get_sanction(application_id, store)
    if sanctions.empty:
        raise ValueError("A human sanction is required before disbursement.")
    sanction = sanctions.iloc[0]
    conditions = json.loads(sanction["conditions_json"])
    if any(not item.get("complete", False) for item in conditions):
        raise ValueError("Complete all sanction conditions before disbursement.")
    kfs = json.loads(sanction["kfs_json"])
    gross = float(sanction["approved_amount"])
    fees = float(kfs["processing_fee"])
    net = round(gross - fees, 2)
    now = datetime.now().isoformat(timespec="seconds")
    reference = f"SIM-{uuid4().hex[:12].upper()}"
    record_disbursement(
        application_id,
        reference,
        gross,
        fees,
        net,
        now,
        store,
    )
    return {
        "application_id": application_id,
        "disbursement_ref": reference,
        "gross_amount": gross,
        "fees": fees,
        "net_amount": net,
        "disbursed_at": now,
        "mode": "simulated",
    }
