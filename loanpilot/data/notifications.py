"""Persistent document notifications for the Overview workspace."""

from datetime import datetime, timezone
from pathlib import Path

from loanpilot.data.document_library import (
    DocumentNotFoundError,
    ensure_library_content_hashes,
    get_library_document,
    is_document_summary_current,
    save_uploaded_pdf,
    summarize_library_document,
)
from loanpilot.config import DOCUMENT_LIBRARY_DIR
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore

_NO_TEXT_SUMMARY = (
    "No readable text could be extracted from this PDF, so a summary is unavailable."
)
_SUMMARY_UNAVAILABLE = (
    "A concise summary could not be prepared from the available document text."
)


def upload_and_notify_pdf(
    filename: str,
    content: bytes | bytearray | memoryview,
    store: SQLiteStore,
    *,
    documents_dir: Path = DOCUMENT_LIBRARY_DIR,
) -> dict[str, object]:
    """Persist an uploaded PDF, prepare its summary, and create its one notification."""
    document = save_uploaded_pdf(
        filename,
        content,
        store,
        documents_dir=documents_dir,
    )
    document_id = str(document["document_id"])
    if document["processing_status"] == "Processed":
        document = summarize_library_document(document_id, store)
    create_document_notification(document_id, store)
    return document


def create_document_notification(
    document_id: str,
    store: SQLiteStore,
) -> None:
    """Create at most one notification for a saved document."""
    create_schema(store)
    document = get_library_document(document_id, store)
    if document is None:
        raise DocumentNotFoundError("The uploaded document is no longer available.")

    if is_document_summary_current(document):
        headline = str(document["summary_headline"])
        summary = str(document["summary_text"])
    elif (
        not str(document.get("extracted_text") or "").strip()
        or "no meaningful selectable text" in str(
            document.get("summary_error") or ""
        ).casefold()
        or "ocr-readable pdf" in str(document.get("summary_error") or "").casefold()
    ):
        headline = "Document uploaded · summary unavailable"
        summary = _NO_TEXT_SUMMARY
    else:
        headline = "Document uploaded · summary unavailable"
        summary = _SUMMARY_UNAVAILABLE

    store.execute(
        """
        INSERT INTO raw_document_notifications (
            document_id, headline, summary, uploaded_at, read_at
        ) VALUES (?, ?, ?, ?, NULL)
        ON CONFLICT(document_id) DO NOTHING
        """,
        (
            document_id,
            headline[:160],
            summary[:1800],
            str(document["uploaded_at"]),
        ),
    )


def list_document_notifications(store: SQLiteStore) -> list[dict[str, object]]:
    """Return saved document notifications newest first."""
    create_schema(store)
    ensure_library_content_hashes(store)
    rows = store.query(
        """
        SELECT n.document_id, d.original_filename, n.headline, n.summary,
               n.uploaded_at, n.read_at, d.content_sha256
        FROM raw_document_notifications n
        JOIN raw_library_documents d ON d.document_id = n.document_id
        ORDER BY n.uploaded_at DESC, n.document_id DESC
        """
    )
    notifications = rows.to_dict("records")
    unique_notifications = []
    seen_content = set()
    for notification in notifications:
        content_hash = notification.get("content_sha256")
        key = str(content_hash) if content_hash else str(notification["document_id"])
        if key in seen_content:
            continue
        seen_content.add(key)
        unique_notifications.append(notification)
    return unique_notifications


def unread_document_notification_count(store: SQLiteStore) -> int:
    """Count persisted notifications that have not been opened."""
    return sum(
        notification.get("read_at") is None
        for notification in list_document_notifications(store)
    )


def mark_document_notification_read(
    document_id: str,
    store: SQLiteStore,
) -> None:
    """Persist the first read timestamp without changing an existing one."""
    create_schema(store)
    store.execute(
        """
        UPDATE raw_document_notifications
        SET read_at = ?
        WHERE document_id = ? AND read_at IS NULL
        """,
        (datetime.now(timezone.utc).isoformat(timespec="microseconds"), document_id),
    )


def mark_all_document_notifications_read(store: SQLiteStore) -> None:
    """Persist one read timestamp for all currently unread notifications."""
    create_schema(store)
    store.execute(
        """
        UPDATE raw_document_notifications
        SET read_at = ?
        WHERE read_at IS NULL
        """,
        (datetime.now(timezone.utc).isoformat(timespec="microseconds"),),
    )


def format_relative_upload_time(value: object) -> str:
    """Format an upload timestamp as a concise relative time in the UI."""
    try:
        uploaded_at = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return "Upload time unavailable"
    if uploaded_at.tzinfo is None:
        uploaded_at = uploaded_at.replace(tzinfo=timezone.utc)
    seconds = max(
        0,
        int((datetime.now(timezone.utc) - uploaded_at.astimezone(timezone.utc)).total_seconds()),
    )
    if seconds < 60:
        return "Just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago"
    hours = seconds // 3600
    if hours < 24:
        return f"{hours} hr ago"
    days = seconds // 86400
    if days == 1:
        return "Yesterday"
    if days < 30:
        return f"{days} days ago"
    months = days // 30
    if months < 12:
        return f"{months} mo ago"
    years = days // 365
    return f"{years} yr ago"
