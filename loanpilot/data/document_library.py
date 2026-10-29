"""Persistent storage, PDF processing, and reference retrieval for the library."""

from collections import Counter
from datetime import datetime, timezone
import logging
import math
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from loanpilot.agent.llm import GeminiUnavailableError, generate_json_with_gemini
from loanpilot.config import DOCUMENT_LIBRARY_DIR
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore

LOGGER = logging.getLogger(__name__)
MAX_DOCUMENT_SIZE_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 200
MAX_EXTRACTED_TEXT_CHARS = 500_000
MAX_SEARCH_CANDIDATES = 100
_DOCUMENT_ID = re.compile(r"[0-9a-f]{32}\Z")
_SEARCH_STOP_WORDS = {
    "and", "are", "for", "from", "has", "have", "into", "loan", "not",
    "our", "the", "this", "that", "their", "was", "with", "you",
}
_SUMMARY_STOP_WORDS = {
    "about", "after", "again", "also", "and", "any", "are", "because",
    "been", "before", "being", "between", "both", "but", "can", "could",
    "does", "each", "for", "from", "further", "had", "has", "have", "her",
    "here", "him", "his", "how", "into", "its", "may", "more", "most",
    "not", "our", "out", "over", "same", "shall", "should", "some", "such",
    "than", "that", "the", "their", "them", "then", "there", "these", "they",
    "this", "those", "through", "under", "until", "upon", "very", "was",
    "were", "what", "when", "where", "which", "while", "who", "will", "with",
    "would", "you", "your",
}


class DocumentLibraryError(ValueError):
    """A user-actionable document library validation or storage error."""


class DocumentNotFoundError(DocumentLibraryError):
    """A requested library document no longer exists."""


def _extractive_summary(text: str) -> tuple[str, str] | None:
    """Choose representative, informative source sentences without adding facts."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    line_counts = Counter(
        re.sub(r"\s+", " ", line).casefold()
        for line in lines
        if len(line) <= 120
    )
    filtered_lines = [
        line
        for line in lines
        if not (
            len(line) <= 120
            and line_counts[re.sub(r"\s+", " ", line).casefold()] > 1
        )
    ]
    normalized_text = " ".join(filtered_lines)
    sentences = [
        " ".join(sentence.split())
        for sentence in re.split(r"(?<=[.!?])\s+", normalized_text)
        if sentence.strip()
    ]

    candidates: list[tuple[str, list[str], set[str]]] = []
    for sentence in sentences:
        words = re.findall(r"[a-z][a-z'-]{2,}", sentence.casefold())
        terms = [
            word.strip("-'")
            for word in words
            if len(word.strip("-'")) >= 3
            and word.strip("-'") not in _SUMMARY_STOP_WORDS
        ]
        if len(terms) < 5:
            continue
        candidates.append((sentence, terms, set(terms)))
    if not candidates:
        return None

    document_frequencies = Counter(
        term for _, _, unique_terms in candidates for term in unique_terms
    )
    sentence_count = len(candidates)
    scores = []
    for index, (_, terms, unique_terms) in enumerate(candidates):
        informative_weight = sum(
            (1 + math.log1p(terms.count(term)))
            * (1 + math.log((sentence_count + 1) / (document_frequencies[term] + 0.5)))
            for term in unique_terms
        )
        scores.append((informative_weight / math.sqrt(len(terms)), index))

    # First select the strongest sentence from each document third, then fill
    # remaining slots by score. This avoids summarizing only the opening page.
    selected: list[int] = []
    for start_fraction, end_fraction in ((0, 1 / 3), (1 / 3, 2 / 3), (2 / 3, 1)):
        start = int(sentence_count * start_fraction)
        end = int(sentence_count * end_fraction)
        if end <= start and start < sentence_count:
            end = start + 1
        in_section = [item for item in scores if start <= item[1] < end]
        if in_section:
            selected.append(max(in_section)[1])
    for _, index in sorted(scores, reverse=True):
        if index not in selected and len(selected) < 4:
            selected.append(index)
    selected = sorted(selected[:4])

    distinct: list[int] = []
    for index in selected:
        terms = candidates[index][2]
        if any(
            len(terms & candidates[prior][2]) / max(1, len(terms | candidates[prior][2]))
            >= 0.72
            for prior in distinct
        ):
            continue
        distinct.append(index)
    if not distinct:
        return None

    summary = " ".join(candidates[index][0] for index in distinct)
    sentence_scores = {index: score for score, index in scores}
    headline = candidates[max(distinct, key=sentence_scores.get)][0].strip().rstrip(".!?")
    if len(headline) > 100:
        headline = headline[:97].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
    if len(summary) > 1800:
        summary = summary[:1797].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
    return headline, summary


def _has_meaningful_text(text: str) -> bool:
    """Reject blank, page-label, and similarly non-substantive extraction output."""
    terms = {
        word.strip("-'")
        for word in re.findall(r"[a-z][a-z'-]{2,}", text.casefold())
        if word.strip("-'") not in _SUMMARY_STOP_WORDS
    }
    return len(terms) >= 3


def format_document_upload_time(value: object) -> str:
    """Render a persisted upload timestamp in the viewer's local timezone."""
    try:
        uploaded_at = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    if uploaded_at.tzinfo:
        uploaded_at = uploaded_at.astimezone()
    return uploaded_at.strftime("%d %b %Y, %I:%M %p %Z").strip()


