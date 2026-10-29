"""Portfolio analytics and high-attention navigation tests."""

from streamlit.testing.v1 import AppTest
from fpdf import FPDF
import pandas as pd
import pytest

from loanpilot.data.document_library import (
    SUMMARY_VERSION,
    format_document_upload_time,
    get_library_document,
    save_uploaded_pdf,
    summarize_library_document,
)
from loanpilot.data.notifications import (
    create_document_notification,
    list_document_notifications,
    unread_document_notification_count,
)
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore
from loanpilot.pages import overview


def _pdf_bytes(text: str = "Lending eligibility requires verified monthly income.") -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(0, 10, text)
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


def test_overview_does_not_generate_summaries_or_notifications_for_old_documents(
    tmp_path,
    monkeypatch,
) -> None:
    store = SQLiteStore(tmp_path / "overview-existing-document.db")
    create_schema(store)
    document = save_uploaded_pdf(
        "income-policy.pdf",
        _pdf_bytes(),
        store,
        documents_dir=tmp_path / "library",
    )
    gemini_calls = []
    monkeypatch.setattr(
        "loanpilot.data.document_library.generate_json_with_gemini",
        lambda prompt: gemini_calls.append(prompt),
    )

    app = AppTest.from_string(
        "from loanpilot.data.store import SQLiteStore\n"
        "from loanpilot.pages.overview import render\n"
        f"render(SQLiteStore({str(store.path)!r}))"
    ).run()

    persisted = get_library_document(str(document["document_id"]), store)
    content = "\n".join(
        str(element.value)
        for name in ("title", "header", "subheader", "caption", "markdown", "text")
        for element in getattr(app, name, [])
    )
    assert not app.exception
    assert persisted is not None
    assert persisted["summary_status"] == "Not requested"
    assert not gemini_calls
    assert list_document_notifications(store) == []
    assert "Latest Updates" not in content
    assert unread_document_notification_count(store) == 0


def test_overview_notification_panel_expands_summary_and_marks_read(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "overview-notification.db")
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
            summary_method = 'Gemini',
            summary_headline = 'Verified income requirements',
            summary_text = 'The document requires verified income evidence. Reviewers compare declared income with supporting records.',
            summary_version = ?
        WHERE document_id = ?
        """,
        (SUMMARY_VERSION, document["document_id"]),
    )
    second_document = save_uploaded_pdf(
            "review-guide.pdf",
            _pdf_bytes("Reviewers compare declared income with supporting records."),
            store,
            documents_dir=tmp_path / "library",
    )
    store.execute(
            """
            UPDATE raw_library_documents
            SET summary_status = 'Completed',
                summary_method = 'Gemini',
                summary_headline = 'Income review steps',
                summary_text = 'Reviewers compare declared income with supporting records.',
                summary_version = ?
            WHERE document_id = ?
            """,
            (SUMMARY_VERSION, second_document["document_id"]),
    )
    create_document_notification(str(document["document_id"]), store)
    create_document_notification(str(second_document["document_id"]), store)

    app = AppTest.from_string(
        "from loanpilot.data.store import SQLiteStore\n"
        "from loanpilot.pages.overview import render\n"
        f"render(SQLiteStore({str(store.path)!r}))"
    ).run()

    assert not app.exception
    assert unread_document_notification_count(store) == 2
    app.button(key="overview_notification_toggle").click().run()
    assert app.session_state["overview_notifications_open"] is True
    assert app.button(key="overview_notifications_close")
    app.button(key="overview_notifications_mark_all_read").click().run()
    assert not app.exception
    assert unread_document_notification_count(store) == 0
    assert app.button(key="overview_notification_toggle").label == ""
    app.button(key="overview_notifications_close").click().run()
    assert not app.exception
    assert app.session_state["overview_notifications_open"] is False
    assert not any(
        button.key == "overview_notifications_close"
        for button in app.button
    )
    app.button(key="overview_notification_toggle").click().run()
    assert app.button(key=f"overview_notification_expand_{document['document_id']}")
    app.button(key=f"overview_notification_expand_{document['document_id']}").click().run()

    assert not app.exception
    assert unread_document_notification_count(store) == 0
    assert app.session_state[f"overview_notification_expanded_{document['document_id']}"]
    assert app.button(key=f"overview_notification_collapse_{document['document_id']}")
    visible_text = "\n".join(str(element.value) for element in app.markdown)
    assert "Reviewers compare declared income with supporting records." in visible_text
    assert "income-policy.pdf" in "\n".join(
        str(element.value) for element in app.caption
    )
    assert format_document_upload_time(document["uploaded_at"]) in "\n".join(
        str(element.value) for element in app.caption
    )


def test_overview_handles_an_unreadable_document_notification_without_inventing_summary(
    tmp_path,
) -> None:
    store = SQLiteStore(tmp_path / "overview-unreadable-notification.db")
    create_schema(store)
    document = save_uploaded_pdf(
        "scanned.pdf",
        _pdf_bytes("Page 1"),
        store,
        documents_dir=tmp_path / "library",
    )
    summarize_library_document(str(document["document_id"]), store)
    create_document_notification(str(document["document_id"]), store)
    notification = list_document_notifications(store)[0]

    assert notification["headline"] == "Document uploaded · summary unavailable"
    assert "No readable text could be extracted" in notification["summary"]
    assert notification["read_at"] is None
