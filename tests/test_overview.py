"""Portfolio analytics and high-attention navigation tests."""

from streamlit.testing.v1 import AppTest
from fpdf import FPDF
import pandas as pd
import pytest

from loanpilot.data.document_library import (
    SUMMARY_VERSION,
    format_document_upload_time,
    get_library_document,
    is_document_summary_current,
    save_uploaded_pdf,
)
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore
from loanpilot.pages import overview


def _pdf_bytes() -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(0, 10, "Lending eligibility requires verified monthly income.")
    return bytes(pdf.output())


def _insert_application(
    store: SQLiteStore,
    application_id: str,
    submitted_at: str,
    stage: str,
    *,
    ai_recommendation: str | None = None,
    human_decision: str | None = None,
    decided_at: str | None = None,
) -> None:
    customer_id = f"C-{application_id}"
    store.execute(
        """
        INSERT INTO cur_customers (
            customer_id, name, dob, age, city, employer, employment_type,
            current_tenure_months, total_experience_months, net_monthly_income,
            pan_demo_id, kyc_status, relationship_since
        ) VALUES (?, ?, '1990-01-01', 36, 'Pune', 'Employer', 'Salaried',
                  24, 60, 50000, ?, 'Verified', '2020-01-01')
        """,
        (customer_id, application_id, f"PAN-{application_id}"),
    )
    store.execute(
        """
        INSERT INTO cur_applications (
            application_id, customer_id, requested_amount, tenure_months,
            purpose, channel, submitted_at, stage
        ) VALUES (?, ?, 100000, 24, 'Personal', 'Branch', ?, ?)
        """,
        (application_id, customer_id, submitted_at, stage),
    )
    if ai_recommendation is not None or human_decision is not None:
        store.execute(
            """
            INSERT INTO cur_decisions (
                application_id, ai_recommendation, ai_reasons_json,
                human_decision, decided_at
            ) VALUES (?, ?, '{"risk_band":"Medium"}', ?, ?)
            """,
            (
                application_id,
                ai_recommendation or "Refer",
                human_decision,
                decided_at,
            ),
        )


def test_portfolio_counts_use_persisted_statuses_and_submission_month(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "portfolio.db")
    create_schema(store)
    _insert_application(
        store,
        "APP-APPROVED",
        "2025-01-15T10:00:00",
        "Sanction",
        ai_recommendation="Decline",
        human_decision="Approve",
        decided_at="2026-03-01T10:00:00",
    )
    _insert_application(
        store,
        "APP-PENDING-AI-APPROVE",
        "2025-01-20T10:00:00",
        "Human Review",
        ai_recommendation="Approve",
    )
    _insert_application(
        store,
        "APP-REJECTED",
        "2025-02-05T10:00:00",
        "Rejected",
        ai_recommendation="Approve",
        human_decision="Reject",
        decided_at="2025-02-08T10:00:00",
    )
    _insert_application(
        store,
        "APP-DOCS",
        "2025-02-10T10:00:00",
        "Awaiting documents",
        ai_recommendation="Refer",
        human_decision="Request documents",
    )
    _insert_application(
        store,
        "APP-2026",
        "2026-01-01T10:00:00",
        "Human Review",
        ai_recommendation="Approve",
    )

    records = overview._portfolio_records(store)
    monthly_2025 = overview._monthly_counts(records, 2025)
    totals_2025 = monthly_2025.groupby("status")["count"].sum().to_dict()
    january_2025 = monthly_2025.loc[monthly_2025["month"] == 1, "count"].sum()
    february_2025 = monthly_2025.loc[monthly_2025["month"] == 2, "count"].sum()
    monthly_2026 = overview._monthly_counts(records, 2026)
    totals_2026 = monthly_2026.groupby("status")["count"].sum().to_dict()

    assert records["application_id"].is_unique
    assert totals_2025 == {"Approved": 1, "Pending": 2, "Rejected": 1}
    assert january_2025 == 2
    assert february_2025 == 2
    assert totals_2026 == {"Approved": 0, "Pending": 1, "Rejected": 0}
    assert int(monthly_2025["count"].sum()) == len(records.loc[records["year"] == 2025])


