"""Grounded document extraction, checks, persistence, and assessment linkage."""

from datetime import datetime

import pytest
from fpdf import FPDF
from streamlit.testing.v1 import AppTest

from loanpilot.agent.orchestrator import run_assessment
from loanpilot.data.document_verification import analyze_uploads
from loanpilot.data.queries import (
    create_intake_application,
    get_document_verification_report,
    get_document_verifications,
)
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore


def _pdf(text: str = "") -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    if text:
        pdf.multi_cell(0, 8, text)
    return bytes(pdf.output())


def _uploads(
    *,
    name: str = "Priya Shah",
    employer: str = "Aarambh Demo Services",
    net: int = 50000,
    credits: int = 50000,
) -> list[dict]:
    return [
        {
            "file_name": "identity.pdf",
            "category": "identity_proof",
            "content": _pdf(
                f"Document type: PAN\nName: {name}\nPAN demo identifier: DEMO123456"
            ),
        },
        {
            "file_name": "salary.pdf",
            "category": "payslip",
            "content": _pdf(
                f"Employee: {name}\nEmployer: {employer}\nPay month: September 2026\n"
                f"Gross pay: Rs {net + 10000:,.2f}\nDeductions: Rs 10,000.00\n"
                f"Net pay: Rs {net:,.2f}\nEmployee ID: EMP-123"
            ),
        },
        {
            "file_name": "statement.pdf",
            "category": "bank_statement_summary",
            "content": _pdf(
                f"Account holder: {name}\nBank name: Demo Bank\n"
                "Period: April 2026 to September 2026\n"
                f"Average monthly salary credits: Rs {credits:,.2f}"
            ),
        },
    ]


def _salary_bank_uploads(
    *,
    salary_name: str = "Priya Shah",
    bank_name: str = "Priya Shah",
    net: int = 50000,
    credits: tuple[int, ...] = (50000, 50000),
) -> list[dict]:
    transaction_lines = "\n".join(
        f"2026-{index + 3:02d}-01 NEFT SALARY credit Rs {amount:,.2f} CR"
        for index, amount in enumerate(credits)
    )
    average = sum(credits) / len(credits) if credits else 0
    return [
        {
            "file_name": "salary.pdf",
            "category": "salary_slip",
            "content": _pdf(
                f"Employee name: {salary_name}\nEmployer: Aarambh Demo Services\n"
                f"Net salary: Rs {net:,.2f}"
            ),
        },
        {
            "file_name": "statement.pdf",
            "category": "bank_statement",
            "content": _pdf(
                f"Account holder: {bank_name}\n"
                "Period: April 2026 to September 2026\n"
                f"{transaction_lines}\n"
                f"Average monthly salary credits: Rs {average:,.2f}"
            ),
        },
    ]


def _local_extraction(monkeypatch) -> None:
    """Keep these tests deterministic and exercise the no-key fallback."""
    from loanpilot.data import document_verification

    def unavailable(_prompt):
        raise RuntimeError("Gemini is not configured.")

    monkeypatch.setattr(document_verification, "generate_json_with_gemini", unavailable)


def test_text_pdfs_are_extracted_and_consistent_values_are_grounded(monkeypatch) -> None:
    _local_extraction(monkeypatch)
    documents, report = analyze_uploads(
        _uploads(),
        {"name": "Priya Shah", "employer": "Aarambh Demo Services", "income": 50000},
    )

    assert len(documents) == 3
    assert documents[1]["extracted_fields"]["net_salary"] == 50000
    assert documents[1]["field_evidence"]["net_salary"] == "Net pay: Rs 50,000.00"
    assert report["overall_status"] == "Verified / Consistent"
    assert report["authenticity_status"] == "Not independently verified"
    assert any(check["check"] == "Payslip vs salary credits" for check in report["checks"])


def test_mismatched_names_employers_and_salary_require_review(monkeypatch) -> None:
    _local_extraction(monkeypatch)
    documents, report = analyze_uploads(
        _uploads(name="Wrong Applicant", employer="Different Employer", net=65000, credits=40000),
        {"name": "Priya Shah", "employer": "Aarambh Demo Services", "income": 50000},
    )

    assert report["overall_status"] == "Needs manual review"
    statuses = {
        check["check"]: check["status"]
        for document in documents
        for check in document["checks"]
    }
    assert statuses["Applicant name"] == "Mismatch"
    assert statuses["Employer name"] == "Mismatch"
    assert statuses["Net salary vs declared income"] == "Mismatch"


