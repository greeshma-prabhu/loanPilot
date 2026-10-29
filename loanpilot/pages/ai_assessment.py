"""AI Assessment page for deterministic policy evaluation and agent trace review."""

import json
from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from loanpilot.agent.orchestrator import run_assessment
from loanpilot.badges import implementation_badge
from loanpilot.components import (
    fmt_inr,
    render_decision_card,
    render_human_review_button,
    render_key_numbers,
    render_why,
    status_chip,
)
from loanpilot.data.queries import (
    get_agent_trace,
    get_application,
    list_applications,
)
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore
from loanpilot.theme import format_datetime, render_disclaimer, render_header

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


def _open_kyc_case(application_id: str) -> None:
    """Open the selected case with its KYC panel displayed."""
    from loanpilot.navigation import OPERATE_PAGES

    st.session_state["selected_application"] = application_id
    st.session_state["case_kyc_open"] = application_id
    st.switch_page(OPERATE_PAGES["applications"])


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


def _render_pipeline(completed_steps: int) -> None:
    """Render a one-line compact progress indicator with short step labels."""
    labels = ("Documents", "Financials", "Policy", "Risk", "Recommendation")
    parts = []
    for index, label in enumerate(labels):
        state = "done" if index < completed_steps else "running" if index == completed_steps and completed_steps < len(labels) else "waiting"
        marker, text = ("✓", "Done") if state == "done" else ("●", "Running") if state == "running" else ("○", "Waiting")
        parts.append(
            f'<div class="lp-assessment-step {state}">'
            f'<span aria-hidden="true">{marker}</span> {label} · {text}</div>'
        )
    st.markdown(
        f'<div class="lp-assessment-progress">{"".join(parts)}</div>',
        unsafe_allow_html=True,
    )


def _render_timeline(result: dict[str, Any]) -> None:
    """Show tool calls, inputs, outputs, durations, modes, and handoffs."""
    st.subheader("Agent timeline")
    for step in result.get("trace", []):
        with st.expander(
            f"{step['step_no']}. {step['agent']} · "
            f"{step['duration_ms']} ms · {format_datetime(step['started_at'])}",
            expanded=False,
        ):
            for call in step["calls"]:
                st.markdown(f"**Tool: {call['name']}**")
                with st.expander("Show raw inputs"):
                    st.json(call.get("inputs", {}))
                with st.expander("Show raw outputs"):
                    st.json(call.get("outputs", {}))
            st.caption(f"Mode: {step['mode']} · Handoff: {step['handoff']}")


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
                "Extracted value": _human_value(value),
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
    rows = []
    for row in clauses:
        rows.append(
            "<tr>"
            f"<td>{escape(str(row['clause_id']))}</td>"
            f"<td>{escape(str(row['rule_text']))}</td>"
            f"<td>{escape(_human_value(row['observed']))}</td>"
            f"<td>{escape(row['status'].title())}</td>"
            "</tr>"
        )
    st.markdown(
        '<table class="lp-policy-table"><thead><tr><th>Clause</th><th>Full rule</th>'
        f"<th>Observed value</th><th>Result</th></tr></thead><tbody>{''.join(rows)}</tbody></table>",
        unsafe_allow_html=True,
    )
    with st.expander("Show raw policy values"):
        st.json([{"clause_id": row["clause_id"], "observed": row["observed"]} for row in clauses])


def _human_value(value: Any) -> str:
    """Convert structured policy observations to a compact readable label."""
    if isinstance(value, dict):
        return " · ".join(f"{key.replace('_', ' ')}: {item}" for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value) or "None"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _render_recommendation(result: dict[str, Any]) -> None:
    """Render recommendation, reasons, conditions, counterfactual, and explanation."""
    with st.container(border=True):
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
        kyc_clause = next(
            (
                clause
                for clause in result.get("policy", {}).get("clauses", [])
                if clause.get("clause_id") == "CP-6.1"
            ),
            {},
        )
        observed_kyc = kyc_clause.get("observed", {})
        kyc_name_match = float(
            observed_kyc.get("name_match", observed_kyc.get("name_match_score", 1))
            or 0
        )
        kyc_reason = str(observed_kyc.get("reason", "")).casefold()
        kyc_pending = (
            kyc_clause.get("status") == "refer"
            and str(
                observed_kyc.get(
                    "status", observed_kyc.get("pan_status", "")
                )
            ).casefold()
            != "verified"
            and not (
                kyc_name_match < 0.85
                and "manual identity review" in kyc_reason
            )
        )
        kyc_mismatch = (
            kyc_clause.get("status") == "refer"
            and kyc_name_match < 0.85
            and (
                str(
                    observed_kyc.get(
                        "status", observed_kyc.get("pan_status", "")
                    )
                ).casefold()
                == "verified"
                or "manual identity review" in kyc_reason
            )
        )
        st.markdown("**What would change this**")
        if kyc_pending:
            st.write("Complete eKYC")
        elif kyc_mismatch:
            st.write("Manual identity review")
        elif affordable is None:
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


