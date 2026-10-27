"""AI Assessment page for deterministic policy evaluation and agent trace review."""

import json
from typing import Any

import pandas as pd
import streamlit as st

from loanpilot.agent.orchestrator import run_assessment
from loanpilot.badges import implementation_badge
from loanpilot.components import fmt_inr, status_chip
from loanpilot.data.queries import (
    get_agent_trace,
    get_application,
    list_applications,
)
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore
from loanpilot.theme import render_disclaimer, render_header

_PIPELINE = [
    "Document Verification",
    "Financial Assessment",
    "Credit & Policy",
    "Risk",
    "Recommendation",
]


def _remember_selection() -> None:
    """Keep the current assessment case available to other pages."""
    application_id = st.session_state.get("assessment_application_selector")
    if application_id:
        st.session_state["selected_application"] = application_id


def _run_selected_assessment(application_id: str, store: SQLiteStore) -> None:
    """Run the deterministic workflow and store its result for the current view."""
    result = run_assessment(application_id, store)
    st.session_state["assessment_result"] = result
    st.session_state["assessment_application_id"] = application_id


def _load_demo_data(store: SQLiteStore) -> None:
    """Generate the synthetic sample dataset in an empty store."""
    counts = seed_demo_data(store, reset=True)
    st.toast(
        "Demo data loaded. "
        + ", ".join(f"{table}: {count}" for table, count in counts.items())
    )


def _decode_trace_row(row: pd.Series) -> dict[str, Any]:
    """Decode a persisted step payload and retain trace metadata."""
    payload = json.loads(row["tool_calls_json"])
    return {
        "step_no": int(row["step_no"]),
        "agent": row["agent"],
        "started_at": row["started_at"],
        "duration_ms": int(row["duration_ms"]),
        "mode": row["mode"],
        "handoff": row["handoff"],
        "calls": payload.get("calls", []),
        "result": payload.get("result", {}),
    }


def _assessment_from_saved(application_id: str, store: SQLiteStore) -> dict[str, Any] | None:
    """Rebuild the display model from the latest persisted trace and decision."""
    trace_frame = get_agent_trace(application_id, store=store)
    if trace_frame.empty:
        return None
    trace = [_decode_trace_row(row) for _, row in trace_frame.iterrows()]
    by_step = {step["step_no"]: step for step in trace}
    if not all(number in by_step for number in range(1, 6)):
        return None
    application = get_application(application_id, store)
    if application.empty:
        return None
    reasons = json.loads(application.iloc[0]["ai_reasons_json"] or "{}")
    return {
        "application_id": application_id,
        "recommendation": application.iloc[0]["ai_recommendation"],
        "risk_band": reasons.get("risk_band", "Unavailable"),
        "policy": by_step[3]["result"].get("policy", {}),
        "risk": by_step[4]["result"],
        "finances": by_step[2]["result"],
        "extracted": {
            "fields": by_step[1]["result"].get("extracted_fields", {}),
            "evidence": by_step[1]["result"].get("evidence", {}),
            "anomaly_description": by_step[1]["result"].get(
                "anomaly_description", ""
            ),
        },
        "reconciliation": by_step[1]["result"].get("reconciliation", {}),
        "pricing": by_step[5]["result"].get("pricing", {}),
        "counterfactual": by_step[5]["result"].get("counterfactual", {}),
        "reasons_for": reasons.get("reasons_for", []),
        "reasons_against": reasons.get("reasons_against", []),
        "conditions": reasons.get("conditions", []),
        "explanation": reasons.get("explanation", ""),
        "explanation_mode": by_step[5]["mode"],
        "modes": [step["mode"] for step in trace],
        "trace": trace,
        "handed_to": "Human Review",
    }


def _result_mode(result: dict[str, Any]) -> str:
    """Summarize language generation modes without relabelling deterministic steps."""
    llm_modes = dict.fromkeys(
        mode
        for mode in result.get("modes", [])
        if mode == "Live Gemini" or mode.startswith("Recorded (")
    )
    return " + ".join(llm_modes) if llm_modes else "Recorded (pre-written sample)"


