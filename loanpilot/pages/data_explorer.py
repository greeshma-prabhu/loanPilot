"""Read-only browser for the local demo data layers."""

import pandas as pd
import streamlit as st

from loanpilot.components import fmt_inr
from loanpilot.data.queries import (
    explorer_catalog,
    run_canned_read_query,
)
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore
from loanpilot.theme import format_datetime, render_disclaimer, render_header

_DICTIONARY = [
    {"Field": "application_id", "Meaning": "Unique synthetic identifier for a loan request."},
    {"Field": "customer_id", "Meaning": "Unique synthetic identifier for an applicant."},
    {"Field": "stage", "Meaning": "Current workflow position, such as Submitted or Human Review."},
    {"Field": "net_monthly_income", "Meaning": "Applicant's declared monthly take-home income in rupees."},
    {"Field": "bureau_score", "Meaning": "Synthetic bureau score; blank means a thin file."},
    {"Field": "foir", "Meaning": "Fixed obligations-to-income ratio: existing and proposed EMIs divided by income."},
    {"Field": "ai_recommendation", "Meaning": "Deterministic policy outcome: Approve, Refer or Decline."},
]

_LAYERS = {
    "RAW": "Evidence and responses as received.",
    "CURATED": "Cleaned, linked applicant, application and decision records.",
    "SERVING": "Joined features prepared for the decision workflow.",
}


def _format_explorer_values(frame: pd.DataFrame) -> pd.DataFrame:
    """Return user-facing values with Indian currency and readable dates."""
    formatted = frame.copy()
    friendly_names = {
        "stage": "Stage",
        "name": "Applicant",
        "city": "City",
        "doc_type": "Document type",
        "document_count": "Documents",
        "net_monthly_income": "Monthly income",
        "requested_amount": "Requested amount",
        "approved_amount": "Approved amount",
        "emi": "EMI",
        "foir": "FOIR",
        "bureau_score": "Bureau score",
        "submitted_at": "Submitted",
        "uploaded_at": "Uploaded",
        "created_at": "Created",
        "decided_at": "Decision date",
    }
    for column in formatted.columns:
        normalized = column.casefold()
        if normalized.endswith(("_at", "_on", "_date")) or normalized in {"dob", "date"}:
            formatted[column] = formatted[column].map(format_datetime)
        elif (
            any(term in normalized for term in ("amount", "income", "emi", "fee", "balance", "salary", "outstanding"))
            and not any(term in normalized for term in ("count", "months", "score"))
            and pd.api.types.is_numeric_dtype(formatted[column])
        ):
            formatted[column] = formatted[column].map(
                lambda value: fmt_inr(value) if pd.notna(value) else "—"
            )
    return formatted.rename(
        columns={column: friendly_names[column] for column in formatted.columns if column in friendly_names}
    )


def _render_sample(frame: pd.DataFrame) -> None:
    """Show friendly values and keep the original fields behind an expander."""
    technical_columns = [
        column for column in frame.columns
        if column.casefold() == "id"
        or column.casefold().endswith("_id")
        or "payload" in column.casefold()
        or "json" in column.casefold()
        or column.casefold() in {"text_content", "file_path"}
    ]
    visible = _format_explorer_values(frame.drop(columns=technical_columns))
    if visible.shape[1]:
        st.dataframe(visible, width="stretch", hide_index=True)
    if not frame.empty:
        with st.expander("Show raw fields"):
            st.dataframe(frame, width="stretch", hide_index=True)


def _render_layer(layer: str, objects: list[dict]) -> None:
    """Render object descriptions, row counts and a bounded sample."""
    st.markdown(f"#### {layer.title()}")
    st.caption(_LAYERS[layer])
    if not objects:
        st.info("No objects are available in this layer.")
        return
    for item in objects:
        with st.expander(
            f"{item['name']} · {item['row_count']:,} rows",
            expanded=False,
        ):
            st.write(item["description"])
            if item["sample"].empty:
                st.caption("No rows are present.")
            else:
                _render_sample(item["sample"])


def render(store: SQLiteStore | None = None) -> None:
    """Render the schema browser, dictionary, lineage and safe canned queries."""
    render_disclaimer()
    store = store or SQLiteStore()
    create_schema(store)
    render_header(
        "Data Explorer",
        "Browse what is stored, where it came from, and how the layers connect.",
        "EXPLAIN  /  DATA EXPLORER",
    )
    st.info("Local SQLite stand-in with the same schema · up to five sample rows per object.")
    catalog = explorer_catalog(store)
    tabs = st.tabs(["RAW · as received", "CURATED · joined", "SERVING · features"])
    for tab, layer in zip(tabs, ("raw", "curated", "serving"), strict=True):
        with tab:
            _render_layer(layer.upper(), catalog[layer])

    st.subheader("Small data dictionary")
    st.dataframe(_DICTIONARY, width="stretch", hide_index=True)

    st.subheader("Lineage")
    st.write(
        "Uploaded documents and mock bureau/KYC responses enter RAW. Customer, "
        "transaction and application records are kept in CURATED tables. The "
        "SERVING view joins these sources to calculate income, proposed EMI, FOIR, "
        "bureau score and document flags for the assessment workflow."
    )
    st.subheader("Canned read-only queries")
    query_name = st.selectbox(
        "Choose a query",
        ("Recent applications", "Customer income sample", "Document inventory"),
        key="explorer_query",
    )
    st.caption("These fixed SELECT queries are read-only and capped at 10 rows.")
    try:
        result = run_canned_read_query(query_name, store)
    except ValueError as error:
        st.error(f"Could not run the selected read-only query: {error}")
    else:
        _render_sample(result)
