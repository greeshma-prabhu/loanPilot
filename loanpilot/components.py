"""Reusable presentation components for application case views."""

from html import escape
import json
from typing import Any

import pandas as pd
import streamlit as st

STAGES = [
    "Submitted",
    "Document Verification",
    "Financial Assessment",
    "Credit & Policy Checks",
    "Risk Assessment",
    "Human Review",
    "Sanction",
    "Disbursed (simulated)",
]

_STAGE_ALIASES = {
    "approved": "Human Review",
    "declined": "Human Review",
    "referred": "Human Review",
    "rejected": "Human Review",
    "escalated": "Human Review",
    "awaiting documents": "Document Verification",
    "disbursed": "Disbursed (simulated)",
    "disbursed (simulated)": "Disbursed (simulated)",
}


def fmt_inr(amount: float | int | None) -> str:
    """Format an amount with Indian digit grouping and the Rs prefix."""
    if amount is None:
        return "—"
    rounded = int(round(float(amount)))
    sign = "-" if rounded < 0 else ""
    digits = str(abs(rounded))
    if len(digits) > 3:
        last_three = digits[-3:]
        leading = digits[:-3]
        groups = []
        while len(leading) > 2:
            groups.insert(0, leading[-2:])
            leading = leading[:-2]
        if leading:
            groups.insert(0, leading)
        digits = ",".join(groups + [last_three])
    return f"Rs {sign}{digits}"


def calculate_foir(
    existing_emi: float, proposed_emi: float, monthly_income: float
) -> float | None:
    """Return FOIR as a ratio, or None when verified monthly income is zero."""
    if monthly_income <= 0:
        return None
    return (existing_emi + proposed_emi) / monthly_income


def status_chip(text: str, kind: str = "neutral") -> str:
    """Return a text-labelled status chip using a consistent status palette."""
    styles = {
        "neutral": ("#eef0f2", "#4b5563"),
        "success": ("#e5f4e9", "#1f6b3b"),
        "warning": ("#fff2d6", "#805400"),
        "danger": ("#fde8e7", "#9d2f2a"),
        "info": ("#e4f1f8", "#205b79"),
        "demo": ("#e8f4f2", "#17665f"),
    }
    background, foreground = styles.get(kind, styles["neutral"])
    return (
        f'<span title="{escape(text)}" style="display:inline-block;'
        f'padding:.2rem .6rem;border-radius:999px;'
        f'background:{background};color:{foreground};font-size:.82rem;'
        f'font-weight:600;border:1px solid {foreground}33;max-width:100%;">'
        f'{escape(text)}</span>'
    )


def case_header_card(application: Any) -> None:
    """Render a compact applicant identity and status header."""
    value = application.to_dict() if hasattr(application, "to_dict") else application
    name = escape(str(value.get("name", value.get("applicant", "Applicant"))))
    stage = escape(str(value.get("stage", "Unknown")))
    recommendation = value.get("ai_recommendation")
    recommendation_label = (
        f"AI: {escape(str(recommendation))}"
        if recommendation is not None and not pd.isna(recommendation)
        else "AI: pending"
    )
    st.markdown(
        '<div style="padding:.9rem 1rem;border:1px solid #dce7e5;'
        'border-radius:14px;background:#fff;margin:.4rem 0 .7rem;">'
        f'<div style="font-size:1.25rem;font-weight:650;color:#173b39;">{name}</div>'
        f'{status_chip(stage, "info")} &nbsp; {status_chip(recommendation_label, "neutral")}'
        "</div>",
        unsafe_allow_html=True,
    )


def kpi_card(
    label: str,
    value: str,
    *,
    help_text: str | None = None,
) -> None:
    """Render one KPI with an optional formula tooltip."""
    st.markdown(
        '<div style="min-height:6.2rem;padding:.9rem 1rem;border:1px solid #dce7e5;'
        'border-radius:14px;background:#fff;">'
        f'<div style="font-size:.88rem;color:#526563;">{escape(label)}</div>'
        f'<div style="font-size:1.25rem;font-weight:650;color:#173b39;'
        f'margin:.25rem 0;">{escape(value)}</div>'
        "</div>",
        unsafe_allow_html=True,
        help=help_text,
    )