def test_overview_opens_the_selected_attention_application(tmp_path, monkeypatch) -> None:
    store = SQLiteStore(tmp_path / "attention.db")
    create_schema(store)
    _insert_application(
        store,
        "APP-ATTENTION",
        "2025-06-01T10:00:00",
        "Human Review",
        ai_recommendation="Refer",
    )
    switched = []
    monkeypatch.setattr(overview.st, "switch_page", switched.append)
    app = AppTest.from_string(
        "from loanpilot.data.store import SQLiteStore\n"
        "from loanpilot.pages.overview import render\n"
        f"render(SQLiteStore({str(store.path)!r}))"
    ).run()

    assert not app.exception
    content = "\n".join(
        str(element.value)
        for name in ("markdown", "caption")
        for element in getattr(app, name, [])
    )
    assert "Stage · Human Review" in content
    assert "days pending" in content
    assert "Priority · Medium" in content
    app.button(key="overview_open_APP-ATTENTION").click().run()
    assert not app.exception
    assert app.session_state["selected_application"] == "APP-ATTENTION"
    assert len(switched) == 1


def test_overview_handles_missing_attention_fields(tmp_path, monkeypatch) -> None:
    store = SQLiteStore(tmp_path / "attention-missing-fields.db")
    create_schema(store)
    monkeypatch.setattr(
        overview,
        "overview_attention_cases",
        lambda _store: pd.DataFrame(
            [
                {
                    "applicant": float("nan"),
                    "application_id": "APP-MISSING-OPTIONAL",
                    "requested_amount": float("nan"),
                    "submitted_at": None,
                    "stage": float("nan"),
                    "ai_recommendation": float("nan"),
                    "risk_band": float("nan"),
                    "attention_priority": float("nan"),
                    "attention_reason": float("nan"),
                }
            ]
        ),
    )

    app = AppTest.from_string(
        "from loanpilot.data.store import SQLiteStore\n"
        "from loanpilot.pages.overview import render\n"
        f"render(SQLiteStore({str(store.path)!r}))"
    ).run()

    assert not app.exception
    content = "\n".join(
        str(element.value)
        for name in ("markdown", "text", "caption")
        for element in getattr(app, name, [])
    )
    assert "Stage · Unknown" in content
    assert "Requested · Unavailable" in content
    assert "Priority · Unspecified" in content
    assert "nan" not in content.casefold()


def test_latest_updates_reads_persisted_summary_and_upload_time(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "latest-updates.db")
    create_schema(store)
    document = save_uploaded_pdf(
        "income-policy.pdf",
        _pdf_bytes(),
        store,
        documents_dir=tmp_path / "library",
    )
    store.execute(
        """
        UPDATE raw_library_documents
        SET summary_status = 'Completed',
            summary_method = 'Local extractive',
            summary_headline = 'Verified income requirements',
            summary_text = 'The document requires verified income evidence. It outlines how income should be reviewed.',
            summary_version = ?
        WHERE document_id = ?
        """,
        (SUMMARY_VERSION, document["document_id"]),
    )

    app = AppTest.from_string(
        "from loanpilot.data.store import SQLiteStore\n"
        "from loanpilot.pages.overview import render\n"
        f"render(SQLiteStore({str(store.path)!r}))"
    ).run()

    assert not app.exception
    content = "\n".join(
        str(element.value)
        for name in ("markdown", "text", "caption")
        for element in getattr(app, name, [])
    )
    assert "Verified income requirements" in content
    assert "The document requires verified income evidence." in content
    assert format_document_upload_time(document["uploaded_at"]) in content
    assert "Local extractive" not in content
    assert not app.get("file_uploader")
    assert not any("Read document" in button.label for button in app.button)


