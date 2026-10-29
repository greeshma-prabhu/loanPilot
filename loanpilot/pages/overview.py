"""Portfolio analytics and recent document updates for the lending workspace."""

import calendar
from html import escape

import pandas as pd
import plotly.express as px
import streamlit as st

from loanpilot.components import status_chip
from loanpilot.data.document_library import (
    format_document_upload_time,
    is_document_summary_current,
    list_library_documents,
)
from loanpilot.data.queries import overview_attention_cases
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore
from loanpilot.theme import render_disclaimer, render_header

_STATUSES = ("Approved", "Rejected", "Pending")
_STATUS_COLORS = {
    "Approved": "#138b83",
    "Rejected": "#bd6964",
    "Pending": "#d99a32",
}
_APPROVED_STAGES = {"Approved", "Sanction", "Disbursed (simulated)"}
_APPROVAL_DECISIONS = {"Approve", "Approve with conditions", "Modify terms"}


def _portfolio_records(store: SQLiteStore) -> pd.DataFrame:
    """Fetch one persisted row per application with its current workflow stage."""
    records = store.query(
        """
        SELECT a.application_id, a.submitted_at, a.stage, d.human_decision
        FROM cur_applications a
        LEFT JOIN cur_decisions d ON d.application_id = a.application_id
        WHERE a.persona_key IS NULL
          AND a.application_id NOT LIKE 'APP-HIST-%'
          AND a.application_id NOT LIKE 'APP-CUSTOM-%'
        ORDER BY a.application_id
        """
    )
    if records.empty:
        return pd.DataFrame(
            columns=[
                "application_id",
                "submitted_at",
                "stage",
                "human_decision",
                "date",
                "year",
                "month",
                "status",
            ]
        )

    records = records.drop_duplicates("application_id").copy()
    # Use the calendar date persisted at intake; decision dates do not move a
    # case into another month when the current status changes.
    records["date"] = pd.to_datetime(
        records["submitted_at"].astype(str).str.slice(0, 10),
        format="%Y-%m-%d",
        errors="coerce",
    )
    records = records.loc[records["date"].notna()].copy()
    records["year"] = records["date"].dt.year.astype(int)
    records["month"] = records["date"].dt.month.astype(int)

    # Portfolio periods are application-submission cohorts; each cohort reflects
    # the current persisted stage, so later decisions do not shift its month.
    stages = records["stage"].fillna("").astype(str)
    decisions = records["human_decision"].fillna("").astype(str)
    records["status"] = "Pending"
    approved = stages.isin({"Approved", "Disbursed (simulated)"}) | (
        stages.eq("Sanction") & decisions.isin(_APPROVAL_DECISIONS)
    )
    records.loc[approved, "status"] = "Approved"
    records.loc[stages.eq("Rejected"), "status"] = "Rejected"
    return records


def _monthly_counts(records: pd.DataFrame, year: int) -> pd.DataFrame:
    """Return twelve real calendar periods with current-status counts."""
    months = pd.DataFrame(
        [
            {"month": month, "status": status, "count": 0}
            for month in range(1, 13)
            for status in _STATUSES
        ]
    )
    if records.empty:
        return months
    actual = (
        records.loc[records["year"] == year]
        .groupby(["month", "status"], as_index=False)["application_id"]
        .nunique()
        .rename(columns={"application_id": "count"})
    )
    counts = months.drop(columns="count").merge(
        actual,
        on=["month", "status"],
        how="left",
    )
    counts["count"] = counts["count"].fillna(0).astype(int)
    counts["period"] = counts["month"].map(lambda month: calendar.month_abbr[month])
    return counts


def _render_portfolio_analytics(store: SQLiteStore) -> None:
    """Render the monthly status chart and the selected-year status summary."""
    st.subheader("Loan Portfolio Analytics")
    records = _portfolio_records(store)
    if records.empty:
        st.info("Portfolio analytics will appear when dated loan applications are available.")
        return

    years = sorted(records["year"].unique().tolist(), reverse=True)
    selected_year = st.selectbox(
        "Application year",
        years,
        format_func=str,
        key="overview_portfolio_year",
    )
    monthly = _monthly_counts(records, int(selected_year))
    monthly["period"] = pd.Categorical(
        monthly["period"],
        categories=[calendar.month_abbr[month] for month in range(1, 13)],
        ordered=True,
    )
    with st.container(key="overview_portfolio_layout"):
        chart_column, summary_column = st.columns([3, 1])
        with chart_column:
            chart = px.bar(
                monthly,
                x="period",
                y="count",
                color="status",
                custom_data=["period", "status", "count"],
                category_orders={
                    "period": [calendar.month_abbr[month] for month in range(1, 13)],
                    "status": list(_STATUSES),
                },
                color_discrete_map=_STATUS_COLORS,
                labels={"period": "Application month", "count": "Applications", "status": ""},
            )
            chart.update_traces(
                hovertemplate="%{x}<br>%{customdata[1]}: %{customdata[2]}<extra></extra>"
            )
            chart.update_layout(
                barmode="stack",
                showlegend=False,
                yaxis_title="Applications",
                xaxis_title="",
                margin={"l": 8, "r": 8, "t": 12, "b": 8},
                plot_bgcolor="white",
                paper_bgcolor="white",
            )
            chart.update_yaxes(rangemode="tozero", dtick=1)
            st.plotly_chart(
                chart,
                width="stretch",
                key="overview_portfolio_monthly",
            )
        with summary_column:
            st.markdown(f"#### Status summary · {selected_year}")
            totals = monthly.groupby("status", observed=False)["count"].sum()
            for status in _STATUSES:
                st.markdown(
                    f'<div style="display:flex;align-items:center;justify-content:space-between;'
                    f'gap:.5rem;padding:.7rem 0;border-bottom:1px solid #e1e7e9">'
                    f'<span><span style="color:{_STATUS_COLORS[status]}">●</span> {status}</span>'
                    f'<strong>{int(totals.get(status, 0))}</strong></div>',
                    unsafe_allow_html=True,
                )
            st.caption(f"{int(monthly['count'].sum())} applications in this year")