def stage_tracker(current_stage: str) -> None:
    """Render ordered workflow steps with explicit done/current/upcoming text."""
    normalized = _STAGE_ALIASES.get(current_stage.casefold(), current_stage)
    current_index = STAGES.index(normalized) if normalized in STAGES else 0
    columns = st.columns(len(STAGES))
    for index, (column, stage) in enumerate(zip(columns, STAGES, strict=True)):
        if index < current_index:
            icon, state = "✓", "Done"
        elif index == current_index:
            icon, state = "●", "Current"
        else:
            icon, state = "○", "Upcoming"
        with column:
            st.markdown(
                f'<div class="lp-stage-state">{icon} {state}</div>'
                f'<div class="lp-stage-label">{stage}</div>',
                unsafe_allow_html=True,
            )


def _assessment_model(application_id: str, store: Any = None) -> dict[str, Any] | None:
    """Load a persisted assessment into a shared presentation model."""
    from loanpilot.data.queries import get_agent_trace, get_application

    application_rows = get_application(application_id, store)
    trace_rows = get_agent_trace(application_id, store=store)
    if application_rows.empty or trace_rows.empty:
        return None
    application = application_rows.iloc[0].to_dict()
    trace_by_step = {
        int(row["step_no"]): json.loads(row["tool_calls_json"])
        for _, row in trace_rows.iterrows()
    }
    if not all(number in trace_by_step for number in range(1, 6)):
        return None
    first = trace_by_step[1].get("result", {})
    financials = trace_by_step[2].get("result", {})
    credit = trace_by_step[3].get("result", {})
    risk = trace_by_step[4].get("result", {})
    recommendation_step = trace_by_step[5].get("result", {})
    reasons = json.loads(application.get("ai_reasons_json") or "{}")
    return {
        "application": application,
        "recommendation": application.get("ai_recommendation"),
        "risk_band": reasons.get("risk_band", risk.get("risk_band", "Unavailable")),
        "policy": credit.get("policy", {}),
        "finances": financials,
        "extracted": {
            "fields": first.get("extracted_fields", {}),
            "evidence": first.get("evidence", {}),
            "anomaly_description": first.get("anomaly_description", ""),
            "reconciliation": first.get("reconciliation", {}),
        },
        "pricing": recommendation_step.get("pricing", {}),
        "counterfactual": recommendation_step.get("counterfactual", {}),
        "explanation": recommendation_step.get("explanation", ""),
        "explanation_mode": recommendation_step.get("explanation_mode", "Recorded"),
        "trace": [
            {
                "step_no": int(row["step_no"]),
                "agent": row["agent"],
                "duration_ms": int(row["duration_ms"]),
                "mode": row["mode"],
                "handoff": row["handoff"],
                **json.loads(row["tool_calls_json"]),
            }
            for _, row in trace_rows.iterrows()
        ],
    }


def _open_human_review(application_id: str) -> None:
    """Select a case and open its Human Review workspace."""
    from loanpilot.navigation import OPERATE_PAGES

    st.session_state["selected_application"] = application_id
    st.session_state["review_open"] = application_id
    st.switch_page(OPERATE_PAGES["human_review"])


def render_human_review_button(application_id: str) -> None:
    """Render a full-width handoff button below a decision card."""
    st.button(
        "Go to Human Review",
        key=f"decision_review_{application_id}",
        on_click=_open_human_review,
        args=(application_id,),
        type="primary",
        width="stretch",
    )