def test_overview_generates_a_new_document_summary(
    tmp_path,
    monkeypatch,
) -> None:
    store = SQLiteStore(tmp_path / "overview-summary-extraction.db")
    create_schema(store)
    document = save_uploaded_pdf(
        "income-policy.pdf",
        _pdf_bytes(),
        store,
        documents_dir=tmp_path / "library",
    )
    assert document["summary_status"] == "Not requested"
    monkeypatch.setattr(
        "loanpilot.data.document_library.generate_json_with_gemini",
        lambda _prompt: {
            "headline": "Lending eligibility",
            "summary": (
                "Lending eligibility requires verified monthly income. "
                "Reviewers compare the evidence with the application."
            ),
        },
    )

    app = AppTest.from_string(
        "from loanpilot.data.store import SQLiteStore\n"
        "from loanpilot.pages.overview import render\n"
        f"render(SQLiteStore({str(store.path)!r}))"
    ).run()

    persisted = get_library_document(str(document["document_id"]), store)
    assert not app.exception
    assert persisted is not None
    assert persisted["summary_status"] == "Completed"
    assert persisted["summary_method"] == "Gemini"
    assert is_document_summary_current(persisted)
    content = "\n".join(
        str(element.value)
        for name in ("markdown", "text", "caption")
        for element in getattr(app, name, [])
    )
    assert "Lending eligibility" in content


def test_overview_uses_local_fallback_when_gemini_is_unavailable(
    tmp_path,
    monkeypatch,
) -> None:
    store = SQLiteStore(tmp_path / "overview-summary-fallback.db")
    create_schema(store)
    document = save_uploaded_pdf(
        "income-policy.pdf",
        _pdf_bytes(),
        store,
        documents_dir=tmp_path / "library",
    )
    monkeypatch.setattr(
        "loanpilot.data.document_library.generate_json_with_gemini",
        lambda _prompt: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
    )

    app = AppTest.from_string(
        "from loanpilot.data.store import SQLiteStore\n"
        "from loanpilot.pages.overview import render\n"
        f"render(SQLiteStore({str(store.path)!r}))"
    ).run()

    persisted = get_library_document(str(document["document_id"]), store)
    content = "\n".join(
        str(element.value)
        for name in ("markdown", "text", "caption")
        for element in getattr(app, name, [])
    )
    assert not app.exception
    assert persisted is not None
    assert persisted["summary_method"] == "Local extractive"
    assert "Extractive summary · local fallback" in content
    assert "Lending eligibility" in content


def test_latest_updates_refreshes_obsolete_summary_from_extracted_text(
    tmp_path,
    monkeypatch,
) -> None:
    store = SQLiteStore(tmp_path / "obsolete-summary.db")
    create_schema(store)
    document = save_uploaded_pdf(
        "old-policy.pdf",
        _pdf_bytes(),
        store,
        documents_dir=tmp_path / "library",
    )
    store.execute(
        """
        UPDATE raw_library_documents
        SET summary_status = 'Completed',
            summary_headline = 'LOANPILOT AARAMBH BANK Page 1',
            summary_text = 'LOANPILOT AARAMBH BANK FICTIONAL DEMO DOCUMENT Page 1',
        summary_version = ?
        WHERE document_id = ?
        """,
        (SUMMARY_VERSION, document["document_id"]),
    )
    monkeypatch.setattr(
        "loanpilot.data.document_library.generate_json_with_gemini",
        lambda _prompt: {
            "headline": "Lending eligibility",
            "summary": (
                "Lending eligibility requires verified monthly income. "
                "Reviewers compare the evidence with the application."
            ),
        },
    )

    app = AppTest.from_string(
        "from loanpilot.data.store import SQLiteStore\n"
        "from loanpilot.pages.overview import render\n"
        f"render(SQLiteStore({str(store.path)!r}))"
    ).run()

    content = "\n".join(
        str(element.value)
        for name in ("markdown", "text", "caption")
        for element in getattr(app, name, [])
    )
    assert not app.exception
    assert "LOANPILOT AARAMBH BANK Page 1" not in content
    assert "FICTIONAL DEMO DOCUMENT" not in content
    assert "Summary needs refreshing" not in content
    assert "Lending eligibility" in content
    refreshed = store.query(
        "SELECT summary_status, summary_method, summary_version "
        "FROM raw_library_documents WHERE document_id = ?",
        (document["document_id"],),
    ).iloc[0]
    assert refreshed.to_dict() == {
        "summary_status": "Completed",
        "summary_method": "Gemini",
        "summary_version": SUMMARY_VERSION,
    }