def _render_pipeline(complete: bool) -> None:
    """Render the five-step assessment pipeline with text status indicators."""
    columns = st.columns(5)
    for index, (column, step) in enumerate(zip(columns, _PIPELINE, strict=True)):
        state = "Done" if complete else ("Ready" if index == 0 else "Upcoming")
        icon = "✓" if complete else ("○" if index else "●")
        style = "is-done" if complete else ("is-ready" if index == 0 else "")
        with column:
            st.markdown(
                f'<div class="lp-pipeline-card {style}">'
                f'<div class="lp-pipeline-state">{icon} {state}</div>'
                f'<div class="lp-pipeline-label">{step}</div></div>',
                unsafe_allow_html=True,
            )


def _render_timeline(result: dict[str, Any]) -> None:
    """Show tool calls, inputs, outputs, durations, modes, and handoffs."""
    st.subheader("Agent timeline")
    for step in result.get("trace", []):
        with st.expander(
            f"{step['step_no']}. {step['agent']} · {step['duration_ms']} ms · {step['mode']}",
            expanded=False,
        ):
            for call in step["calls"]:
                st.markdown(f"**Tool: {call['name']}**")
                st.caption("Inputs")
                st.json(call.get("inputs", {}))
                st.caption("Outputs")
                st.json(call.get("outputs", {}))
            st.caption(f"Handoff: {step['handoff']}")


def _render_evidence(result: dict[str, Any]) -> None:
    """Show extracted fields beside their source document and supporting text."""
    st.subheader("Document evidence")
    evidence = result["extracted"].get("evidence", {})
    fields = result["extracted"].get("fields", {})
    rows = []
    for field, value in fields.items():
        source = evidence.get(field) or {}
        rows.append(
            {
                "Field": field.replace("_", " ").title(),
                "Extracted value": value,
                "Source document": source.get("source_document", "Unavailable"),
                "Matching text": source.get("snippet", "No matching text found"),
            }
        )
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.info("No document fields were extracted.")
    st.markdown("**Document anomaly description**")
    st.write(result["extracted"].get("anomaly_description") or "Unavailable")


def _render_policy(result: dict[str, Any]) -> None:
    """Show deterministic clause results and label the executed evaluation."""
    st.subheader("Illustrative policy evaluation")
    st.markdown(
        f"{implementation_badge('real')} Deterministic policy code executed for this case.",
        unsafe_allow_html=True,
    )
    clauses = result.get("policy", {}).get("clauses", [])
    if not clauses:
        st.info("No policy results are available.")
        return
    frame = pd.DataFrame(
        [
            {
                "Clause": row["clause_id"],
                "Rule": row["rule_text"],
                "Observed": json.dumps(row["observed"], ensure_ascii=False),
                "Result": f"{row['status'].title()} · {row['severity']} severity",
            }
            for row in clauses
        ]
    )
    st.dataframe(frame, width="stretch", hide_index=True)