def test_missing_required_documents_are_reported(monkeypatch) -> None:
    _local_extraction(monkeypatch)
    documents, report = analyze_uploads(
        _uploads()[:1],
        {"name": "Priya Shah", "employer": "Aarambh Demo Services", "income": 50000},
    )

    assert len(documents) == 1
    assert report["overall_status"] == "Incomplete"
    assert set(report["missing_categories"]) == {"payslip", "bank_statement_summary"}


def test_statement_gaps_and_employment_duration_are_compared(monkeypatch) -> None:
    _local_extraction(monkeypatch)
    statement = _pdf(
        "Account holder: Priya Shah\nPeriod: April 2026 to September 2026\n"
        "2026-04: salary credit Rs 50,000.00\n"
        "2026-06: salary credit Rs 50,000.00"
    )
    employment = _pdf(
        "Employee: Priya Shah\nEmployer: Aarambh Demo Services\n"
        "Joining date: 2022-01-01\nEmployment status: Active"
    )
    documents, _ = analyze_uploads(
        [
            {"file_name": "statement.pdf", "category": "bank_statement_summary", "content": statement},
            {"file_name": "employment.pdf", "category": "employment_proof", "content": employment},
        ],
        {
            "name": "Priya Shah",
            "employer": "Aarambh Demo Services",
            "income": 50000,
            "job_months": 12,
        },
    )

    statement_check = next(
        check
        for check in documents[0]["checks"]
        if check["check"] == "Salary credit months in statement period"
    )
    duration_check = next(
        check
        for check in documents[1]["checks"]
        if check["check"] == "Employment duration"
    )
    assert statement_check["status"] == "Missing information"
    assert duration_check["status"] == "Mismatch"


def test_document_step_renders_both_modes_and_empty_upload_report(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "intake-ui.db")
    create_schema(store)
    app = AppTest.from_string(
        "import streamlit as st\n"
        "from loanpilot.pages.new_application import _initial_intake, render\n"
        "from loanpilot.data.store import SQLiteStore\n"
        "st.session_state['intake'] = _initial_intake()\n"
        "st.session_state['intake_step'] = 4\n"
        f"render(SQLiteStore({str(store.path)!r}))\n"
    ).run()

    assert not app.exception
    assert app.button(key="intake_select_demo_documents")
    assert app.button(key="intake_select_upload_documents")
    for doc_type in ("payslip", "bank_statement_summary", "kyc_sheet", "employment_proof"):
        assert any(
            element.key == f"intake_download_{doc_type}"
            for element in app.get("download_button")
        )
    app.button(key="intake_select_upload_documents").click().run()
    assert not app.exception
    uploaders = {element.key for element in app.get("file_uploader")}
    assert "intake_salary_slip_pdf" in uploaders
    assert "intake_bank_statement_pdf" in uploaders
    assert not any(
        getattr(element, "key", None) == "intake_analyze_documents"
        for element in app.button
    )
    assert not any("Identity proof" in element.value for element in app.info)


def test_intake_persists_salary_documents_with_fixed_categories(
    tmp_path, monkeypatch
) -> None:
    from loanpilot import config
    from loanpilot.pages.new_application import _DOCUMENT_MODES, _save_documents

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "DOCUMENTS_DIR", tmp_path / "documents")
    uploads = _salary_bank_uploads()
    documents = _save_documents(
        "APP-DOC-CATEGORY-TEST",
        {"document_mode": _DOCUMENT_MODES[1], "uploads": uploads},
    )

    assert [document["category"] for document in documents] == [
        "salary_slip",
        "bank_statement",
    ]
    assert [document["doc_type"] for document in documents] == [
        "salary_slip",
        "bank_statement",
    ]
    for upload, document in zip(uploads, documents):
        stored = tmp_path / document["file_path"]
        assert stored.read_bytes() == upload["content"]
        assert document["text_content"] == ""


