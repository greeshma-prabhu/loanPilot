"""Persistence, retrieval, and confirmation tests for reference PDFs."""

from pathlib import Path

from fpdf import FPDF
import pytest
from streamlit.testing.v1 import AppTest
from streamlit.proto.Common_pb2 import FileURLs
from streamlit.runtime.uploaded_file_manager import UploadedFile, UploadedFileRec

from loanpilot.data import document_library
from loanpilot.data.document_library import (
    MAX_DOCUMENT_SIZE_BYTES,
    SUMMARY_VERSION,
    DocumentLibraryError,
    clean_pdf_text,
    delete_library_document,
    format_document_upload_time,
    get_library_document,
    is_document_summary_current,
    list_library_documents,
    read_library_pdf,
    save_uploaded_pdf,
    search_library_documents,
    summarize_library_document,
    upload_and_summarize_pdf,
)
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore


def _pdf_bytes(text: str = "Personal lending eligibility guidance") -> bytes:
    """Create a small text PDF for parser and preview tests."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(0, 10, text)
    return bytes(pdf.output())


def _render_library(store: SQLiteStore, documents_dir: Path | None = None) -> AppTest:
    """Render the library page against a test-owned persistent database."""
    directory_argument = (
        f", documents_dir=Path({str(documents_dir)!r})" if documents_dir else ""
    )
    return AppTest.from_string(
        "from pathlib import Path\n"
        "from loanpilot.data.store import SQLiteStore\n"
        f"from loanpilot.pages.document_library import render\n"
        f"render(SQLiteStore({str(store.path)!r}){directory_argument})"
    )


def test_upload_persists_metadata_pdf_and_extracted_text(tmp_path) -> None:
    """The opaque file and its searchable metadata survive a new store instance."""
    database_path = tmp_path / "library.db"
    store = SQLiteStore(database_path)
    create_schema(store)
    original = _pdf_bytes("Lending eligibility requires verified monthly income.")
    document = save_uploaded_pdf(
        r"..\outside\eligibility.pdf",
        original,
        store,
        documents_dir=tmp_path / "library",
    )

    reopened_store = SQLiteStore(database_path)
    persisted = get_library_document(str(document["document_id"]), reopened_store)
    assert persisted is not None
    assert persisted["original_filename"] == "eligibility.pdf"
    assert persisted["mime_type"] == "application/pdf"
    assert persisted["size_bytes"] == len(original)
    assert persisted["processing_status"] == "Processed"
    assert "verified monthly income" in str(persisted["extracted_text"])
    assert read_library_pdf(
        str(document["document_id"]),
        reopened_store,
        documents_dir=tmp_path / "library",
    ) == original
    assert len(list_library_documents(reopened_store)) == 1


def test_upload_automatically_summarizes_once_and_keeps_each_update(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "summary.db"
    store = SQLiteStore(database_path)
    calls = []

    def fake_gemini(prompt: str) -> dict[str, str]:
        calls.append(prompt)
        if "minimum monthly income" in prompt:
            return {
                "headline": "Income eligibility guidance",
                "summary": "Applicants must verify minimum monthly income. "
                "The document describes the required verification process.",
            }
        return {
            "headline": "Loan document checklist",
            "summary": "Applicants must provide identity documents. "
            "The guide describes document review steps.",
        }

    monkeypatch.setattr(document_library, "generate_json_with_gemini", fake_gemini)
    documents_dir = tmp_path / "library"
    first = upload_and_summarize_pdf(
        "income-guide.pdf",
        _pdf_bytes("Applicants must verify minimum monthly income."),
        store,
        documents_dir=documents_dir,
    )
    second = upload_and_summarize_pdf(
        "document-checklist.pdf",
        _pdf_bytes("Applicants must provide identity documents."),
        store,
        documents_dir=documents_dir,
    )

    reopened = SQLiteStore(database_path)
    persisted_first = get_library_document(str(first["document_id"]), reopened)
    assert persisted_first is not None
    assert persisted_first["summary_status"] == "Completed"
    assert persisted_first["summary_method"] == "Gemini"
    assert persisted_first["summary_version"] == SUMMARY_VERSION
    assert persisted_first["summary_headline"] == "Income eligibility guidance"
    assert "minimum monthly income" in persisted_first["summary_text"]
    assert len(calls) == 2
    assert summarize_library_document(str(first["document_id"]), reopened)["summary_status"] == "Completed"
    assert len(calls) == 2

    documents = list_library_documents(reopened)
    assert [item["document_id"] for item in documents] == [
        second["document_id"],
        first["document_id"],
    ]
    assert documents[0]["summary_headline"] == "Loan document checklist"
    assert delete_library_document(
        str(first["document_id"]),
        reopened,
        documents_dir=documents_dir,
    ) is False
    assert get_library_document(str(first["document_id"]), reopened) is None
    assert get_library_document(str(second["document_id"]), reopened)["summary_status"] == "Completed"


def test_document_library_shows_file_metadata_and_actions_only(tmp_path, monkeypatch) -> None:
    """The library lists name/date and file actions, not document summaries."""
    store = SQLiteStore(tmp_path / "visible-summary.db")
    documents_dir = tmp_path / "library"
    monkeypatch.setattr(
        document_library,
        "generate_json_with_gemini",
        lambda _prompt: {
            "headline": "Income evidence review",
            "summary": (
                "Applicants provide proof of monthly income. "
                "Reviewers compare declared income with supporting documents."
            ),
        },
    )
    document = upload_and_summarize_pdf(
        "income-guide.pdf",
        _pdf_bytes("Applicants provide proof of monthly income."),
        store,
        documents_dir=documents_dir,
    )

    app = _render_library(store, documents_dir).run()
    assert not app.exception
    content = "\n".join(
        str(element.value)
        for name in ("markdown", "text", "caption")
        for element in getattr(app, name, [])
    )
    assert "income-guide.pdf" in content
    assert format_document_upload_time(
        get_library_document(str(document["document_id"]), store)["uploaded_at"]
    ) in content
    assert "Income evidence review" not in content
    assert "Applicants provide proof of monthly income" not in content
    assert "Generate summary" not in content
    assert "Regenerate summary" not in content
    assert "Read / View" in [button.label for button in app.button]
    assert "Delete" in [button.label for button in app.button]
    assert (
        get_library_document(str(document["document_id"]), store)["summary_status"]
        == "Completed"
    )


def test_gemini_summary_filters_generic_disclaimer_sentences(tmp_path, monkeypatch) -> None:
    """Generic demo disclaimers cannot replace or invalidate useful summary text."""
    store = SQLiteStore(tmp_path / "summary-disclaimer.db")
    monkeypatch.setattr(
        document_library,
        "generate_json_with_gemini",
        lambda _prompt: {
            "headline": "Income evidence review",
            "summary": (
                "Applicants provide proof of monthly income. "
                "This guide alone does not approve the case. "
                "Reviewers compare declared income with supporting documents."
            ),
        },
    )

    document = upload_and_summarize_pdf(
        "income-guide.pdf",
        _pdf_bytes(
            "Applicants provide proof of monthly income. "
            "Reviewers compare declared income with supporting documents."
        ),
        store,
        documents_dir=tmp_path / "library",
    )

    assert document["summary_method"] == "Gemini"
    assert is_document_summary_current(document)
    assert "This guide alone does not approve" not in document["summary_text"]
    assert "Reviewers compare declared income" in document["summary_text"]


def test_failed_extraction_is_honest_and_gemini_failure_uses_local_fallback(
    tmp_path,
    monkeypatch,
) -> None:
    store = SQLiteStore(tmp_path / "summary-failure.db")
    documents_dir = tmp_path / "library"
    calls = []

    def unavailable(prompt: str) -> dict[str, str]:
        calls.append(prompt)
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(document_library, "generate_json_with_gemini", unavailable)
    extraction_failed = upload_and_summarize_pdf(
        "unreadable.pdf",
        b"%PDF-1.4\nnot a real PDF",
        store,
        documents_dir=documents_dir,
    )
    assert extraction_failed["processing_status"] == "Failed"
    assert extraction_failed["summary_status"] == "Failed"
    assert extraction_failed["summary_headline"] == ""
    assert extraction_failed["summary_text"] == ""
    assert calls == []

    gemini_failed = upload_and_summarize_pdf(
        "readable.pdf",
        _pdf_bytes("The guideline requires a verified income document."),
        store,
        documents_dir=documents_dir,
    )
    assert gemini_failed["summary_status"] == "Completed"
    assert gemini_failed["summary_method"] == "Local extractive"
    assert gemini_failed["summary_headline"]
    assert "verified income document" in str(gemini_failed["summary_text"]).casefold()
    assert len(calls) == 1

    # A successful local fallback is terminal and is not resummarized on reruns.
    rerun = summarize_library_document(str(gemini_failed["document_id"]), store)
    assert rerun["summary_status"] == "Completed"
    assert rerun["summary_method"] == "Local extractive"
    assert len(calls) == 1


def test_local_extractive_summary_uses_document_sentences_and_skips_repeated_headers():
    """Local fallback selects factual sentences from separate document sections."""
    extracted_text = "\n".join(
        [
            "AARAMBH BANK - INTERNAL LENDING GUIDELINE",
            "Not an actual bank policy, legal advice, or a real loan decision.",
            "Production policies require approval by the relevant institution.",
            "This guide alone does not approve the case; affordability and verification remain necessary.",
            "Applicants must provide verified proof of stable monthly income.",
            "The credit team checks existing repayment obligations before eligibility.",
            "AARAMBH BANK - INTERNAL LENDING GUIDELINE",
            "Applications with incomplete identity documents remain pending review.",
            "The operations team records every verification result in the case file.",
        ]
    )

    result = document_library._extractive_summary(extracted_text)

    assert result is not None
    headline, summary = result
    assert headline
    assert "verified proof of stable monthly income" in summary.casefold()
    assert "incomplete identity documents" in summary.casefold()
    assert summary.casefold().count("aarambh bank") == 0
    assert "not an actual bank policy" not in summary.casefold()
    assert "production policies require approval" not in summary.casefold()
    assert "this guide alone does not approve the case" not in summary.casefold()


def test_pdf_cleanup_removes_furniture_without_losing_policy_controls():
    """Repeated headers, IDs, pages, and encoding noise are removed."""
    extracted = "\n".join(
        [
            "LOANPILOT | AARAMBH BANK",
            "FICTIONAL DEMO DOCUMENT",
            "Version: 4.2",
            "Page 1 of 2",
            "Audit records must include reviewer name, decision, reason, and timestamp.",
            "Escalate suspected document tampering to the credit manager for review.",
            "LOANPILOT | AARAMBH BANK",
            "Page 2 of 2",
            "Audit records must include reviewer name, decision, reason, and timestamp.",
            "The applicant must submit verified income statements before approval.",
            "Broken character: �",
        ]
    )

    cleaned = clean_pdf_text(extracted)

    assert "LOANPILOT" not in cleaned
    assert "AARAMBH BANK" not in cleaned
    assert "FICTIONAL DEMO DOCUMENT" not in cleaned
    assert "Version: 4.2" not in cleaned
    assert "Page 1" not in cleaned
    assert "�" not in cleaned
    assert cleaned.count("Audit records must include") == 1
    assert "reviewer name, decision, reason, and timestamp" in cleaned
    assert "Escalate suspected document tampering" in cleaned
    assert "verified income statements" in cleaned


def test_gemini_unavailable_falls_back_and_summary_persists_after_reopen(
    tmp_path, monkeypatch
) -> None:
    """A provider error produces a persisted local summary tied to the source ID."""
    database_path = tmp_path / "fallback-persistence.db"
    store = SQLiteStore(database_path)
    monkeypatch.setattr(
        document_library,
        "generate_json_with_gemini",
        lambda prompt: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
    )
    document = upload_and_summarize_pdf(
        "lending-rules.pdf",
        _pdf_bytes(
            "Applicants must submit verified identity documents before review. "
            "The credit team compares documented income against existing obligations. "
            "Incomplete applications remain pending until required evidence is received."
        ),
        store,
        documents_dir=tmp_path / "library",
    )

    reopened = SQLiteStore(database_path)
    persisted = get_library_document(str(document["document_id"]), reopened)
    assert persisted is not None
    assert persisted["document_id"] == document["document_id"]
    assert persisted["uploaded_at"] == document["uploaded_at"]
    assert persisted["summary_status"] == "Completed"
    assert persisted["summary_method"] == "Local extractive"
    assert persisted["summary_headline"]
    assert persisted["summary_text"]
    assert persisted["summary_error"] == ""
    assert summarize_library_document(str(document["document_id"]), reopened)[
        "summary_method"
    ] == "Local extractive"


def test_unreadable_or_noninformative_text_does_not_get_a_fabricated_summary(
    tmp_path, monkeypatch
) -> None:
    """Textless PDFs are saved with OCR guidance and no generated summary."""
    store = SQLiteStore(tmp_path / "no-text-summary.db")
    gemini_calls = []
    monkeypatch.setattr(
        document_library,
        "generate_json_with_gemini",
        lambda prompt: gemini_calls.append(prompt),
    )
    document = upload_and_summarize_pdf(
        "scanned.pdf",
        _pdf_bytes("Page 1"),
        store,
        documents_dir=tmp_path / "library",
    )
    assert document["summary_status"] == "Failed"
    assert document["summary_method"] == ""
    assert document["summary_headline"] == ""
    assert document["summary_text"] == ""
    assert "OCR" in str(document["summary_error"])
    assert gemini_calls == []


def test_uploaded_file_buffer_is_copied_before_pdf_processing(tmp_path, monkeypatch):
    """Processing an exported upload view does not retain or resize its buffer."""
    store = SQLiteStore(tmp_path / "uploaded-buffer.db")
    monkeypatch.setattr(
        document_library,
        "generate_json_with_gemini",
        lambda prompt: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
    )
    original = _pdf_bytes("The lender requires verified identity documents.")
    source = UploadedFile(
        UploadedFileRec("uploaded-id", "buffered.pdf", "application/pdf", original),
        FileURLs(),
    )
    upload_snapshot = bytes(source.getvalue())
    document = upload_and_summarize_pdf(
        source.name,
        upload_snapshot,
        store,
        documents_dir=tmp_path / "library",
    )
    source.seek(0, 2)
    source.write(b"more")

    assert document["processing_status"] == "Processed"
    assert read_library_pdf(
        str(document["document_id"]),
        store,
        documents_dir=tmp_path / "library",
    ) == original


def test_unusable_gemini_response_uses_factual_local_summary(tmp_path, monkeypatch):
    """Malformed model output falls back to actual extracted document sentences."""
    store = SQLiteStore(tmp_path / "malformed-summary.db")
    monkeypatch.setattr(
        document_library,
        "generate_json_with_gemini",
        lambda prompt: {"headline": "", "summary": ""},
    )

    document = upload_and_summarize_pdf(
        "eligibility.pdf",
        _pdf_bytes(
            "Applicants must provide verified income statements before assessment. "
            "The credit team checks existing debt obligations during eligibility review."
        ),
        store,
        documents_dir=tmp_path / "library",
    )

    assert document["summary_status"] == "Completed"
    assert document["summary_method"] == "Local extractive"
    assert "verified income statements" in str(document["summary_text"]).casefold()


def test_existing_document_schema_is_migrated_without_losing_records(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "old-library.db")
    with store.connection() as connection:
        connection.execute(
            """
            CREATE TABLE raw_library_documents (
                document_id TEXT PRIMARY KEY,
                original_filename TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                processing_status TEXT NOT NULL,
                extracted_text TEXT NOT NULL DEFAULT '',
                processing_error TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            INSERT INTO raw_library_documents (
                document_id, original_filename, uploaded_at, mime_type,
                size_bytes, processing_status
            ) VALUES ('old-doc', 'old.pdf', '2026-01-01T00:00:00', 'application/pdf',
                      100, 'Processed')
            """
        )

    create_schema(store)
    persisted = get_library_document("old-doc", store)

    assert persisted is not None
    assert persisted["original_filename"] == "old.pdf"
    assert persisted["summary_status"] == "Not requested"
    assert persisted["summary_method"] == ""
    assert persisted["summary_version"] == 0
    assert persisted["summary_headline"] == ""


def test_document_library_has_no_summary_actions_or_summary_content(tmp_path, monkeypatch) -> None:
    store = SQLiteStore(tmp_path / "retry-ui.db")
    documents_dir = tmp_path / "library"
    document = save_uploaded_pdf(
        "retry-policy.pdf",
        _pdf_bytes("The policy requires verified monthly income."),
        store,
        documents_dir=documents_dir,
    )
    store.execute(
        """
        UPDATE raw_library_documents
        SET summary_status = 'Failed', summary_error = 'Gemini unavailable.'
        WHERE document_id = ?
        """,
        (document["document_id"],),
    )
    monkeypatch.setattr(
        document_library,
        "generate_json_with_gemini",
        lambda _prompt: pytest.fail("Document Library must not generate summaries"),
    )
    app = _render_library(store, documents_dir).run()
    assert not app.exception
    visible_text = "\n".join(
        str(element.value)
        for name in ("title", "subheader", "caption", "markdown", "text")
        for element in getattr(app, name, [])
    )
    assert "Manage PDF references for Aarambh Bank" not in visible_text
    assert "Extracted guidance is informational" not in visible_text
    assert "Summary unavailable" not in visible_text
    assert "Generate summary" not in visible_text
    assert not any("summary" in button.label.casefold() for button in app.button)
    assert [
        button.label
        for button in app.button
        if button.key in {
            f"library_view_{document['document_id']}",
            f"library_delete_{document['document_id']}",
        }
    ] == ["Read / View", "Delete"]
    assert any(
        format_document_upload_time(document["uploaded_at"]) in item.value
        for item in app.caption
    )
    assert (
        get_library_document(str(document["document_id"]), store)["summary_status"]
        == "Failed"
    )


def test_overview_regenerates_old_summary_from_cleaned_source(tmp_path, monkeypatch):
    """Overview refreshes an obsolete summary without adding a duplicate record."""
    store = SQLiteStore(tmp_path / "old-summary-refresh.db")
    documents_dir = tmp_path / "library"
    document = save_uploaded_pdf(
        "old-policy.pdf",
        _pdf_bytes(
            "LOANPILOT AARAMBH BANK FICTIONAL DEMO DOCUMENT Page 1 "
            "Applicants must provide verified income statements before review. "
            "The credit team records the reviewer name, decision reason, and timestamp."
        ),
        store,
        documents_dir=documents_dir,
    )
    store.execute(
        """
        UPDATE raw_library_documents
        SET summary_status = 'Completed', summary_method = 'Gemini',
            summary_headline = 'LOANPILOT AARAMBH BANK Page 1',
            summary_text = 'LOANPILOT AARAMBH BANK FICTIONAL DEMO DOCUMENT Page 1',
            summary_version = 0
        WHERE document_id = ?
        """,
        (document["document_id"],),
    )
    prompts = []

    def fake_gemini(prompt: str) -> dict[str, str]:
        prompts.append(prompt)
        return {
            "headline": "Verified income review requirements",
            "summary": (
                "Applicants must provide verified income statements before review. "
                "The credit team records the reviewer name, decision reason, and timestamp."
            ),
        }

    monkeypatch.setattr(document_library, "generate_json_with_gemini", fake_gemini)
    app = AppTest.from_string(
        "from loanpilot.data.store import SQLiteStore\n"
        "from loanpilot.pages.overview import render\n"
        f"render(SQLiteStore({str(store.path)!r}))"
    ).run()

    rows = list_library_documents(store)
    refreshed = get_library_document(str(document["document_id"]), store)
    assert not app.exception
    assert len(rows) == 1
    assert refreshed is not None
    assert refreshed["summary_version"] == SUMMARY_VERSION
    assert refreshed["summary_headline"] == "Verified income review requirements"
    assert "LOANPILOT" not in prompts[0]
    assert "FICTIONAL DEMO DOCUMENT" not in prompts[0]
    assert "reviewer name, decision reason, and timestamp" in " ".join(
        prompts[0].split()
    )


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("policy.txt", b"%PDF-1.4", "Choose a PDF"),
        ("policy.pdf", b"not a PDF", "not a valid PDF"),
    ],
)
def test_invalid_uploads_are_rejected_without_records(
    tmp_path,
    filename: str,
    content: bytes,
    message: str,
) -> None:
    store = SQLiteStore(tmp_path / "invalid.db")
    create_schema(store)

    with pytest.raises(DocumentLibraryError, match=message):
        save_uploaded_pdf(filename, content, store, documents_dir=tmp_path / "library")

    assert list_library_documents(store) == []
    assert not (tmp_path / "library").exists()


def test_upload_size_limit_is_enforced(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "too-large.db")
    create_schema(store)

    with pytest.raises(DocumentLibraryError, match="10 MB or smaller"):
        save_uploaded_pdf(
            "large.pdf",
            b"%PDF-" + b"x" * MAX_DOCUMENT_SIZE_BYTES,
            store,
            documents_dir=tmp_path / "library",
        )

    assert list_library_documents(store) == []
    assert not (tmp_path / "library").exists()


def test_unreadable_pdf_is_saved_with_failed_status(tmp_path) -> None:
    """A PDF that cannot be parsed remains viewable with an explicit failure."""
    store = SQLiteStore(tmp_path / "unreadable.db")
    document = save_uploaded_pdf(
        "unreadable.pdf",
        b"%PDF-1.4\nnot a real PDF",
        store,
        documents_dir=tmp_path / "library",
    )

    assert document["processing_status"] == "Failed"
    assert document["processing_error"]
    assert read_library_pdf(
        str(document["document_id"]),
        store,
        documents_dir=tmp_path / "library",
    ).startswith(b"%PDF-")


def test_search_returns_only_relevant_processed_document_text(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "search.db")
    document = save_uploaded_pdf(
        "eligibility.pdf",
        _pdf_bytes("For lending eligibility, verify monthly income and existing debt."),
        store,
        documents_dir=tmp_path / "library",
    )

    results = search_library_documents("eligibility monthly income", store)

    assert len(results) == 1
    assert results[0]["document_id"] == document["document_id"]
    assert "monthly income" in str(results[0]["snippet"]).casefold()
    assert search_library_documents("unrelated gardening topic", store) == []


def test_ai_assessment_displays_retrieved_guidance_separately(tmp_path) -> None:
    """Retrieved excerpts are shown as reference, not as assessment policy."""
    store = SQLiteStore(tmp_path / "assessment-reference.db")
    create_schema(store)
    store.execute(
        """
        INSERT INTO cur_customers (
            customer_id, name, dob, age, city, employer, employment_type,
            current_tenure_months, total_experience_months, net_monthly_income,
            pan_demo_id, kyc_status, relationship_since
        ) VALUES ('C1', 'Test Applicant', '1990-01-01', 36, 'Pune', 'Employer',
                  'Salaried', 24, 60, 50000, 'DEMO-PAN-1', 'Verified', '2020-01-01')
        """
    )
    store.execute(
        """
        INSERT INTO cur_applications (
            application_id, customer_id, requested_amount, tenure_months,
            purpose, channel, submitted_at, stage
        ) VALUES ('APP-1', 'C1', 100000, 24, 'Credit review', 'Branch',
                  '2026-01-01T00:00:00', 'Submitted')
        """
    )
    save_uploaded_pdf(
        "review-guide.pdf",
        _pdf_bytes("Credit review guidance: manual review applies to policy exceptions."),
        store,
        documents_dir=tmp_path / "library",
    )
    app = AppTest.from_string(
        "from loanpilot.data.store import SQLiteStore\n"
        "from loanpilot.pages.ai_assessment import _render_library_references\n"
        f"store = SQLiteStore({str(store.path)!r})\n"
        "_render_library_references({'application_id': 'APP-1', "
        "'policy': {'clauses': [{'rule_text': 'Credit review policy exceptions'}]}}, store)"
    ).run()

    assert not app.exception
    assert any("Document Library references" in item.label for item in app.expander)
    assert any(
        "not used to calculate or change this assessment" in item.value
        for item in app.caption
    )
    assert any(
        "manual review applies" in item.value.casefold()
        for item in [*app.markdown, *app.text]
    )


def test_delete_removes_only_selected_document_and_handles_missing_file(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "delete.db")
    documents_dir = tmp_path / "library"
    first = save_uploaded_pdf("first.pdf", _pdf_bytes("first document"), store, documents_dir=documents_dir)
    second = save_uploaded_pdf("second.pdf", _pdf_bytes("second document"), store, documents_dir=documents_dir)

    missing = delete_library_document(
        str(first["document_id"]),
        store,
        documents_dir=documents_dir,
    )

    assert not missing
    assert get_library_document(str(first["document_id"]), store) is None
    assert get_library_document(str(second["document_id"]), store) is not None
    assert not (documents_dir / f"{first['document_id']}.pdf").exists()
    assert (documents_dir / f"{second['document_id']}.pdf").is_file()

    (documents_dir / f"{second['document_id']}.pdf").unlink()
    assert delete_library_document(
        str(second["document_id"]),
        store,
        documents_dir=documents_dir,
    )
    assert get_library_document(str(second["document_id"]), store) is None


def test_delete_error_keeps_library_record(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "delete-error.db")
    documents_dir = tmp_path / "library"
    document = save_uploaded_pdf(
        "cannot-delete.pdf",
        _pdf_bytes(),
        store,
        documents_dir=documents_dir,
    )
    path = documents_dir / f"{document['document_id']}.pdf"
    path.unlink()
    path.mkdir()

    with pytest.raises(DocumentLibraryError, match="record was kept"):
        delete_library_document(str(document["document_id"]), store, documents_dir=documents_dir)

    assert get_library_document(str(document["document_id"]), store) is not None
    path.rmdir()


def test_library_ui_views_selected_document_and_requires_delete_confirmation(tmp_path) -> None:
    """View selects the named PDF; delete requires a second explicit action."""
    store = SQLiteStore(tmp_path / "library-ui.db")
    documents_dir = tmp_path / "library"
    document = save_uploaded_pdf(
        "selected-policy.pdf",
        _pdf_bytes("Selected policy content"),
        store,
        documents_dir=documents_dir,
    )
    document_id = str(document["document_id"])
    app = _render_library(store, documents_dir)

    app.run()
    assert not app.exception
    app.button(key=f"library_view_{document_id}").click().run()
    assert not app.exception
    assert any("Reading selected PDF" in item.value for item in app.subheader)
    assert any(
        "selected-policy.pdf" in item.value
        for item in app.caption
    )
    assert any(
        button.label == "Download original PDF"
        for button in app.get("download_button")
    )
    assert read_library_pdf(
        document_id,
        store,
        documents_dir=documents_dir,
    ).startswith(b"%PDF-")

    app.button(key=f"library_delete_{document_id}").click().run()
    assert not app.exception
    assert (documents_dir / f"{document_id}.pdf").is_file()
    assert get_library_document(document_id, store) is not None
    assert any(button.key == "library_confirm_delete" for button in app.button)

    app.button(key="library_confirm_delete").click().run()
    assert not app.exception
    assert get_library_document(document_id, store) is None
    assert not (documents_dir / f"{document_id}.pdf").exists()
    assert any("document and its extracted text were deleted" in item.value for item in app.info)


def test_document_storage_failure_is_reported_without_metadata(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "storage-failure.db")
    documents_dir = tmp_path / "not-a-directory"
    documents_dir.write_text("occupied")

    with pytest.raises(DocumentLibraryError, match="could not be saved"):
        save_uploaded_pdf(
            "policy.pdf",
            _pdf_bytes(),
            store,
            documents_dir=documents_dir,
        )

    assert list_library_documents(store) == []
