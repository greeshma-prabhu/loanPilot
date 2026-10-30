"""Portfolio analytics and recent document updates for the lending workspace."""

import calendar
from html import escape

import pandas as pd
import plotly.express as px
import streamlit as st

from loanpilot.components import fmt_inr, status_chip
from loanpilot.data.document_library import format_document_upload_time
from loanpilot.data.notifications import (
    format_relative_upload_time,
    list_document_notifications,
    mark_all_document_notifications_read,
    mark_document_notification_read,
    unread_document_notification_count,
)
from loanpilot.data.queries import (
    overview_attention_cases,
    overview_dashboard_records,
)
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore
from loanpilot.theme import format_datetime, render_disclaimer

_STATUSES = ("Approved", "Rejected", "Pending")
_STATUS_COLORS = {
    "Approved": "#138b83",
    "Rejected": "#bd6964",
    "Pending": "#d99a32",
}
_APPROVED_STAGES = {"Approved", "Sanction", "Disbursed (simulated)"}
_APPROVAL_DECISIONS = {"Approve", "Approve with conditions", "Modify terms"}


def _display_text(value: object, default: str = "") -> str:
    """Convert optional database values without exposing pandas null markers."""
    if value is None or pd.isna(value):
        return default
    return str(value).strip() or default


def _format_optional_amount(value: object) -> str:
    """Format a requested amount when present, otherwise show a clear fallback."""
    amount = pd.to_numeric(value, errors="coerce")
    return fmt_inr(float(amount)) if pd.notna(amount) else "Unavailable"


def _portfolio_records(store: SQLiteStore) -> pd.DataFrame:
    """Fetch operational and explicitly seeded synthetic application rows."""
    records = overview_dashboard_records(store)
    if records.empty:
        return pd.DataFrame(
            columns=[
                "application_id",
                "applicant",
                "requested_amount",
                "submitted_at",
                "stage",
                "human_decision",
                "ai_recommendation",
                "risk_band",
                "attention_reason",
                "is_synthetic",
                "date",
                "year",
                "month",
                "status",
            ]
        )
    records = records.drop_duplicates("application_id").copy()
    records["date"] = pd.to_datetime(
        records["submitted_at"].astype(str).str.slice(0, 10),
        format="%Y-%m-%d",
        errors="coerce",
    )
    records["year"] = records["date"].dt.year.astype("Int64")
    records["month"] = records["date"].dt.month.astype("Int64")
    stages = records["stage"].fillna("").astype(str)
    decisions = records["human_decision"].fillna("").astype(str)
    records["status"] = "Pending"
    approved = stages.isin(_APPROVED_STAGES) | (
        stages.eq("Sanction")
        & decisions.isin(_APPROVAL_DECISIONS)
    )
    records.loc[approved, "status"] = "Approved"
    records.loc[
        stages.eq("Rejected") | decisions.isin({"Reject", "Decline"}),
        "status",
    ] = "Rejected"
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
        records.loc[records["year"].eq(year).fillna(False)]
        .dropna(subset=["month"])
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
    counts["period"] = counts["month"].map(
        lambda month: calendar.month_abbr[int(month)]
    )
    return counts


