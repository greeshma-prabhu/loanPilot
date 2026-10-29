"""Persistent library of reference PDFs for the lending workspace."""

import inspect
from importlib.util import find_spec
from pathlib import Path

import streamlit as st

from loanpilot.components import status_chip
from loanpilot.config import DOCUMENT_LIBRARY_DIR
from loanpilot.data.document_library import (
    MAX_DOCUMENT_SIZE_BYTES,
    DocumentLibraryError,
    delete_library_document,
    format_document_upload_time,
    list_library_documents,
    read_library_pdf,
    summarize_library_document,
    upload_and_summarize_pdf,
)
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore
from loanpilot.theme import render_disclaimer, render_header


def _format_size(value: object) -> str:
    """Render a small PDF size without rounding it down to zero."""
    size_bytes = int(value)
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.2f} MB"


def _render_upload(store: SQLiteStore, documents_dir: Path) -> None:
    """Render the constrained PDF upload and explicit processing feedback."""
    with st.container(border=True):
        st.subheader("Upload Document")
        st.caption("Add a lending policy, eligibility guide, or SOP PDF (maximum 10 MB).")
        uploader_options = {}
        if "max_upload_size" in inspect.signature(st.file_uploader).parameters:
            uploader_options["max_upload_size"] = MAX_DOCUMENT_SIZE_BYTES // (1024 * 1024)
        uploaded_file = st.file_uploader(
            "Choose a PDF document",
            type=["pdf"],
            key="library_pdf_upload",
            help="PDF only; maximum 10 MB.",
            **uploader_options,
        )
        upload_error = ""
        if uploaded_file is not None:
            if not uploaded_file.name.casefold().endswith(".pdf"):
                upload_error = "Choose a PDF file to upload."
            elif uploaded_file.size > MAX_DOCUMENT_SIZE_BYTES:
                upload_error = "PDF files must be 10 MB or smaller."
            if upload_error:
                st.error(upload_error)
        if st.button(
            "Upload Document",
            key="library_upload_document",
            type="primary",
            disabled=uploaded_file is None or bool(upload_error),
        ):
            with st.spinner("Saving the PDF, extracting text, and preparing its summary..."):
                try:
                    uploaded_name = str(uploaded_file.name)
                    uploaded_content = bytes(uploaded_file.getvalue())
                    document = upload_and_summarize_pdf(
                        uploaded_name,
                        uploaded_content,
                        store,
                        documents_dir=documents_dir,
                    )
                except DocumentLibraryError as error:
                    st.error(str(error))
                else:
                    st.success("Document uploaded.")
                    st.caption(
                        f"{document['original_filename']} · "
                        f"{format_document_upload_time(document['uploaded_at'])}"
                    )
                    if document["processing_status"] != "Processed":
                        st.warning(str(document["processing_error"]))
                    elif document["summary_status"] == "Completed":
                        st.caption("Document summary is ready in Overview → Latest Updates.")
                    else:
                        st.warning(str(document["summary_error"]))


