"""Database-backed LoanPilot portfolio and workflow dashboard."""

import json

import pandas as pd
import plotly.express as px
import streamlit as st

from loanpilot import config
from loanpilot.agent.orchestrator import run_assessment
from loanpilot.components import render_decision_card, render_why
from loanpilot.data.queries import (
    list_applications,
    overview_attention_cases,
    overview_metrics,
    overview_pipeline_counts,
    overview_recommendation_counts,
    overview_risk_counts,
)
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore
from loanpilot.ledger import ledger_counts, ledger_frame
from loanpilot.theme import render_disclaimer, render_header


def _start_guided_demo(store: SQLiteStore) -> None:
    """Open Priya's seeded case in the Applications workspace."""
    from loanpilot.navigation import OPERATE_PAGES

    sample = list_applications({"demo_only": True}, store)
    priya = sample.loc[sample["applicant"] == "Priya Menon"]
    if priya.empty:
        st.session_state["overview_notice"] = "Priya's demo case is not loaded yet."
        return
    application_id = str(priya.iloc[0]["application_id"])
    st.session_state["selected_application"] = application_id
    st.switch_page(OPERATE_PAGES["applications"])


def _open_review_case(application_id: str) -> None:
    """Open Human Review with a selected queue case."""
    from loanpilot.navigation import OPERATE_PAGES

    st.session_state["review_application"] = application_id
    st.session_state["selected_application"] = application_id
    st.switch_page(OPERATE_PAGES["human_review"])


def _prepare_demo(store: SQLiteStore, leave_priya_unassessed: bool = True) -> tuple[int, int]:
    """Assess missing persona cases once, optionally reserving Priya for a live demo."""
    counts = store.table_counts()
    if not counts.get("cur_applications", 0):
        if counts.get("cur_customers", 0):
            raise ValueError(
                "The database has customers but no applications; demo cases were not reset."
            )
        seed_demo_data(store)

    cases = list_applications({"demo_only": True}, store)
    if cases.empty:
        raise ValueError("No demo personas are available to assess.")
    assessed = 0
    skipped = 0
    for _, case in cases.iterrows():
        if leave_priya_unassessed and case["applicant"] == "Priya Menon":
            skipped += 1
            continue
        recommendation = case["ai_recommendation"]
        if pd.notna(recommendation) and str(recommendation).strip():
            skipped += 1
            continue
        run_assessment(str(case["application_id"]), store)
        assessed += 1
    return assessed, skipped


def _run_prepare_demo(store: SQLiteStore) -> None:
    """Run the Overview action and report the resulting case counts."""
    try:
        assessed, skipped = _prepare_demo(
            store,
            bool(st.session_state.get("prepare_leave_priya_unassessed", True)),
        )
    except ValueError as error:
        st.error(f"Could not prepare demo cases: {error}")
        return
    st.toast(
        f"Demo ready: {assessed} new assessments, {skipped} unchanged or reserved cases."
    )


def _render_prepare_demo(store: SQLiteStore, assessment_count: int) -> None:
    """Show the repeat-safe assessment action and its default Priya reservation."""
    with st.container(border=True):
        st.subheader("Prepare demo")
        if assessment_count == 0:
            st.info(
                "No AI assessments are saved yet. Prepare the sample cases here; "
                "Priya can remain unassessed for a live walkthrough."
            )
        else:
            st.caption(
                "Fill in missing demo assessments. Saved outcomes are kept unchanged."
            )
        st.checkbox(
            "Leave Priya Menon unassessed for a live walkthrough",
            value=True,
            key="prepare_leave_priya_unassessed",
        )
        st.button(
            "Prepare demo",
            on_click=_run_prepare_demo,
            args=(store,),
            key="prepare_demo",
            type="primary",
            width="stretch",
        )


def _render_kpis(
    metrics: dict[str, float | int | None],
    assessment_count: int,
) -> None:
    """Render portfolio and workflow figures sourced from the database."""
    st.subheader("Portfolio at a glance")
    st.caption("All figures use synthetic data from the local database.")
    values = [
        ("Apps in pipeline", f"{int(metrics['pipeline_count'] or 0):,}"),
        ("AI approves", f"{int(metrics['approve_count'] or 0):,}" if assessment_count else "—"),
        ("AI referrals", f"{int(metrics['refer_count'] or 0):,}" if assessment_count else "—"),
        ("AI declines", f"{int(metrics['decline_count'] or 0):,}" if assessment_count else "—"),
        (
            "Avg. historical time",
            (
                f"{float(metrics['historical_processing_hours']) / 24:.1f} days"
                if metrics["historical_processing_hours"] is not None
                else "—"
            ),
        ),
        ("Human reviews pending", f"{int(metrics['pending_review_count'] or 0):,}"),
    ]
    for offset in range(0, len(values), 3):
        columns = st.columns(3)
        for column, (label, value) in zip(
            columns, values[offset : offset + 3], strict=True
        ):
            with column:
                st.metric(label, value, help="Computed from synthetic data in the local database.")
                if label.startswith("AI ") and assessment_count == 0:
                    st.caption("No assessments yet")