def _render_latest_updates(store: SQLiteStore) -> None:
    """Display persisted document summaries, newest uploaded source first."""
    st.subheader("Latest Updates")
    documents = list_library_documents(store)
    updates = [
        document
        for document in documents
        if str(document.get("summary_status", "Not requested")) != "Not requested"
    ]
    if not updates:
        st.info("Document summaries will appear here after a PDF is uploaded.")
        return

    for update in updates:
        status = str(update.get("summary_status", "Not requested"))
        with st.container(border=True):
            if is_document_summary_current(update):
                headline = escape(str(update.get("summary_headline", "")))
                st.markdown(f"**{headline}**")
                summary = escape(str(update.get("summary_text", "")))
                st.markdown(
                    f'<p class="lp-update-summary">{summary}</p>',
                    unsafe_allow_html=True,
                )
            elif status == "Completed":
                st.caption("Summary needs refreshing")
                st.write("Refresh this summary from the Document Library.")
            else:
                status_label = "Processing" if status == "Processing" else "Failed"
                st.caption(status_label)
                if status == "Failed":
                    st.write(
                        "A readable summary is unavailable. Check the PDF text or upload an OCR-readable document."
                    )
            st.caption(format_document_upload_time(update.get("uploaded_at")))


def _open_case(application_id: str) -> None:
    """Select a case and open its Applications workspace."""
    from loanpilot.navigation import OPERATE_PAGES

    st.session_state["selected_application"] = application_id
    st.switch_page(OPERATE_PAGES["applications"])


def _render_attention(store: SQLiteStore) -> None:
    """Show high-attention cases with direct links to their application records."""
    cases = overview_attention_cases(store)
    if cases.empty:
        st.info("No cases are currently awaiting human review.")
        return
    for _, case in cases.iterrows():
        recommendation = str(case.get("ai_recommendation") or "").strip()
        risk_band = str(case.get("risk_band") or "").strip()
        priority = risk_band or "Unspecified"
        priority_kind = (
            "danger"
            if priority.casefold() in {"high", "critical", "very high"}
            else "warning"
            if priority != "Unspecified"
            else "neutral"
        )
        submitted_at = pd.to_datetime(
            case.get("submitted_at"),
            utc=True,
            errors="coerce",
        )
        days_pending = (
            max(0, (pd.Timestamp.now(tz="UTC") - submitted_at).days)
            if not pd.isna(submitted_at)
            else None
        )
        with st.container(border=True):
            details, action = st.columns([5, 1])
            with details:
                st.markdown(f"**{escape(str(case['applicant']))}**")
                issue = (
                    f"AI recommendation: {escape(recommendation)}"
                    if recommendation
                    else "Awaiting an assessment recommendation"
                )
                st.markdown(
                    f'<div class="lp-attention-issue">{issue}</div>',
                    unsafe_allow_html=True,
                )
                age = (
                    f"{days_pending} days pending"
                    if days_pending is not None
                    else "Waiting time unavailable"
                )
                st.markdown(
                    f'<div class="lp-attention-meta">'
                    f'<span>Stage · Human Review</span>'
                    f'<span>{age}</span>'
                    f'<span>Priority · {escape(priority)}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with action:
                st.markdown(
                    status_chip(priority, priority_kind),
                    unsafe_allow_html=True,
                )
                st.button(
                    "Open",
                    key=f"overview_open_{case['application_id']}",
                    on_click=_open_case,
                    args=(str(case["application_id"]),),
                    width="stretch",
                )


def render(store: SQLiteStore | None = None) -> None:
    """Render the focused portfolio command centre."""
    render_disclaimer()
    store = store or SQLiteStore()
    create_schema(store)
    render_header(
        "Overview",
        "Loan portfolio performance and lending intelligence.",
        "OPERATE  /  COMMAND CENTRE",
    )
    _render_portfolio_analytics(store)
    _render_latest_updates(store)
    st.subheader("Needs Your Attention")
    _render_attention(store)