def _document_path(document_id: str, documents_dir: Path) -> Path:
    """Resolve an opaque identifier to its generated PDF filename."""
    if not _DOCUMENT_ID.fullmatch(document_id):
        raise DocumentNotFoundError("The selected document is not available.")
    return documents_dir / f"{document_id}.pdf"


def _extract_pdf_text(path: Path) -> tuple[str, str]:
    """Extract bounded text from a PDF and return a visible processing note."""
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError, PdfStreamError
    except ImportError as error:
        raise DocumentLibraryError(
            "PDF text processing is unavailable because pypdf is not installed."
        ) from error

    try:
        with path.open("rb") as pdf_file:
            reader = PdfReader(pdf_file, strict=False)
            if reader.is_encrypted and not reader.decrypt(""):
                return "", "Encrypted PDFs are not supported."
            if len(reader.pages) > MAX_PDF_PAGES:
                return "", f"PDF exceeds the {MAX_PDF_PAGES}-page processing limit."
            extracted = []
            total_chars = 0
            for page in reader.pages:
                remaining = MAX_EXTRACTED_TEXT_CHARS - total_chars
                if remaining <= 0:
                    break
                page_text = page.extract_text() or ""
                extracted.append(page_text[:remaining])
                total_chars += min(len(page_text), remaining)
    except (OSError, ValueError, TypeError, PdfReadError, PdfStreamError) as error:
        LOGGER.warning("Could not extract text from library PDF (%s).", type(error).__name__)
        return "", "PDF text extraction failed; the original file is still available."

    text = "\n".join(extracted).strip()
    if not text:
        return "", "No selectable text found; this may be a scanned PDF."
    note = (
        "Text extraction was capped at 500,000 characters."
        if total_chars >= MAX_EXTRACTED_TEXT_CHARS
        else ""
    )
    return text, note


def save_uploaded_pdf(
    filename: str,
    content: bytes | bytearray | memoryview,
    store: SQLiteStore,
    *,
    documents_dir: Path = DOCUMENT_LIBRARY_DIR,
) -> dict[str, object]:
    """Validate, persist, and process an uploaded PDF without trusting its name."""
    # Streamlit UploadedFile is a mutable BytesIO. Keep only an independent
    # immutable snapshot so rerun cleanup cannot resize an exported buffer.
    content_bytes = bytes(content)
    safe_name = Path(filename.replace("\\", "/")).name.strip()
    if not safe_name or Path(safe_name).suffix.casefold() != ".pdf":
        raise DocumentLibraryError("Choose a PDF file to upload.")
    content_size = len(content_bytes)
    if content_size == 0:
        raise DocumentLibraryError("The selected PDF is empty.")
    if content_size > MAX_DOCUMENT_SIZE_BYTES:
        raise DocumentLibraryError("PDF files must be 10 MB or smaller.")
    if b"%PDF-" not in content_bytes[:1024]:
        raise DocumentLibraryError("The selected file is not a valid PDF.")

    create_schema(store)
    document_id = uuid4().hex
    path = _document_path(document_id, documents_dir)
    try:
        documents_dir.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as pdf_file:
            pdf_file.write(content_bytes)
    except OSError as error:
        raise DocumentLibraryError("The PDF could not be saved to the document library.") from error

    try:
        extracted_text, processing_error = _extract_pdf_text(path)
        processing_status = "Processed" if extracted_text else "Failed"
        uploaded_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        store.execute(
            """
            INSERT INTO raw_library_documents (
                document_id, original_filename, uploaded_at, mime_type,
                size_bytes, processing_status, extracted_text, processing_error,
                summary_status, summary_method, summary_headline, summary_text,
                summary_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Not requested', '', '', '', '')
            """,
            (
                document_id,
                safe_name,
                uploaded_at,
                "application/pdf",
                content_size,
                processing_status,
                extracted_text,
                processing_error,
            ),
        )
    except (DocumentLibraryError, OSError, sqlite3.Error) as error:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            LOGGER.exception("Could not clean up an unregistered library PDF.")
        if isinstance(error, DocumentLibraryError):
            raise
        raise DocumentLibraryError(
            "The PDF was saved but could not be registered in the document library."
        ) from error

    document = get_library_document(document_id, store)
    if document is None:
        raise DocumentLibraryError("The uploaded PDF could not be found after saving.")
    return document