def render_decision_card(
    application_id: str,
    store: Any = None,
    *,
    compact: bool = False,
) -> None:
    """Render the shared decision-first summary for one persisted assessment."""
    from loanpilot.agent.policy_engine import pricing_rate

    model = _assessment_model(application_id, store)
    if model is None:
        with st.container(border=True):
            st.subheader("Assessment not run yet")
            st.info("Run the assessment to see the recommendation and key numbers.")
        return

    recommendation = str(model["recommendation"] or "Unavailable")
    policy = model["policy"]
    documents_failed = bool(policy.get("document_failure"))
    title = (
        "REFER: document review"
        if recommendation == "Refer" and documents_failed
        else recommendation.upper()
    )
    icon, kind = {
        "Approve": ("✓", "success"),
        "Refer": ("!", "warning"),
        "Decline": ("×", "danger"),
    }.get(recommendation, ("i", "neutral"))
    application = model["application"]
    amount = float(application.get("requested_amount") or 0)
    tenure = int(application.get("tenure_months") or 0)
    pricing = model["pricing"]
    rate = pricing.get("rate")
    emi = pricing.get("emi")
    fact_values = (
        ("Amount and tenure", f"{fmt_inr(amount)} · {tenure} months"),
        ("Rate", f"{float(rate):.2%} p.a." if rate is not None else "—"),
        ("Indicative EMI", fmt_inr(emi)),
        ("Handoff", "Human Review"),
    )
    summary = {
        "Approve": "The case meets the illustrative checks; a human reviewer must still decide.",
        "Refer": (
            "The case needs a human review before any decision."
            if not documents_failed
            else "Document evidence needs a human review before a decision."
        ),
        "Decline": "One or more illustrative checks were not met; this is not a final credit decision.",
    }.get(recommendation, "The assessment result is unavailable.")
    with st.container(border=True):
        st.markdown(
            f'<div class="lp-decision-title {kind}"><span aria-hidden="true">{icon}</span>'
            f'<span>{escape(title)}</span>{status_chip(model["risk_band"], "info")}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="lp-decision-summary">{escape(summary)}</div>',
            unsafe_allow_html=True,
        )
        facts_html = "".join(
            f'<div class="lp-decision-fact"><span>{escape(label)}</span>'
            f'<strong>{escape(value)}</strong></div>'
            for label, value in fact_values
        )
        st.markdown(
            f'<div class="lp-decision-facts {"compact" if compact else ""}">{facts_html}</div>',
            unsafe_allow_html=True,
        )
    if model.get("explanation"):
        st.markdown(
            f"**Explanation** · {status_chip(str(model['explanation_mode']), 'info')}",
            unsafe_allow_html=True,
        )
        st.write(model["explanation"])


def render_why(
    application_id: str,
    store: Any = None,
    *,
    compact: bool = False,
) -> None:
    """Render up to five policy reasons generated from observed values."""
    from loanpilot.agent.reason_text import build_why

    model = _assessment_model(application_id, store)
    if model is None:
        return
    lines = build_why(
        str(model["recommendation"] or "Unavailable"),
        model["policy"].get("clauses", []),
    )
    if not compact:
        st.subheader("Why")
    if not lines:
        st.caption("No triggering policy results were recorded.")
        return
    for line in lines:
        kind = "success" if line["status"] == "pass" else "danger" if line["status"] == "decline" else "warning"
        st.markdown(
            f'<div class="lp-why-line"><span aria-hidden="true">'
            f'{"✓" if kind == "success" else "×" if kind == "danger" else "!"}</span>'
            f'<span>{escape(line["text"])}</span>'
            f'{status_chip(line["clause_id"], kind)}</div>',
            unsafe_allow_html=True,
        )


def render_key_numbers(application_id: str, store: Any = None) -> None:
    """Show the four compact decision facts requested on the assessment page."""
    model = _assessment_model(application_id, store)
    if model is None:
        return
    finances = model["finances"]
    stated = float(finances.get("stated_income") or 0)
    verified = float(finances.get("verified_income") or 0)
    foir_stated = finances.get("foir_stated")
    foir_verified = finances.get("foir_verified")
    bureau_clause = next(
        (
            clause for clause in model["policy"].get("clauses", [])
            if clause.get("clause_id") == "CP-5.1"
        ),
        {},
    )
    observed_bureau = bureau_clause.get("observed", {})
    score = observed_bureau.get("bureau_score") if isinstance(observed_bureau, dict) else None
    reconciliation = model["extracted"].get("reconciliation", {})
    checks = (
        "payslip_arithmetic_matches",
        "salary_credits_within_tolerance",
        "employer_matches",
    )
    issues = sum(not bool(reconciliation.get(key)) for key in checks)
    columns = st.columns(4)
    facts = (
        ("Income", f"{fmt_inr(stated)} → {fmt_inr(verified)}"),
        (
            "FOIR · 45% limit",
            f"{float(foir_stated):.1%} → {float(foir_verified):.1%}"
            if foir_stated is not None and foir_verified is not None
            else "Unavailable",
        ),
        ("Bureau", f"{score if score is not None else 'Thin file'} · {model['risk_band']} risk"),
        ("Documents", "Consistent" if issues == 0 else f"{issues} issues"),
    )
    for column, (label, value) in zip(columns, facts, strict=True):
        column.metric(label, value)