def _render_portfolio_analytics(store: SQLiteStore) -> None:
    """Render dated monthly volumes and the persisted portfolio status mix."""
    st.subheader("Application Trends")
    records = _portfolio_records(store)
    if records.empty:
        st.info("Application trends will appear when applications are submitted.")
        return

    dated = records.dropna(subset=["year", "month"])
    status_counts = (
        records.groupby("status")["application_id"]
        .nunique()
        .reindex(_STATUSES, fill_value=0)
        .rename("count")
        .reset_index()
    )
    with st.container(key="overview_portfolio_layout"):
        trend_column, distribution_column = st.columns([1.55, 1], gap="large")
        with trend_column:
            st.markdown("#### Monthly volume")
            if dated.empty:
                st.info("Monthly volume is unavailable because application dates are missing or invalid.")
            else:
                years = sorted(dated["year"].dropna().astype(int).unique().tolist(), reverse=True)
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
                    labels={
                        "period": "Application month",
                        "count": "Applications",
                        "status": "",
                    },
                )
                chart.update_traces(
                    hovertemplate="%{x}<br>%{customdata[1]}: %{customdata[2]}<extra></extra>"
                )
                chart.update_layout(
                    barmode="stack",
                    showlegend=True,
                    legend={"orientation": "h", "y": 1.12, "x": 0},
                    yaxis_title="Applications",
                    xaxis_title="",
                    margin={"l": 8, "r": 8, "t": 24, "b": 8},
                    plot_bgcolor="white",
                    paper_bgcolor="white",
                )
                chart.update_yaxes(rangemode="tozero", dtick=1)
                st.plotly_chart(
                    chart,
                    width="stretch",
                    key="overview_portfolio_monthly",
                )
        with distribution_column:
            st.markdown("#### Status distribution")
            distribution = px.pie(
                status_counts,
                names="status",
                values="count",
                hole=0.62,
                color="status",
                color_discrete_map=_STATUS_COLORS,
            )
            distribution.update_layout(
                showlegend=True,
                legend={"orientation": "h", "y": -0.08, "x": 0},
                margin={"l": 8, "r": 8, "t": 10, "b": 28},
                plot_bgcolor="white",
                paper_bgcolor="white",
            )
            st.plotly_chart(
                distribution,
                width="stretch",
                key="overview_status_distribution",
            )
    undated_count = int(records["date"].isna().sum())
    if undated_count:
        st.caption(
            "Applications with missing or invalid dates are excluded from monthly trends."
        )


def _read_notification(document_id: str, store: SQLiteStore) -> None:
    """Expand one notification and persist its read state."""
    st.session_state[f"overview_notification_expanded_{document_id}"] = True
    mark_document_notification_read(document_id, store)


def _collapse_notification(document_id: str) -> None:
    """Collapse one notification without changing its persisted read state."""
    st.session_state[f"overview_notification_expanded_{document_id}"] = False