def _render_document_list(
    documents: list[dict[str, object]],
    store: SQLiteStore,
    documents_dir: Path,
) -> None:
    """Render persisted document cards with view and confirmed-delete actions."""
    st.subheader("Library Documents")
    if not documents:
        st.info("No documents yet. Upload a PDF to create your reference library.")
        return

    for document in documents:
        document_id = str(document["document_id"])
        with st.container(border=True):
            st.write(str(document["original_filename"]))
            st.caption(
                f"{format_document_upload_time(document['uploaded_at'])} · PDF · "
                f"{_format_size(document['size_bytes'])}"
            )
            status = str(document["processing_status"])
            st.markdown(
                status_chip(
                    status,
                    {"Processed": "success", "Failed": "danger"}.get(status, "info"),
                ),
                unsafe_allow_html=True,
            )
            if document["processing_error"]:
                st.caption(str(document["processing_error"]))
            summary_status = str(document.get("summary_status", "Not requested"))
            if summary_status == "Failed":
                st.caption(f"Summary failed · {document.get('summary_error', '')}")
            elif summary_status == "Processing":
                st.caption("Summary processing is incomplete.")
            view_column, delete_column = st.columns(2)
            with view_column:
                if st.button(
                    "Read / View",
                    key=f"library_view_{document_id}",
                    width="stretch",
                ):
                    st.session_state["library_view_document"] = document_id
            with delete_column:
                if st.button(
                    "Delete",
                    key=f"library_delete_{document_id}",
                    width="stretch",
                ):
                    st.session_state["library_delete_pending"] = document_id
            if summary_status == "Failed" and document["processing_status"] == "Processed":
                if st.button(
                    "Retry summary",
                    key=f"library_retry_summary_{document_id}",
                ):
                    with st.spinner("Retrying document summary..."):
                        updated = summarize_library_document(
                            document_id,
                            store,
                            retry=True,
                        )
                    if updated["summary_status"] == "Completed":
                        st.success("Document summary is ready in Overview → Latest Updates.")
                    else:
                        st.error(str(updated["summary_error"]))

    pending_id = st.session_state.get("library_delete_pending")
    pending = next(
        (item for item in documents if item["document_id"] == pending_id),
        None,
    )
    if pending is not None:
        st.warning(
            "Confirm deleting this PDF and its extracted text from the library."
        )
        st.write(str(pending["original_filename"]))
        confirm, cancel = st.columns(2)
        with confirm:
            if st.button(
                "Confirm delete",
                key="library_confirm_delete",
                type="primary",
            ):
                try:
                    file_missing = delete_library_document(
                        str(pending_id),
                        store,
                        documents_dir=documents_dir,
                    )
                except DocumentLibraryError as error:
                    st.error(str(error))
                else:
                    st.session_state.pop("library_delete_pending", None)
                    if st.session_state.get("library_view_document") == pending_id:
                        st.session_state.pop("library_view_document", None)
                    if file_missing:
                        st.session_state["library_delete_notice"] = (
                            "The PDF file was already missing; its library record was removed."
                        )
                    else:
                        st.session_state["library_delete_notice"] = (
                            "The document and its extracted text were deleted."
                        )
                    st.rerun()
        with cancel:
            if st.button("Cancel", key="library_cancel_delete"):
                st.session_state.pop("library_delete_pending", None)
                st.rerun()


def _render_pdf_preview(
    store: SQLiteStore,
    documents: list[dict[str, object]],
    documents_dir: Path,
) -> None:
    """Show the selected original PDF in a browser-native embedded viewer."""
    document_id = st.session_state.get("library_view_document")
    if not document_id:
        return
    selected = next(
        (item for item in documents if item["document_id"] == document_id),
        None,
    )
    if selected is None:
        st.session_state.pop("library_view_document", None)
        return

    st.subheader("Reading selected PDF")
    st.caption(str(selected["original_filename"]))
    try:
        pdf_bytes = read_library_pdf(
            str(document_id),
            store,
            documents_dir=documents_dir,
        )
    except DocumentLibraryError as error:
        st.error(str(error))
        return
    if getattr(st, "pdf", None) is not None and find_spec("streamlit_pdf") is not None:
        st.pdf(
            pdf_bytes,
            height=720,
            key=f"library_preview_{document_id}",
            alt=f"PDF preview of {selected['original_filename']}",
        )
    else:
        st.info(
            "This installation does not include the optional embedded PDF viewer. "
            "Download the original PDF to read it with full formatting."
        )
    st.download_button(
        "Download original PDF",
        data=pdf_bytes,
        file_name=str(selected["original_filename"]),
        mime="application/pdf",
        key=f"library_download_{document_id}",
    )


def render(
    store: SQLiteStore | None = None,
    *,
    documents_dir: Path = DOCUMENT_LIBRARY_DIR,
) -> None:
    """Render upload, persisted library records, and the selected PDF preview."""
    render_disclaimer()
    store = store or SQLiteStore()
    create_schema(store)
    render_header(
        "Document Library",
        "",
        "OPERATE  /  REFERENCE DOCUMENTS",
    )
    delete_notice = st.session_state.pop("library_delete_notice", None)
    if delete_notice:
        st.info(delete_notice)
    _render_upload(store, documents_dir)
    st.divider()
    documents = list_library_documents(store)
    _render_document_list(documents, store, documents_dir)
    _render_pdf_preview(store, documents, documents_dir)
