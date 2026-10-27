"""Generate synthetic PDF documents for the six ready-to-run personas."""

from pathlib import Path
from typing import Any

from fpdf import FPDF

from loanpilot.config import BANK_NAME, DATA_DIR, DOCUMENTS_DIR, PROJECT_ROOT
from loanpilot.data.seed import PERSONAS
from loanpilot.data.store import SQLiteStore

_WATERMARK = "SYNTHETIC SAMPLE, DEMO ONLY"


class _DemoPDF(FPDF):
    """PDF canvas with the fictional bank header and demo watermark on each page."""

    def header(self) -> None:
        """Draw a bank header and diagonal watermark for every page."""
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(25, 65, 62)
        self.cell(
            0,
            9,
            f"{BANK_NAME} | Synthetic sample document",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.set_draw_color(15, 118, 110)
        self.line(10, 20, self.w - 10, 20)
        self.set_font("Helvetica", "B", 22)
        self.set_text_color(210, 220, 218)
        with self.rotation(45, x=self.w / 2, y=self.h / 2):
            self.text(x=22, y=self.h / 2, text=_WATERMARK)
        self.set_text_color(30, 40, 40)
        self.ln(15)


def _format_money(value: float) -> str:
    """Format a synthetic amount without relying on locale settings."""
    return f"Rs {value:,.2f}"


def _persona_document_texts(
    store: SQLiteStore, persona_key: str
) -> list[tuple[str, str, str]]:
    """Create payslip, statement-summary, and KYC text for one persona."""
    application_id = f"APP-{persona_key}"
    customer_id = f"CUST-{persona_key}"
    customer = store.query(
        "SELECT name, employer, net_monthly_income, pan_demo_id, relationship_since "
        "FROM cur_customers WHERE customer_id = ?",
        (customer_id,),
    ).iloc[0]
    transactions = store.query(
        "SELECT month, salary_credit, total_debits FROM cur_transactions "
        "WHERE customer_id = ? ORDER BY month",
        (customer_id,),
    )
    salary_avg = float(transactions["salary_credit"].mean())

    payslip_employer = (
        "Aarambh Tech Solutions Private Limited"
        if persona_key == "PERSONA-4"
        else customer["employer"]
    )
    if persona_key == "PERSONA-4":
        gross, deductions, net = 100000.0, 15000.0, 82000.0
    else:
        net = float(customer["net_monthly_income"])
        deductions = round(net * 0.18, 2)
        gross = round(net + deductions, 2)
    payslip = "\n".join(
        (
            "PERSONAL LOAN DEMO - PAYSLIP",
            f"Application: {application_id}",
            f"Employee: {customer['name']}",
            f"Employer on payslip: {payslip_employer}",
            "Pay month: September 2026",
            f"Gross pay: {_format_money(gross)}",
            f"Deductions: {_format_money(deductions)}",
            f"Net pay: {_format_money(net)}",
        )
    )

    statement_lines = [
        "PERSONAL LOAN DEMO - BANK STATEMENT SUMMARY",
        f"Application: {application_id}",
        f"Account holder: {customer['name']}",
        "Period: April 2026 to September 2026",
        f"Average monthly balance: {_format_money(_account_balance(store, customer_id))}",
    ]
    for row in transactions.to_dict("records"):
        statement_lines.append(
            f"{row['month']}: salary credit {_format_money(row['salary_credit'])}; "
            f"total debits {_format_money(row['total_debits'])}"
        )
    statement_lines.append(f"Average monthly salary credits: {_format_money(salary_avg)}")
    statement = "\n".join(statement_lines)

    aadhaar_demo_id = f"XXXX-XXXX-{int(persona_key[-1]):04d}"
    kyc = "\n".join(
        (
            "PERSONAL LOAN DEMO - KYC SUMMARY",
            f"Application: {application_id}",
            f"Applicant: {customer['name']}",
            f"PAN demo identifier: {customer['pan_demo_id']}",
            f"Aadhaar demo identifier: {aadhaar_demo_id}",
            "PAN status: Verified (simulated)",
            "KYC name match: 0.94 (simulated)",
            "CERSAI: not applicable (unsecured)",
            f"Bank relationship since: {customer['relationship_since']}",
        )
    )
    return [
        ("payslip", "Payslip", payslip),
        ("bank_statement_summary", "Bank statement summary", statement),
        ("kyc_sheet", "KYC sheet", kyc),
    ]


def _account_balance(store: SQLiteStore, customer_id: str) -> float:
    """Look up the synthetic savings balance for a persona customer."""
    return float(
        store.query(
            "SELECT avg_monthly_balance FROM cur_accounts WHERE customer_id = ?",
            (customer_id,),
        ).iloc[0, 0]
    )


def _write_pdf(path: Path, title: str, text: str) -> None:
    """Write one one-page synthetic PDF with its text content."""
    pdf = _DemoPDF()
    pdf.set_title(title)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    pdf.set_text_color(30, 40, 40)
    for line in text.splitlines():
        pdf.multi_cell(w=190, h=7, text=line)
    pdf.output(str(path))


def seed_persona_documents(store: SQLiteStore) -> int:
    """Write three synthetic PDFs per persona and register their text in RAW."""
    rows: list[tuple[Any, ...]] = []
    for persona_key in PERSONAS:
        application_id = f"APP-{persona_key}"
        folder = DOCUMENTS_DIR / application_id
        folder.mkdir(parents=True, exist_ok=True)
        submitted_at = store.query(
            "SELECT submitted_at FROM cur_applications WHERE application_id = ?",
            (application_id,),
        ).iloc[0, 0]
        for doc_type, title, text in _persona_document_texts(store, persona_key):
            filename = f"{doc_type}.pdf"
            path = folder / filename
            _write_pdf(path, title, text)
            relative_path = path.relative_to(PROJECT_ROOT).as_posix()
            rows.append(
                (
                    f"DOC-{persona_key}-{doc_type.upper()}",
                    application_id,
                    doc_type,
                    filename,
                    relative_path,
                    text,
                    submitted_at,
                )
            )
    store.execute_many(
        "INSERT INTO raw_documents "
        "(doc_id, application_id, doc_type, file_name, file_path, text_content, uploaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)


def validate_persona_documents(store: SQLiteStore) -> None:
    """Verify all generated files exist and persona four's three mismatches remain."""
    docs = store.query(
        "SELECT doc_type, file_path, text_content FROM raw_documents "
        "WHERE application_id = 'APP-PERSONA-4'"
    )
    if len(docs) != 3:
        raise ValueError("Persona 4 must have exactly three registered documents")
    for row in docs.to_dict("records"):
        path = DATA_DIR.parent / Path(row["file_path"])
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"Persona document is missing or empty: {path}")
    payslip = docs.loc[docs["doc_type"] == "payslip", "text_content"].iloc[0]
    statement = docs.loc[
        docs["doc_type"] == "bank_statement_summary", "text_content"
    ].iloc[0]
    if not all(
        phrase in payslip
        for phrase in (
            "Gross pay: Rs 100,000.00",
            "Deductions: Rs 15,000.00",
            "Net pay: Rs 82,000.00",
        )
    ):
        raise ValueError("Persona 4 payslip arithmetic inconsistency is missing")
    if "Aarambh Tech Solutions Private Limited" not in payslip:
        raise ValueError("Persona 4 employer-name inconsistency is missing")
    if "Average monthly salary credits: Rs 54,120.00" not in statement:
        raise ValueError("Persona 4 salary-credit inconsistency is missing")