def list_library_documents(store: SQLiteStore) -> list[dict[str, object]]:
    """List document metadata without loading extracted text."""
    create_schema(store)
    rows = store.query(
        """
        SELECT document_id, original_filename, uploaded_at, mime_type,
               size_bytes, processing_status, processing_error, summary_status,
               summary_method, summary_headline, summary_text, summary_error
        FROM raw_library_documents
        ORDER BY uploaded_at DESC, document_id
        """
    )
    return rows.to_dict("records")


def get_library_document(
    document_id: str,
    store: SQLiteStore,
) -> dict[str, object] | None:
    """Fetch one library record and its extracted text."""
    create_schema(store)
    rows = store.query(
        "SELECT * FROM raw_library_documents WHERE document_id = ?",
        (document_id,),
    )
    return rows.iloc[0].to_dict() if not rows.empty else None


def summarize_library_document(
    document_id: str,
    store: SQLiteStore,
    *,
    retry: bool = False,
) -> dict[str, object]:
    """Persist one grounded Gemini summary or a local extractive fallback."""
    document = get_library_document(document_id, store)
    if document is None:
        raise DocumentNotFoundError("The selected document is no longer in the library.")
    summary_status = str(document.get("summary_status", "Not requested"))
    if summary_status == "Completed" or (
        summary_status != "Not requested" and not retry
    ):
        return document

    extracted_text = str(document.get("extracted_text") or "").strip()
    if not extracted_text:
        error = str(
            document.get("processing_error")
            or "No selectable PDF text was available for summarisation."
        )
        _store_document_summary(
            document_id,
            store,
            "Failed",
            "",
            "",
            "",
            error,
        )
        result = get_library_document(document_id, store)
        if result is None:
            raise DocumentNotFoundError("The selected document is no longer in the library.")
        return result

    local_fallback = _extractive_summary(extracted_text)
    if not _has_meaningful_text(extracted_text):
        message = (
            "No meaningful selectable text was found. This may be a scanned PDF; "
            "use an OCR-readable PDF and retry."
        )
        _store_document_summary(
            document_id,
            store,
            "Failed",
            "",
            "",
            "",
            message,
        )
        result = get_library_document(document_id, store)
        if result is None:
            raise DocumentNotFoundError("The selected document is no longer in the library.")
        return result

    claim_status = "Failed" if retry else "Not requested"
    claimed = store.execute(
        """
        UPDATE raw_library_documents
        SET summary_status = 'Processing', summary_headline = '',
            summary_method = '', summary_text = '', summary_error = ''
        WHERE document_id = ? AND summary_status = ?
        """,
        (document_id, claim_status),
    )
    if claimed != 1:
        current = get_library_document(document_id, store)
        if current is None:
            raise DocumentNotFoundError("The selected document is no longer in the library.")
        return current
    prompt = (
        "Summarize this uploaded banking reference using only the supplied document text. "
        "Do not add facts, regulations, rates, dates, eligibility rules, or policy changes "
        "that are not explicit in the text. Capture its main purpose and the most important "
        "rules, eligibility criteria, process changes, or procedures that are present. "
        "Return a JSON object with exactly two string fields: headline (a concise, factual "
        "headline) and summary (two to four concise sentences). If the text does not support "
        "a useful factual summary, explain that in the summary rather than inferring. "
        "Document text:\n"
        f"{extracted_text[:60_000]}"
    )
    try:
        payload = generate_json_with_gemini(prompt)
        headline = payload.get("headline")
        summary = payload.get("summary")
        if not isinstance(headline, str) or not headline.strip():
            raise ValueError("Gemini returned no summary headline.")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("Gemini returned no summary text.")
        _store_document_summary(
            document_id,
            store,
            "Completed",
            "Gemini",
            headline.strip()[:160],
            summary.strip()[:1800],
            "",
        )
    except Exception as error:
        LOGGER.warning(
            "Document summary failed (%s).",
            type(error).__name__,
        )
        if local_fallback is not None:
            headline, summary = local_fallback
            _store_document_summary(
                document_id,
                store,
                "Completed",
                "Local extractive",
                headline,
                summary,
                "",
            )
        else:
            message = (
                "The extracted text did not support a reliable factual summary. "
                "Review the document text and retry."
            )
            if isinstance(error, GeminiUnavailableError):
                message = (
                    "Gemini is unavailable, and the extracted text did not support "
                    "a reliable local summary. Review the document text and retry."
                )
            _store_document_summary(
                document_id,
                store,
                "Failed",
                "",
                "",
                "",
                message,
            )

    result = get_library_document(document_id, store)
    if result is None:
        raise DocumentNotFoundError("The selected document is no longer in the library.")
    return result


