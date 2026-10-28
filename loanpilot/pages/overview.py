"""Command-centre overview for current demo and custom applications."""

import pandas as pd
import plotly.express as px
import streamlit as st

from loanpilot import config
from loanpilot.agent.orchestrator import run_assessment
from loanpilot.data.custom_cases import remove_custom_cases
from loanpilot.data.queries import (
    list_applications,
    overview_attention_cases,
    overview_cases,
    overview_historical_metrics,
)
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore
from loanpilot.ledger import ledger_counts, ledger_frame
from loanpilot.theme import format_datetime, render_disclaimer, render_header

_CLOSED_STAGES = {"Rejected", "Disbursed (simulated)", "Awaiting documents"}
_STORIES = {
    "PERSONA-1": "Consistent income and documents; strong bureau profile.",
    "PERSONA-2": "Borderline FOIR with one older late payment.",
    "PERSONA-3": "Monthly obligations exceed the illustrative limit.",
    "PERSONA-4": "Payslip, employer and salary-credit evidence differ.",
    "PERSONA-5": "Thin bureau file; a capped amount may be considered.",
    "PERSONA-6": "Short current-job tenure despite long work history.",
}


def _demo_custom_cases(store: SQLiteStore) -> pd.DataFrame:
    """Return only the six named personas and custom intake records."""
    cases = overview_cases(store)
    if cases.empty:
        return cases
    cases["case_type"] = cases.apply(
        lambda row: "Custom case" if str(row["application_id"]).startswith("APP-CUSTOM-") else "Persona",
        axis=1,
    )
    return cases


def _prepare_demo(store: SQLiteStore) -> tuple[int, int]:
    """Assess missing persona/custom cases idempotently while reserving Priya."""
    counts = store.table_counts()
    if not counts.get("cur_applications", 0):
        seed_demo_data(store)
    cases = _demo_custom_cases(store)
    assessed = 0
    skipped = 0
    for _, row in cases.iterrows():
        if row["applicant"] == "Priya Menon":
            skipped += 1
            continue
        if pd.notna(row["ai_recommendation"]) and str(row["ai_recommendation"]).strip():
            skipped += 1
            continue
        run_assessment(str(row["application_id"]), store)
        assessed += 1
    return assessed, skipped


def _start_demo(store: SQLiteStore) -> None:
    """Assess missing demo cases except Priya, then open her case."""
    from loanpilot.navigation import OPERATE_PAGES

    _prepare_demo(store)
    cases = _demo_custom_cases(store)
    priya = cases.loc[cases["applicant"] == "Priya Menon"]
    if priya.empty:
        st.session_state["overview_notice"] = "Priya Menon is not present in the demo data."
        return
    application_id = str(priya.iloc[0]["application_id"])
    st.session_state["selected_application"] = application_id
    st.switch_page(OPERATE_PAGES["applications"])


def _open_case(application_id: str) -> None:
    """Select a case and open its Applications workspace."""
    from loanpilot.navigation import OPERATE_PAGES

    st.session_state["selected_application"] = application_id
    st.switch_page(OPERATE_PAGES["applications"])


def _reset_demo(store: SQLiteStore) -> None:
    """Rebuild seeded personas, historical data and permanent custom cases."""
    counts = seed_demo_data(store, reset=True)
    st.session_state.pop("selected_application", None)
    st.toast(f"Demo data reset. {counts.get('cur_applications', 0)} cases restored.")


def _remove_custom_and_reset(store: SQLiteStore) -> None:
    """Delete permanent custom definitions only after explicit confirmation."""
    if not st.session_state.get("confirm_remove_custom_cases"):
        st.session_state["custom_case_notice"] = "Confirm removal before deleting permanent custom cases."
        return
    remove_custom_cases()
    _reset_demo(store)
    st.session_state["custom_case_notice"] = "Permanent custom cases were removed."