def _render_details(result: dict[str, Any]) -> None:
    """Render technical assessment detail in compact tabs."""
    with st.expander("Details", expanded=False):
        tabs = st.tabs(["Agent steps", "Document evidence", "Full policy table", "Raw trace"])
        with tabs[0]:
            st.markdown(
                f"{implementation_badge('real')} Deterministic assessment steps",
                unsafe_allow_html=True,
            )
            st.dataframe(
                [
                    {
                        "Step": step["agent"],
                        "Duration": f"{step['duration_ms']} ms",
                        "Mode": step["mode"],
                    }
                    for step in result.get("trace", [])
                ],
                width="stretch",
                hide_index=True,
            )
            for step in result.get("trace", []):
                with st.expander(f"{step['step_no']}. {step['agent']} · tool calls"):
                    for call in step["calls"]:
                        with st.expander(str(call["name"])):
                            st.markdown("**Inputs**")
                            st.json(call.get("inputs", {}))
                            st.markdown("**Outputs**")
                            st.json(call.get("outputs", {}))
        with tabs[1]:
            mode = result.get("modes", ["Recorded"])[0]
            badge_kind = "real" if mode == "Live Gemini" else "simulated"
            st.markdown(
                f"{implementation_badge(badge_kind)} Document extraction and reconciliation",
                unsafe_allow_html=True,
            )
            _render_evidence(result)
        with tabs[2]:
            _render_policy(result)
        with tabs[3]:
            with st.expander("Show raw trace JSON"):
                st.json(result.get("trace", []))


def _render_assessment(result: dict[str, Any], store: SQLiteStore) -> None:
    """Render the decision and key facts before optional technical details."""
    application_id = str(result["application_id"])
    _render_pipeline(len(result.get("trace", [])))
    st.caption("Policy outcomes and financial calculations are deterministic; language output cannot change them.")
    render_decision_card(application_id, store)
    render_human_review_button(application_id)
    render_why(application_id, store)
    st.markdown("### Key numbers")
    render_key_numbers(application_id, store)
    if result.get("recommendation") in {"Refer", "Decline"}:
        counterfactual = result.get("counterfactual", {})
        clauses = result.get("policy", {}).get("clauses", [])
        doc_failure = bool(result.get("policy", {}).get("document_failure"))
        thin_file = any(
            clause.get("clause_id") == "CP-5.4" and clause.get("status") == "refer"
            for clause in clauses
        )
        kyc_clause = next(
            (clause for clause in clauses if clause.get("clause_id") == "CP-6.1"),
            {},
        )
        kyc_observed = kyc_clause.get("observed", {})
        kyc_status = str(
            kyc_observed.get("status", kyc_observed.get("pan_status", ""))
        ).casefold()
        kyc_score = float(
            kyc_observed.get("name_match", kyc_observed.get("name_match_score", 1))
            or 0
        )
        if kyc_clause.get("status") == "refer":
            change_text = (
                "Manual identity review"
                if kyc_score < 0.85
                and (
                    kyc_status == "verified"
                    or "manual identity review"
                    in str(kyc_observed.get("reason", "")).casefold()
                )
                else "Complete eKYC"
            )
        elif doc_failure:
            change_text = "Provide corrected payslip and bank-statement evidence for document review."
        elif thin_file:
            change_text = "The thin-file request is capped at Rs 75,000 in this demo."
        elif counterfactual.get("max_affordable_amount") is not None:
            change_text = (
                "Largest amount within the illustrative 45% FOIR limit: "
                f"{fmt_inr(counterfactual['max_affordable_amount'])}."
            )
        else:
            change_text = counterfactual.get("note", "Review the triggering policy checks.")
        st.markdown("### What would change this")
        st.write(change_text)
        if kyc_clause.get("status") == "refer":
            st.button(
                "Complete eKYC (demo)",
                key=f"assessment_open_kyc_{application_id}",
                on_click=_open_kyc_case,
                args=(application_id,),
                width="stretch",
            )
    _render_details(result)


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
    header_left, header_run, header_mode = st.columns([4.5, 1.4, 1.3])
    with header_left:
        selected_application = st.selectbox(
            "Case",
            application_ids,
            index=default_index,
            format_func=lambda application_id: (
                str(applications.loc[applications.application_id == application_id, "applicant"].iloc[0])
            ),
            key="assessment_application_selector",
            on_change=_remember_selection,
        )
    with header_run:
        st.button(
            "Run assessment",
            type="primary",
            on_click=_run_selected_assessment,
            args=(selected_application, store),
            key="run_assessment",
            width="stretch",
        )
    st.session_state["selected_application"] = selected_application
    current_application = get_application(selected_application, store)
    if current_application.empty:
        st.error(f"Application {selected_application} was not found.")
        return
    result = None
    if st.session_state.get("assessment_application_id") == selected_application:
        result = st.session_state.get("assessment_result")
    if result is None:
        result = _assessment_from_saved(selected_application, store)
    modes = result.get("modes", []) if result else []
    mode_label = "Live Gemini" if "Live Gemini" in modes else "Recorded"
    with header_mode:
        st.markdown(
            f'<div style="padding-top:2rem">{status_chip(mode_label, "info")}</div>',
            unsafe_allow_html=True,
        )
    with st.expander("Technical case reference"):
        st.code(str(selected_application))
    if result is None:
        _render_pipeline(-1)
        render_decision_card(selected_application, store)
    else:
        _render_assessment(result, store)