def upload_and_summarize_pdf(
    filename: str,
    content: bytes | bytearray | memoryview,
    store: SQLiteStore,
    *,
    documents_dir: Path = DOCUMENT_LIBRARY_DIR,
) -> dict[str, object]:
    """Persist and extract an uploaded PDF, then summarize it once."""
    document = save_uploaded_pdf(
        filename,
        content,
        store,
        documents_dir=documents_dir,
    )
    return summarize_library_document(str(document["document_id"]), store)


def _store_document_summary(
    document_id: str,
    store: SQLiteStore,
    status: str,
    method: str,
    headline: str,
    summary: str,
    error: str,
) -> None:
    """Persist summary state on the original document record."""
    updated = store.execute(
        """
        UPDATE raw_library_documents
        SET summary_status = ?, summary_method = ?, summary_headline = ?,
            summary_text = ?, summary_error = ?
        WHERE document_id = ?
        """,
        (status, method, headline, summary, error, document_id),
    )
    if updated != 1:
        raise DocumentNotFoundError("The selected document is no longer in the library.")


def read_library_pdf(
    document_id: str,
    store: SQLiteStore,
    *,
    documents_dir: Path = DOCUMENT_LIBRARY_DIR,
) -> bytes:
    """Read the exact PDF associated with a persisted document record."""
    if get_library_document(document_id, store) is None:
        raise DocumentNotFoundError("The selected document is no longer in the library.")
    path = _document_path(document_id, documents_dir)
    try:
        return path.read_bytes()
    except OSError as error:
        raise DocumentLibraryError(
            "The PDF file is missing or could not be opened."
        ) from error


def delete_library_document(
    document_id: str,
    store: SQLiteStore,
    *,
    documents_dir: Path = DOCUMENT_LIBRARY_DIR,
) -> bool:
    """Delete one confirmed library record and its PDF; return if file was missing."""
    if get_library_document(document_id, store) is None:
        raise DocumentNotFoundError("The selected document is no longer in the library.")
    path = _document_path(document_id, documents_dir)
    file_missing = not path.exists()
    if not file_missing:
        try:
            path.unlink()
        except OSError as error:
            raise DocumentLibraryError(
                "The PDF could not be deleted. Its library record was kept."
            ) from error
    try:
        deleted = store.execute(
            "DELETE FROM raw_library_documents WHERE document_id = ?",
            (document_id,),
        )
    except sqlite3.Error as error:
        raise DocumentLibraryError(
            "The PDF was removed, but its library record could not be deleted."
        ) from error
    if deleted != 1:
        raise DocumentNotFoundError("The selected document is no longer in the library.")
    return file_missing


def search_library_documents(
    query: str,
    store: SQLiteStore,
    *,
    limit: int = 3,
) -> list[dict[str, object]]:
    """Return processed document excerpts ranked by simple keyword overlap."""
    terms = sorted(
        {
            term
            for term in re.findall(r"[a-z0-9]{3,}", query.casefold())
            if term not in _SEARCH_STOP_WORDS
        }
    )[:64]
    if not terms:
        return []
    match_conditions = " OR ".join(
        "LOWER(extracted_text) LIKE ?" for _ in terms
    )
    rows = store.query(
        f"""
        SELECT document_id, original_filename, uploaded_at, extracted_text
        FROM raw_library_documents
        WHERE processing_status = 'Processed' AND extracted_text != ''
          AND ({match_conditions})
        ORDER BY uploaded_at DESC
        LIMIT ?
        """,
        [f"%{term}%" for term in terms] + [MAX_SEARCH_CANDIDATES],
    )
    matches = []
    for row in rows.to_dict("records"):
        text = str(row["extracted_text"])
        folded_text = text.casefold()
        term_counts = {term: folded_text.count(term) for term in terms}
        score = sum(term_counts.values())
        if score == 0:
            continue
        best_term = max(term_counts, key=term_counts.get)
        position = folded_text.find(best_term)
        start = max(0, position - 110)
        end = min(len(text), position + 170)
        snippet = " ".join(text[start:end].split())
        matches.append(
            {
                "document_id": row["document_id"],
                "original_filename": row["original_filename"],
                "uploaded_at": row["uploaded_at"],
                "snippet": snippet,
                "score": score,
            }
        )
    matches.sort(key=lambda result: (-int(result["score"]), str(result["original_filename"]).casefold()))
    return matches[:max(0, limit)]