@pytest.mark.parametrize(
    ("salary_name", "bank_name", "net", "credits", "expected", "difference"),
    [
        ("Priya Shah", "Priya Shah", 50000, (50000, 50000), "MATCH", 0),
        ("Priya Shah", "Priya Shah", 60000, (40000, 40000), "MISMATCH", 20000),
        ("Priya Shah", "Riya Shah", 50000, (50000, 50000), "MISMATCH", 0),
    ],
)
def test_salary_statement_comparison_status_and_monthly_credit_average(
    monkeypatch, salary_name, bank_name, net, credits, expected, difference
) -> None:
    _local_extraction(monkeypatch)
    documents, report = analyze_uploads(
        _salary_bank_uploads(
            salary_name=salary_name,
            bank_name=bank_name,
            net=net,
            credits=credits,
        ),
        {"name": "Priya Shah", "employer": "Aarambh Demo Services", "income": 50000},
        required_categories=("salary_slip", "bank_statement"),
    )

    verification = report["salary_statement_verification"]
    assert verification["status"] == expected
    assert verification["difference"] == difference
    assert verification["bank_statement_average_monthly_salary_credit"] == sum(
        credits
    ) / len(credits)
    assert len(verification["bank_statement_salary_credits"]) == len(credits)
    assert report["missing_categories"] == []
    assert "Salary Slip vs Bank Statement Verification" not in report["explanation"]
    assert documents[1]["category"] == "bank_statement"


def test_non_salary_bank_credits_are_not_counted_as_salary(monkeypatch) -> None:
    _local_extraction(monkeypatch)
    documents, report = analyze_uploads(
        [
            _salary_bank_uploads()[0],
            {
                "file_name": "statement.pdf",
                "category": "bank_statement",
                "content": _pdf(
                    "Account holder: Priya Shah\n"
                    "2026-03-01 NEFT SALARY credit Rs 50,000.00 CR\n"
                    "2026-04-01 Refund credit Rs 100,000.00 CR"
                ),
            },
        ],
        {"name": "Priya Shah"},
        required_categories=("salary_slip", "bank_statement"),
    )

    verification = report["salary_statement_verification"]
    assert verification["status"] == "MATCH"
    assert [item["amount"] for item in verification["bank_statement_salary_credits"]] == [
        50000
    ]


@pytest.mark.parametrize(
    ("uploads", "missing"),
    [
        (_salary_bank_uploads()[1:], "salary_slip"),
        (_salary_bank_uploads()[:1], "bank_statement"),
        (
            [
                _salary_bank_uploads()[0],
                {
                    **_salary_bank_uploads()[1],
                    "content": b"",
                },
            ],
            None,
        ),
    ],
)
def test_missing_or_unreadable_salary_documents_are_inconclusive(
    monkeypatch, uploads, missing
) -> None:
    _local_extraction(monkeypatch)
    _documents, report = analyze_uploads(
        uploads,
        {"name": "Priya Shah", "income": 50000},
        required_categories=("salary_slip", "bank_statement"),
    )
    verification = report["salary_statement_verification"]
    assert verification["status"] == "INCONCLUSIVE"
    if missing:
        assert missing in report["missing_categories"]


def test_assessment_extracts_persists_and_reuses_uploaded_salary_documents(
    tmp_path, monkeypatch
) -> None:
    _local_extraction(monkeypatch)
    from loanpilot.agent import tools

    monkeypatch.setattr(tools, "PROJECT_ROOT", tmp_path)
    store = SQLiteStore(tmp_path / "assessment-time-documents.db")
    create_schema(store)
    records = []
    for upload in _salary_bank_uploads(net=65000, credits=(40000, 40000)):
        relative_path = f"data/documents/case/{upload['file_name']}"
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(upload["content"])
        records.append(
            {
                "doc_type": upload["category"],
                "category": upload["category"],
                "file_name": upload["file_name"],
                "file_path": relative_path,
                "text_content": "",
            }
        )

    application_id = create_intake_application(
        {
            "name": "Priya Shah",
            "dob": "1990-01-01",
            "age": 36,
            "city": "Pune",
            "mobile": "9000000000",
            "employer": "Aarambh Demo Services",
            "employment_type": "Salaried",
            "current_tenure_months": 24,
            "total_experience_months": 60,
            "net_monthly_income": 50000,
            "existing_emi": 0,
            "pan_demo_id": "DEMO123456",
        },
        {
            "requested_amount": 100000,
            "tenure_months": 60,
            "purpose": "Education",
            "submitted_at": datetime.now().isoformat(timespec="seconds"),
        },
        {"score": 800, "thin_file": False, "enquiries_6m": 0},
        {"status": "verified", "name_match": 1.0},
        records,
        store,
        application_id="APP-ASSESSMENT-DOC-TEST",
    )

    assessment = run_assessment(application_id, store)
    report = get_document_verification_report(application_id, store)
    assert report["salary_statement_verification"]["status"] == "MISMATCH"
    assert report["salary_statement_verification"]["difference"] == 25000
    assert len(get_document_verifications(application_id, store)) == 2
    assert assessment["reconciliation"]["salary_statement_status"] == "MISMATCH"
    clause = next(
        row for row in assessment["policy"]["clauses"] if row["clause_id"] == "CP-6.2"
    )
    assert clause["status"] == "refer"
    assert assessment["recommendation"] != "Decline"

    run_assessment(application_id, store)
    assert len(get_document_verifications(application_id, store)) == 2


