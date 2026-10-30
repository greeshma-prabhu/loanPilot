"""Persistence and idempotency tests for Overview document notifications."""

from fpdf import FPDF

from loanpilot.data.document_library import get_library_document
from loanpilot.data.notifications import (
    create_document_notification,
    list_document_notifications,
    mark_all_document_notifications_read,
    mark_document_notification_read,
    upload_and_notify_pdf,
    unread_document_notification_count,
)
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore


def _insert_document(store: SQLiteStore, document_id: str) -> None:
    store.execute(
        """
        INSERT INTO raw_library_documents (
            document_id, original_filename, uploaded_at, mime_type, size_bytes,
            processing_status, extracted_text, summary_status, summary_method,
            summary_version, summary_headline, summary_text
        ) VALUES (?, 'policy.pdf', '2026-10-29T10:00:00+00:00', 'application/pdf',
                  100, 'Processed', 'Income evidence must be verified.',
                  'Completed', 'Gemini', 3, 'Income evidence review',
                  'The policy requires verified income evidence.')
        """,
        (document_id,),
    )


def _pdf_bytes() -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(
        0,
        10,
        "Applicants must provide verified monthly income evidence. "
        "Reviewers compare declared income with supporting records.",
    )
    return bytes(pdf.output())


def test_upload_prepares_summary_and_creates_one_persistent_notification(
    tmp_path,
    monkeypatch,
) -> None:
    store = SQLiteStore(tmp_path / "upload-notification.db")
    monkeypatch.setattr(
        "loanpilot.data.document_library.generate_json_with_gemini",
        lambda _prompt: {
            "headline": "Income evidence review",
            "summary": (
                "Applicants provide verified income evidence. "
                "Reviewers compare the evidence with declared income."
            ),
        },
    )

    document = upload_and_notify_pdf(
        "income-guide.pdf",
        _pdf_bytes(),
        store,
        documents_dir=tmp_path / "library",
    )
    create_document_notification(str(document["document_id"]), store)

    persisted = get_library_document(str(document["document_id"]), SQLiteStore(store.path))
    notifications = list_document_notifications(SQLiteStore(store.path))
    assert persisted is not None
    assert persisted["summary_method"] == "Gemini"
    assert len(notifications) == 1
    assert notifications[0]["document_id"] == document["document_id"]
    assert notifications[0]["original_filename"] == "income-guide.pdf"
    assert notifications[0]["headline"] == "Income evidence review"
    assert notifications[0]["uploaded_at"] == document["uploaded_at"]
    assert notifications[0]["read_at"] is None
    assert unread_document_notification_count(store) == 1


def test_identical_pdf_upload_creates_one_library_record_and_notification(
    tmp_path,
    monkeypatch,
) -> None:
    store = SQLiteStore(tmp_path / "duplicate-notification.db")
    monkeypatch.setattr(
        "loanpilot.data.document_library.generate_json_with_gemini",
        lambda _prompt: {
            "headline": "Income evidence review",
            "summary": "The PDF describes income evidence review requirements.",
        },
    )
    content = _pdf_bytes()
    documents_dir = tmp_path / "library"

    first = upload_and_notify_pdf(
        "income-guide.pdf", content, store, documents_dir=documents_dir
    )
    second = upload_and_notify_pdf(
        "income-guide.pdf", content, store, documents_dir=documents_dir
    )

    assert second["document_id"] == first["document_id"]
    assert len(list_document_notifications(store)) == 1
    assert unread_document_notification_count(store) == 1
    assert store.query(
        "SELECT COUNT(*) AS count FROM raw_library_documents"
    ).iloc[0]["count"] == 1


def test_document_notifications_are_unique_and_persist_read_state(tmp_path) -> None:
    database_path = tmp_path / "notifications.db"
    store = SQLiteStore(database_path)
    create_schema(store)
    _insert_document(store, "document-001")

    create_document_notification("document-001", store)
    create_document_notification("document-001", store)
    assert unread_document_notification_count(store) == 1

    mark_document_notification_read("document-001", store)
    first_read_at = list_document_notifications(store)[0]["read_at"]
    mark_document_notification_read("document-001", store)

    reopened = SQLiteStore(database_path)
    notifications = list_document_notifications(reopened)
    assert len(notifications) == 1
    assert notifications[0]["document_id"] == "document-001"
    assert notifications[0]["headline"] == "Income evidence review"
    assert notifications[0]["read_at"] == first_read_at
    assert unread_document_notification_count(reopened) == 0


def test_mark_all_as_read_updates_only_existing_unread_notifications(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "notifications-all-read.db")
    create_schema(store)
    _insert_document(store, "document-001")
    _insert_document(store, "document-002")
    create_document_notification("document-001", store)
    create_document_notification("document-002", store)
    mark_document_notification_read("document-001", store)

    mark_all_document_notifications_read(store)

    notifications = list_document_notifications(store)
    assert unread_document_notification_count(store) == 0
    assert all(notification["read_at"] is not None for notification in notifications)