def _render_recommendation(result: dict[str, Any]) -> None:
    """Render recommendation, reasons, conditions, counterfactual, and explanation."""
    st.subheader("Recommendation")
    recommendation = result.get("recommendation", "Unavailable")
    risk_band = result.get("risk_band", "Unavailable")
    st.markdown(
        f"### {status_chip(recommendation, 'warning' if recommendation == 'Refer' else 'success' if recommendation == 'Approve' else 'danger')} "
        f"{status_chip(f'Risk: {risk_band}', 'info')}",
        unsafe_allow_html=True,
    )

    left, right = st.columns(2)
    with left:
        st.markdown("**Reasons for**")
        reasons_for = result.get("reasons_for", [])
        if reasons_for:
            for reason in reasons_for[:4]:
                st.write(f"- **{reason.get('clause_id', 'Source')}** · {reason.get('text', '')}")
        else:
            st.caption("No supporting reasons recorded.")
    with right:
        st.markdown("**Reasons against**")
        reasons_against = result.get("reasons_against", [])
        if reasons_against:
            for reason in reasons_against[:4]:
                st.write(f"- **{reason.get('clause_id', 'Source')}** · {reason.get('text', '')}")
        else:
            st.caption("No adverse policy findings recorded.")

    st.markdown("**Conditions / human-review notes**")
    if result.get("conditions"):
        for condition in result["conditions"]:
            st.write(f"- {condition}")
    else:
        st.write("No additional conditions recorded.")

    counterfactual = result.get("counterfactual", {})
    affordable = counterfactual.get("max_affordable_amount")
    st.markdown("**What would change this**")
    if affordable is None:
        st.write(counterfactual.get("note", "No affordable amount is available."))
    else:
        st.write(
            f"Largest amount within the illustrative {counterfactual.get('foir_limit', 0.45):.0%} "
            f"FOIR limit, using verified salary credits: {fmt_inr(affordable)}."
        )

    mode = result.get("explanation_mode") or _result_mode(result)
    st.markdown(f"**Plain-English explanation** · {status_chip(mode, 'info')}", unsafe_allow_html=True)
    st.write(result.get("explanation", "No explanation is available."))
    st.success("Handed to Human Review · AI does not sanction (CP-8.1).")


def _render_assessment(result: dict[str, Any]) -> None:
    """Render all evidence and outputs for a completed assessment."""
    _render_pipeline(True)
    mode = _result_mode(result)
    st.markdown(f"**Language output mode:** {status_chip(mode, 'info')}", unsafe_allow_html=True)
    st.caption("Policy outcomes and financial calculations are deterministic; language output cannot change them.")
    _render_timeline(result)
    _render_evidence(result)
    _render_policy(result)
    _render_recommendation(result)


def render(store: SQLiteStore | None = None) -> None:
    """Render the assessment selector, run action, and persisted assessment."""
    render_disclaimer()
    store = store or SQLiteStore()
    create_schema(store)
    render_header(
        "AI Assessment",
        "A transparent five-step workflow: deterministic policy and calculations, with language support kept in its lane.",
        "OPERATE  /  ASSESSMENT PIPELINE",
    )
    applications = list_applications(store=store)
    if applications.empty:
        st.info("No demo applications are loaded yet. Load the synthetic sample dataset to begin.")
        st.button(
            "Load demo data",
            on_click=_load_demo_data,
            args=(store,),
            key="load_assessment_data",
        )
        return

    application_ids = applications["application_id"].tolist()
    selected = st.session_state.get("selected_application")
    default_index = application_ids.index(selected) if selected in application_ids else 0
    selected_application = st.selectbox(
        "Application",
        application_ids,
        index=default_index,
        format_func=lambda application_id: (
            f"{application_id} · "
            f"{applications.loc[applications.application_id == application_id, 'applicant'].iloc[0]}"
        ),
        key="assessment_application_selector",
        on_change=_remember_selection,
    )
    st.session_state["selected_application"] = selected_application
    current_application = get_application(selected_application, store)
    if current_application.empty:
        st.error(f"Application {selected_application} was not found.")
        return
    st.caption(
        f"{current_application.iloc[0]['name']} · {selected_application} · "
        f"Stage: {current_application.iloc[0]['stage']}"
    )
    st.button(
        "Run assessment",
        type="primary",
        on_click=_run_selected_assessment,
        args=(selected_application, store),
        key="run_assessment",
        width="stretch",
    )

    result = None
    if st.session_state.get("assessment_application_id") == selected_application:
        result = st.session_state.get("assessment_result")
    if result is None:
        result = _assessment_from_saved(selected_application, store)
    if result is None:
        _render_pipeline(False)
        st.info("Select a case and run the assessment to create its trace and recommendation.")
    else:
        _render_assessment(result)