def test_generated_demo_documents_are_watermarked_and_not_verified() -> None:
    from loanpilot.data.document_verification import synthetic_verification_report
    from loanpilot.pages.new_application import (
        _DEMO_DOCUMENT_TYPES,
        _DOC_LABELS,
        _document_texts,
        _initial_intake,
        _pdf_bytes,
    )
    from loanpilot.data.document_verification import extract_pdf_text

    data = _initial_intake()
    data.update(
        {
            "name": "Synthetic Applicant",
            "employer": "Demo Employer",
            "document_problem": False,
        }
    )
    texts = _document_texts(data)
    generated = [
        _pdf_bytes(_DOC_LABELS[key], texts[key].splitlines())
        for key in _DEMO_DOCUMENT_TYPES
    ]
    assert len(generated) == 4
    for content in generated:
        extracted, status, _message = extract_pdf_text(content)
        assert status == "Readable"
        assert "SYNTHETIC SAMPLE, DEMO ONLY" in extracted

    report = synthetic_verification_report(
        [{"file_name": f"{key}.pdf"} for key in _DEMO_DOCUMENT_TYPES]
    )
    assert report["overall_status"] == "Synthetic demo documents"
    assert report["authenticity_status"] == "Not independently verified"


def test_invalid_empty_scanned_and_duplicate_files_are_handled(
    monkeypatch,
) -> None:
    _local_extraction(monkeypatch)
    from loanpilot.data import document_verification

    with pytest.raises(ValueError, match="10 MB"):
        analyze_uploads(
            [
                {
                    "file_name": "too-large.pdf",
                    "category": "payslip",
                    "content": b"%PDF-" + b"0" * document_verification.MAX_PDF_BYTES,
                }
            ],
            {},
        )
    monkeypatch.setattr(
        document_verification,
        "_ocr_pdf",
        lambda _content: ("", "OCR is unavailable; install optional OCR tools."),
    )
    with pytest.raises(ValueError, match="only PDF"):
        analyze_uploads(
            [{"file_name": "bad.txt", "category": "payslip", "content": b"not pdf"}],
            {},
        )

    empty_docs, empty_report = analyze_uploads(
        [{"file_name": "empty.pdf", "category": "payslip", "content": b""}],
        {},
    )
    assert empty_docs[0]["extraction_status"] == "Unreadable"
    assert empty_report["overall_status"] == "Needs manual review"

    scan = _pdf()
    monkeypatch.setattr(
        document_verification,
        "_ocr_pdf",
        lambda _content: ("Employee: Priya Shah", None),
    )
    scan_docs, _ = analyze_uploads(
        [{"file_name": "scan.pdf", "category": "payslip", "content": scan}],
        {"name": "Priya Shah", "employer": "", "income": 50000},
    )
    assert scan_docs[0]["extraction_status"] == "Readable (OCR)"

    duplicate_docs, _ = analyze_uploads(
        [
            {"file_name": "first.pdf", "category": "payslip", "content": scan},
            {"file_name": "copy.pdf", "category": "payslip", "content": scan},
        ],
        {},
    )
    assert duplicate_docs[1]["duplicate_of"] == "first.pdf"
    duplicate_check = next(
        check
        for check in duplicate_docs[1]["checks"]
        if check["check"] == "Duplicate document"
    )
    assert duplicate_check["status"] == "Needs manual review"