def _notification_preview(summary: str, limit: int = 132) -> str:
    """Keep initial notification cards compact and free of line-break noise."""
    preview = " ".join(summary.split())
    if len(preview) <= limit:
        return preview
    return preview[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"


def _render_notification_panel(store: SQLiteStore) -> None:
    """Render a compact, dismissible notification panel in the Overview header."""
    notifications = list_document_notifications(store)
    unread_count = unread_document_notification_count(store)
    bell_color = "#ff6b6b" if unread_count else "#ffffff"
    st.markdown(
        f"""
        <style>
        .st-key-overview_notification_toggle button {{
            min-width: 2.75rem;
            min-height: 2.75rem;
            background: #173b57 !important;
            border-color: #173b57 !important;
            color: #ffffff !important;
        }}
        .st-key-overview_notification_toggle button p {{
            display: grid;
            place-items: center;
            min-width: 1.15rem;
            height: 1.15rem;
            margin: 0;
            padding: 0 .25rem;
            border-radius: 999px;
            background: #ffffff;
            color: #b91c1c !important;
            -webkit-text-fill-color: #b91c1c !important;
            font-size: .75rem;
            font-weight: 750;
            line-height: 1;
        }}
        .st-key-overview_notification_toggle button [data-testid="stIconMaterial"],
        .st-key-overview_notification_toggle button .material-symbols-rounded {{
            color: {bell_color} !important;
            -webkit-text-fill-color: {bell_color} !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    if st.button(
        str(unread_count) if unread_count else "",
        icon=":material/notifications:",
        help="Document notifications",
        key="overview_notification_toggle",
    ):
        st.session_state["overview_notifications_open"] = not bool(
            st.session_state.get("overview_notifications_open", False)
        )
        st.rerun()

    if st.session_state.get("overview_notifications_open", False):
        st.markdown(
            """
            <style>
            .st-key-overview_notification_panel {
                position: fixed !important;
                z-index: 1000 !important;
                top: 10rem !important;
                right: max(1rem, calc((100vw - 1280px) / 2 + 1rem)) !important;
                width: min(420px, calc(100vw - 2rem)) !important;
                max-height: min(70vh, 620px) !important;
                overflow-y: auto !important;
                padding: 1rem !important;
                border: 1px solid #dfe7e9 !important;
                border-radius: 16px !important;
                background: #fff !important;
                box-shadow: 0 16px 40px rgba(18, 45, 59, .2) !important;
            }
            @media (max-width: 760px) {
                .st-key-overview_notification_panel {
                    top: 7rem !important;
                    right: .75rem !important;
                    width: calc(100vw - 1.5rem) !important;
                    max-height: 76vh !important;
                }
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        with st.container(key="overview_notification_panel"):
            heading, close = st.columns([5, 1], gap="large")
            with heading:
                st.markdown("#### Document updates")
            with close:
                if st.button(
                    "",
                    icon=":material/close:",
                    help="Close notifications",
                    key="overview_notifications_close",
                ):
                    st.session_state["overview_notifications_open"] = False
                    st.rerun()
            if not notifications:
                st.info("No new document updates.")
                return
            if st.button(
                "Mark all as read",
                key="overview_notifications_mark_all_read",
                disabled=not unread_count,
                width="stretch",
            ):
                mark_all_document_notifications_read(store)
                st.rerun()
            for notification in notifications:
                document_id = str(notification["document_id"])
                headline = str(notification.get("headline") or "Document update")
                summary = str(notification.get("summary") or "")
                read_at = notification.get("read_at")
                expanded = bool(
                    st.session_state.get(
                        f"overview_notification_expanded_{document_id}",
                        False,
                    )
                )
                with st.container(border=True):
                    st.markdown(f"**{escape(headline)}**")
                    st.caption(
                        f"{'● Unread · ' if read_at is None else ''}"
                        f"{format_relative_upload_time(notification.get('uploaded_at'))}"
                    )
                    if expanded:
                        st.markdown(
                            f'<p class="lp-update-summary">{escape(summary)}</p>',
                            unsafe_allow_html=True,
                        )
                        st.caption(
                            f"{notification.get('original_filename', 'Document')} · "
                            f"{format_document_upload_time(notification.get('uploaded_at'))}"
                        )
                        st.button(
                            "Show less",
                            key=f"overview_notification_collapse_{document_id}",
                            on_click=_collapse_notification,
                            args=(document_id,),
                        )
                    else:
                        preview = escape(_notification_preview(summary))
                        st.markdown(
                            f'<p class="lp-update-summary">{preview}</p>',
                            unsafe_allow_html=True,
                        )
                        st.button(
                            "Read more",
                            key=f"overview_notification_expand_{document_id}",
                            on_click=_read_notification,
                            args=(document_id, store),
                        )


def _open_case(application_id: str) -> None:
    """Select a case and open its Applications workspace."""
    from loanpilot.navigation import OPERATE_PAGES

    st.session_state["selected_application"] = application_id
    st.switch_page(OPERATE_PAGES["applications"])


def _open_human_review(application_id: str) -> None:
    """Select a case and open the Human Review worklist."""
    from loanpilot.navigation import OPERATE_PAGES

    st.session_state["selected_application"] = application_id
    st.session_state["review_open"] = application_id
    st.switch_page(OPERATE_PAGES["human_review"])


def _render_kpis(records: pd.DataFrame) -> None:
    """Render portfolio totals from the same status rows used by the charts."""
    counts = records["status"].value_counts() if not records.empty else {}
    metrics = (
        ("Total Applications", len(records)),
        ("Approved Applications", int(counts.get("Approved", 0))),
        ("Pending Applications", int(counts.get("Pending", 0))),
        ("Rejected Applications", int(counts.get("Rejected", 0))),
    )
    with st.container(key="overview_kpis"):
        columns = st.columns(4, gap="large")
        for column, (label, value) in zip(columns, metrics, strict=True):
            column.metric(label, f"{value:,}")


def _render_attention(store: SQLiteStore) -> None:
    """Show supported attention reasons and direct operational actions."""
    cases = overview_attention_cases(store)
    if cases.empty:
        st.info("No applications currently need a follow-up.")
        return
    for _, case in cases.iterrows():
        recommendation = _display_text(case.get("ai_recommendation"))
        risk_band = _display_text(case.get("risk_band"))
        priority = (
            _display_text(case.get("attention_priority"))
            or risk_band
            or "Unspecified"
        )
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
        stage = _display_text(case.get("stage"), "Unknown")
        days_pending = (
            max(0, (pd.Timestamp.now(tz="UTC") - submitted_at).days)
            if not pd.isna(submitted_at)
            else None
        )
        with st.container(border=True):
            details, action = st.columns([5, 1.2], gap="large")
            with details:
                applicant = _display_text(
                    case.get("applicant"),
                    "Applicant unavailable",
                )
                st.markdown(f"**{escape(applicant)}**")
                issue = _display_text(case.get("attention_reason"))
                if not issue:
                    issue = (
                        f"AI recommendation: {recommendation}"
                        if recommendation
                        else "Awaiting an assessment recommendation"
                    )
                st.markdown(
                    f'<div class="lp-attention-issue">{escape(issue)}</div>',
                    unsafe_allow_html=True,
                )
                age = (
                    f"{days_pending} days pending"
                    if days_pending is not None
                    else "Waiting time unavailable"
                )
                st.markdown(
                    f'<div class="lp-attention-meta">'
                    f'<span>Stage · {escape(stage)}</span>'
                    f'<span>{escape(_display_text(case.get("application_id"), "ID unavailable"))}</span>'
                    f'<span>Requested · {escape(_format_optional_amount(case.get("requested_amount")))}</span>'
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
                    "Open case",
                    key=f"overview_open_{_display_text(case.get('application_id'), 'unknown')}",
                    on_click=_open_case,
                    args=(_display_text(case.get("application_id")),),
                    width="stretch",
                )
                if stage == "Human Review":
                    st.button(
                        "Human Review",
                        key=f"overview_review_{_display_text(case.get('application_id'), 'unknown')}",
                        on_click=_open_human_review,
                        args=(_display_text(case.get("application_id")),),
                        width="stretch",
                    )


def _render_recent_applications(records: pd.DataFrame) -> None:
    """Display five most recently submitted cases with direct case navigation."""
    st.subheader("Recent Applications")
    if records.empty:
        st.info("Submitted applications will appear here.")
        return
    recent = records.sort_values(
        ["date", "submitted_at", "application_id"],
        ascending=[False, False, False],
        na_position="last",
    ).head(5)
    for _, application in recent.iterrows():
        stage = _display_text(application.get("stage"), "Unknown")
        status = _display_text(application.get("status"), "Pending")
        status_kind = (
            "success" if status == "Approved"
            else "danger" if status == "Rejected"
            else "warning"
        )
        risk = _display_text(application.get("risk_band"))
        attention = _display_text(application.get("attention_reason"))
        label = risk or ("Needs attention" if attention else "No attention flag")
        with st.container(border=True):
            details, action = st.columns([5, 1], gap="large")
            with details:
                applicant = _display_text(
                    application.get("applicant"),
                    "Applicant unavailable",
                )
                st.markdown(f"**{escape(applicant)}**")
                st.caption(
                    f"{escape(_display_text(application.get('application_id'), 'ID unavailable'))} · "
                    f"{escape(_format_optional_amount(application.get('requested_amount')))} · "
                    f"{format_datetime(application.get('submitted_at'))}"
                )
                st.markdown(
                    f'{status_chip(status, status_kind)} '
                    f'{status_chip(stage, "info")} '
                    f'{status_chip(label, "warning" if attention else "neutral")}',
                    unsafe_allow_html=True,
                )
                if int(application.get("is_synthetic") or 0):
                    st.caption("Synthetic demo record · not a real customer or decision")
            with action:
                st.button(
                    "Open",
                    key=f"overview_recent_open_{_display_text(application.get('application_id'), 'unknown')}",
                    on_click=_open_case,
                    args=(_display_text(application.get("application_id")),),
                    width="stretch",
                )


def render(store: SQLiteStore | None = None) -> None:
    """Render the persisted application dashboard and its operational actions."""
    render_disclaimer()
    store = store or SQLiteStore()
    create_schema(store)
    records = _portfolio_records(store)
    identity = st.session_state.get("auth") or {}
    first_name = str(identity.get("name") or "").strip().split(" ", 1)[0]
    title = f"Welcome back, {first_name}" if first_name else "Welcome back"
    st.markdown(
        '<div class="lp-eyebrow">OPERATE  /  COMMAND CENTRE</div>',
        unsafe_allow_html=True,
    )
    title_column, notification_column = st.columns([8, 1], gap="large")
    with title_column:
        st.title(title)
    with notification_column:
        _render_notification_panel(store)
    st.markdown(
        '<div class="lp-subtitle">Your lending portfolio at a glance. '
        "Review application trends and take action on cases that need attention.</div>",
        unsafe_allow_html=True,
    )
    _render_kpis(records)
    _render_portfolio_analytics(store)
    st.subheader("Needs Your Attention")
    _render_attention(store)
    _render_recent_applications(records)