def _render_charts(store: SQLiteStore) -> None:
    """Render pipeline, recommendation, and risk charts from query results."""
    pipeline = overview_pipeline_counts(store)
    recommendations = overview_recommendation_counts(store)
    risks = overview_risk_counts(store)
    left, middle, right = st.columns(3)
    with left:
        st.markdown("#### Pipeline by stage")
        if pipeline.empty:
            st.info("No applications are currently in the pipeline.")
        else:
            figure = px.funnel(
                pipeline,
                x="application_count",
                y="stage",
                labels={"application_count": "Applications", "stage": "Stage"},
                color_discrete_sequence=["#16817b"],
            )
            figure.update_layout(margin=dict(l=4, r=8, t=8, b=4), height=310)
            st.plotly_chart(figure, width="stretch", key="overview_pipeline")
    with middle:
        st.markdown("#### AI decision mix")
        if recommendations.empty:
            st.info("No AI recommendations have been saved.")
        else:
            figure = px.pie(
                recommendations,
                names="recommendation",
                values="application_count",
                hole=0.56,
                color="recommendation",
                color_discrete_map={
                    "Approve": "#23866f",
                    "Refer": "#d69a2d",
                    "Decline": "#b95c52",
                },
            )
            figure.update_layout(margin=dict(l=4, r=4, t=8, b=4), height=310)
            st.plotly_chart(figure, width="stretch", key="overview_decisions")
    with right:
        st.markdown("#### Risk-band distribution")
        if risks.empty:
            st.info("Risk bands appear after an AI assessment.")
        else:
            figure = px.bar(
                risks,
                x="risk_band",
                y="application_count",
                color="risk_band",
                color_discrete_map={
                    "Low": "#23866f",
                    "Medium": "#d69a2d",
                    "High": "#b95c52",
                },
                labels={"risk_band": "Risk band", "application_count": "Cases"},
            )
            figure.update_layout(
                showlegend=False,
                margin=dict(l=4, r=4, t=8, b=4),
                height=310,
            )
            st.plotly_chart(figure, width="stretch", key="overview_risk")


def _render_attention(store: SQLiteStore) -> None:
    """Show review cases with direct callback navigation to the reviewer queue."""
    st.subheader("Needs your attention")
    cases = overview_attention_cases(store)
    if cases.empty:
        st.info("No cases are currently awaiting human review.")
        return
    for _, row in cases.iterrows():
        with st.expander(
            f"{row['applicant']} · {row['ai_recommendation'] or 'Pending'} · "
            f"{row['risk_band'] or 'Pending'}"
        ):
            render_decision_card(str(row["application_id"]), store, compact=True)
            render_why(str(row["application_id"]), store, compact=True)
            st.button(
                "Open Human Review",
                key=f"overview_review_{row['application_id']}",
                on_click=_open_review_case,
                args=(str(row["application_id"]),),
            )


def _render_turnaround_comparison() -> None:
    """Show declared illustrative comparison assumptions and their provenance."""
    with config.ILLUSTRATIVE_METRICS_PATH.open(encoding="utf-8") as metrics_file:
        assumptions = json.load(metrics_file)
    st.subheader("Turnaround comparison")
    st.caption("Illustrative assumptions only.")
    first, second = st.columns(2)
    first.metric("Illustrative baseline", f"{float(assumptions['baseline_turnaround_days']):g} days")
    second.metric("Illustrative demo workflow", f"{float(assumptions['demo_turnaround_days']):g} days")
    st.caption(str(assumptions["source"]))


def _render_implementation_status(store: SQLiteStore) -> None:
    """Render ledger status totals and component notes."""
    st.subheader("Implementation status")
    counts = ledger_counts(store)
    columns = st.columns(3)
    for column, status in zip(columns, ("Real", "Simulated", "Planned"), strict=True):
        column.metric(status, counts[status])
    st.dataframe(ledger_frame(store), width="stretch", hide_index=True)


def _render_closed_cases(metrics: dict[str, float | int | None]) -> None:
    """Make parked and completed outcomes visible in a compact card."""
    with st.container(border=True):
        st.subheader("Closed cases")
        columns = st.columns(3)
        columns[0].metric("Rejected", int(metrics["rejected_count"] or 0))
        columns[1].metric("Approved · awaiting payout", int(metrics["approved_count"] or 0))
        columns[2].metric("Disbursed", int(metrics["disbursed_count"] or 0))


def render(store: SQLiteStore | None = None) -> None:
    """Render the portfolio dashboard using current database contents."""
    render_disclaimer()
    store = store or SQLiteStore()
    create_schema(store)
    render_header(
        "Overview",
        "A clearer view from application intake to human-reviewed outcome.",
        "OPERATE  /  PORTFOLIO OVERVIEW",
    )
    notice = st.session_state.pop("overview_notice", None)
    if notice:
        st.warning(notice)
    count = int(store.table_counts().get("cur_applications", 0))
    applications = list_applications({"demo_only": True}, store)
    assessment_count = (
        int(
            (
                applications["ai_recommendation"].notna()
                & applications["ai_recommendation"].astype(str).str.strip().ne("")
            ).sum()
        )
        if not applications.empty
        else 0
    )
    _render_prepare_demo(store, assessment_count)
    metrics = overview_metrics(store)
    persisted_recommendations = sum(
        int(metrics[key] or 0)
        for key in ("approve_count", "refer_count", "decline_count")
    )
    _render_kpis(metrics, persisted_recommendations)
    if count == 0:
        st.info(
            "No synthetic applications are loaded yet. Prepare demo creates the "
            "sample portfolio and its assessments."
        )
        _render_implementation_status(store)
        return
    hero, action = st.columns([4, 1])
    with hero:
        st.markdown(
            "#### One guided view of the personal-loan journey — from synthetic evidence to human review."
        )
        st.caption("AI recommends; a human reviewer decides.")
    with action:
        st.button(
            "Start guided demo",
            on_click=_start_guided_demo,
            key="start_guided_demo",
            args=(store,),
            type="primary",
            width="stretch",
        )
    _render_charts(store)
    _render_attention(store)
    _render_closed_cases(metrics)
    _render_turnaround_comparison()
    _render_implementation_status(store)