def _render_case_table(cases: pd.DataFrame) -> None:
    """Display every demo/custom case with its current human-readable state."""
    rows = []
    for _, case in cases.iterrows():
        story = (
            "Permanent synthetic intake case."
            if case["case_type"] == "Custom case"
            else _STORIES.get(case["persona_key"], "Synthetic persona application.")
        )
        rows.append(
            {
                "Applicant": case["applicant"],
                "Story": story,
                "Stage": case["stage"],
                "AI recommendation": (
                    case["ai_recommendation"]
                    if pd.notna(case["ai_recommendation"])
                    else "—"
                ),
                "Human decision": (
                    case["human_decision"]
                    if pd.notna(case["human_decision"])
                    else "—"
                ),
                "Override": (
                    "Yes" if pd.notna(case["is_override"]) and bool(case["is_override"])
                    else "No" if pd.notna(case["human_decision"])
                    else "—"
                ),
                "Case type": case["case_type"],
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def _render_charts(cases: pd.DataFrame, store: SQLiteStore) -> None:
    """Render the two current-case charts and tuck risk distribution away."""
    if cases.empty:
        st.info("Case charts will appear when demo or custom cases are available.")
        return
    open_cases = cases.loc[~cases["stage"].isin(_CLOSED_STAGES)]
    left, right = st.columns(2)
    with left:
        st.markdown("#### Open cases by stage")
        counts = open_cases.groupby("stage", dropna=False).size().rename("Cases").reset_index()
        if counts.empty:
            st.info("There are no open cases.")
        else:
            st.plotly_chart(
                px.bar(counts, x="stage", y="Cases", labels={"stage": "Stage"}),
                width="stretch",
                key="overview_open_stages",
            )
    with right:
        st.markdown("#### AI decision mix")
        decision_counts = (
            cases.loc[cases["ai_recommendation"].notna()]
            .groupby("ai_recommendation")
            .size()
            .rename("Cases")
            .reset_index()
        )
        if decision_counts.empty:
            st.info("AI recommendations appear after assessment.")
        else:
            st.plotly_chart(
                px.bar(
                    decision_counts,
                    x="ai_recommendation",
                    y="Cases",
                    color="ai_recommendation",
                    color_discrete_map={
                        "Approve": "#23866f",
                        "Refer": "#d69a2d",
                        "Decline": "#b95c52",
                    },
                    labels={"ai_recommendation": "AI recommendation"},
                ),
                width="stretch",
                key="overview_decision_mix",
            )
    with st.expander("Risk-band distribution"):
        risk = list_applications(store=store)
        risk = risk.loc[
            risk["persona_key"].notna()
            | risk["application_id"].astype(str).str.startswith("APP-CUSTOM-")
        ]
        if risk.empty or risk["risk_band"].dropna().empty:
            st.info("Risk bands appear after assessment.")
        else:
            risk_counts = risk.groupby("risk_band").size().rename("Cases").reset_index()
            st.plotly_chart(
                px.bar(risk_counts, x="risk_band", y="Cases", color="risk_band"),
                width="stretch",
                key="overview_risk_distribution",
            )


def _render_closed_summary(cases: pd.DataFrame) -> None:
    """Show closed outcomes, agreement counts, and rejected-case context."""
    closed = cases.loc[cases["stage"].isin(_CLOSED_STAGES)]
    agreed = int(
        (
            cases["human_decision"].notna()
            & ~cases["is_override"].fillna(0).astype(bool)
        ).sum()
    )
    overridden = int(cases["is_override"].fillna(0).astype(bool).sum())
    counts = (
        ("Approved · awaiting payout", int((cases["stage"] == "Sanction").sum())),
        ("Disbursed", int((cases["stage"] == "Disbursed (simulated)").sum())),
        ("Rejected", int((cases["stage"] == "Rejected").sum())),
        ("Escalated", int((cases["stage"] == "Escalated").sum())),
        ("Awaiting documents", int((cases["stage"] == "Awaiting documents").sum())),
        ("AI / human agreed", agreed),
        ("Overridden", overridden),
    )
    st.subheader("Closed cases")
    columns = st.columns(4)
    for column, (label, value) in zip(columns, counts[:4], strict=True):
        column.metric(label, value)
    columns = st.columns(3)
    for column, (label, value) in zip(columns, counts[4:], strict=True):
        column.metric(label, value)
    rejected = closed.loc[closed["stage"] == "Rejected"]
    with st.expander(f"Rejected case details ({len(rejected)})"):
        if rejected.empty:
            st.caption("No rejected cases.")
        else:
            st.dataframe(
                rejected[["applicant", "decided_by", "human_reason", "decided_at"]]
                .rename(
                    columns={
                        "applicant": "Applicant",
                        "decided_by": "Reviewer",
                        "human_reason": "Reason",
                        "decided_at": "Decision time",
                    }
                )
                .assign(**{"Decision time": lambda frame: frame["Decision time"].map(format_datetime)}),
                width="stretch",
                hide_index=True,
            )


def _render_attention(store: SQLiteStore) -> None:
    """Show cases awaiting human review with direct case-open actions."""
    st.subheader("Needs your attention")
    cases = overview_attention_cases(store)
    if cases.empty:
        st.info("No cases are currently awaiting human review.")
        return
    for _, case in cases.iterrows():
        columns = st.columns([4, 1])
        columns[0].write(
            f"**{case['applicant']}** · {case['ai_recommendation'] or 'Pending'} · "
            f"{case['risk_band'] or 'Pending'}"
        )
        columns[1].button(
            "Open",
            key=f"overview_open_{case['application_id']}",
            on_click=_open_case,
            args=(str(case["application_id"]),),
        )


def _render_historical(store: SQLiteStore) -> None:
    """Keep the 60 historical synthetic outcomes separate from pipeline totals."""
    historical = overview_historical_metrics(store)
    with st.container(border=True):
        st.subheader("Historical portfolio · synthetic past cases")
        st.caption("Historical cases are shown separately and are not part of the current pipeline.")
        columns = st.columns(5)
        for column, (label, value) in zip(
            columns,
            (
                ("Cases", historical["case_count"]),
                ("Approved", historical["approved_count"]),
                ("Declined", historical["declined_count"]),
                ("Referred", historical["referred_count"]),
                ("Average processing", f"{float(historical['average_processing_days']):.1f} days"),
            ),
            strict=True,
        ):
            column.metric(label, value)


def render(store: SQLiteStore | None = None) -> None:
    """Render the single Overview command centre."""
    render_disclaimer()
    store = store or SQLiteStore()
    create_schema(store)
    render_header("Overview", "One command centre for the synthetic loan demo.", "OPERATE  /  COMMAND CENTRE")
    notice = st.session_state.pop("overview_notice", None)
    if notice:
        st.warning(notice)
    st.button(
        "Start demo with Priya Menon",
        type="primary",
        width="stretch",
        key="start_guided_demo",
        on_click=_start_demo,
        args=(store,),
    )

    cases = _demo_custom_cases(store)
    total = len(cases)
    closed = int(cases["stage"].isin(_CLOSED_STAGES).sum()) if total else 0
    open_count = total - closed
    waiting = int((cases["stage"] == "Human Review").sum()) if total else 0
    columns = st.columns(4)
    for column, (label, value) in zip(
        columns,
        (
            ("Total cases", total),
            ("Open", open_count),
            ("Closed", closed),
            ("Waiting for human review", waiting),
        ),
        strict=True,
    ):
        column.metric(label, value, help="Six synthetic personas plus custom cases; historical cases excluded.")

    st.subheader("Where every case stands")
    if cases.empty:
        st.info("No demo cases are loaded yet. Start demo to load the synthetic personas.")
    else:
        _render_case_table(cases)
        ids = cases["application_id"].astype(str).tolist()
        names = dict(zip(ids, cases["applicant"].astype(str), strict=True))
        st.selectbox("Open a case", ids, format_func=lambda value: names[value], key="overview_case")
        st.button(
            "Open case",
            on_click=_open_case,
            args=(st.session_state.get("overview_case", ids[0]),),
            key="overview_open_selected",
        )

    _render_charts(cases, store)
    _render_closed_summary(cases)
    _render_attention(store)
    _render_historical(store)
    with st.expander("Implementation status"):
        ledger_counts(store)
        st.dataframe(ledger_frame(store), width="stretch", hide_index=True)
    with st.expander("Presenter controls"):
        st.button(
            "Reset demo data",
            key="overview_reset_demo",
            on_click=_reset_demo,
            args=(store,),
        )
        st.caption("Remove permanent custom cases from the saved list and reset the database.")
        st.checkbox("Confirm removal of all custom cases", key="confirm_remove_custom_cases")
        st.button(
            "Remove all custom cases",
            key="remove_custom_cases",
            on_click=_remove_custom_and_reset,
            args=(store,),
        )
        custom_notice = st.session_state.pop("custom_case_notice", None)
        if custom_notice:
            st.info(custom_notice)
