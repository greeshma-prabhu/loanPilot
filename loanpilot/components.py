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
        "neutral": ("#f0f3f5", "#4b6072"),
        "success": ("#e4f4ec", "#216b4b"),
        "warning": ("#fff4dd", "#805400"),
        "danger": ("#fcebea", "#9d3b3b"),
        "info": ("#e7f2f6", "#285b73"),
        "demo": ("#e8f5f3", "#12645e"),
    }
    background, foreground = styles.get(kind, styles["neutral"])
    return (
        f'<span title="{escape(text)}" style="display:inline-block;'
        f'padding:.2rem .6rem;border-radius:999px;'
        f'background:{background};color:{foreground};font-size:.82rem;'
        f'font-weight:600;border:1px solid {foreground}33;max-width:100%;">'
        f'{escape(text)}</span>'
    )


def render_document_verification_report(
    documents: list[dict[str, Any]],
    report: dict[str, Any],
) -> None:
    """Render source-linked extracted fields and consistency checks."""
    overall = str(report.get("overall_status", "Incomplete"))
    kind = (
        "success"
        if overall in {"Verified / Consistent", "Synthetic demo documents"}
        else "danger"
        if overall == "Needs manual review"
        else "warning"
    )
    st.subheader("Document verification report")
    st.markdown(status_chip(overall, kind), unsafe_allow_html=True)
    st.write(report.get("explanation") or "No document analysis explanation is available.")
    if report.get("analysis_method"):
        st.caption(str(report["analysis_method"]))
    st.caption(
        "Issuer authenticity: "
        + str(report.get("authenticity_status", "Not independently verified"))
    )

    salary_statement = report.get("salary_statement_verification")
    if salary_statement:
        status = str(salary_statement.get("status", "INCONCLUSIVE"))
        status_kind = {
            "MATCH": "success",
            "MISMATCH": "danger",
            "INCONCLUSIVE": "warning",
        }.get(status, "warning")
        st.subheader("Salary Slip vs Bank Statement Verification")
        st.markdown(status_chip(status, status_kind), unsafe_allow_html=True)
        status_text = {
            "MATCH": "Salary Slip and Bank Statement details match.",
            "MISMATCH": "Salary Slip and Bank Statement details do not match.",
            "INCONCLUSIVE": "The documents cannot be read or compared conclusively.",
        }.get(status, "The document comparison result is unavailable.")
        st.write(status_text)
        amount_columns = st.columns(3, gap="large")
        with amount_columns[0]:
            st.metric(
                "Salary Slip net salary",
                fmt_inr(salary_statement.get("salary_slip_net_salary")),
            )
        with amount_columns[1]:
            st.metric(
                "Average monthly salary credit",
                fmt_inr(
                    salary_statement.get(
                        "bank_statement_average_monthly_salary_credit"
                    )
                ),
            )
        with amount_columns[2]:
            st.metric("Difference", fmt_inr(salary_statement.get("difference")))

        name_comparison = salary_statement.get("name_comparison") or {}
        st.write(
            "**Name comparison:** "
            f"{name_comparison.get('status', 'Missing information')} · "
            f"Salary Slip: {name_comparison.get('salary_slip_name') or 'Unavailable'} · "
            f"Bank Statement: {name_comparison.get('bank_statement_name') or 'Unavailable'}"
        )
        credits = salary_statement.get("bank_statement_salary_credits") or []
        if credits:
            st.caption(
                "Only transactions explicitly identified as salary/payroll are "
                "included; other bank credits are not assumed to be salary."
            )
            st.dataframe(
                [
                    {
                        "Date": item.get("date") or "Not stated",
                        "Salary credit": fmt_inr(item.get("amount")),
                        "Transaction description": item.get("description") or "—",
                    }
                    for item in credits
                ],
                width="stretch",
                hide_index=True,
            )
        st.write("**AI Finding:** " + str(salary_statement.get("explanation") or "No explanation available."))

    report_checks = report.get("checks") or []
    if report_checks:
        st.dataframe(
            [
                {
                    "Check": check.get("check", ""),
                    "Result": check.get("status", ""),
                    "Document value": check.get("document_value") or "—",
                    "Application value": check.get("declared_value") or "—",
                    "Evidence": check.get("evidence") or "—",
                    "Explanation": check.get("explanation") or "—",
                }
                for check in report_checks
            ],
            width="stretch",
            hide_index=True,
        )

    if not documents:
        missing = report.get("missing_categories") or []
        if missing:
            st.warning(
                "Missing required documents: "
                + ", ".join(str(item).replace("_", " ") for item in missing)
                + "."
            )
        return

    for index, document in enumerate(documents):
        fields = document.get("extracted_fields", {})
        checks = document.get("checks", [])
        status = document.get("verification_status", "Synthetic demo")
        filename = str(document.get("file_name", "Document"))
        category = str(document.get("category", document.get("doc_type", "Document")))
        with st.expander(
            f"{filename} · {category.replace('_', ' ').title()} · {status}",
            expanded=index == 0,
        ):
            st.write(
                "Extraction: "
                + str(
                    document.get(
                        "extraction_status",
                        "Synthetic document generated from applicant entries",
                    )
                )
            )
            if document.get("extraction_method"):
                st.write("Extraction method: " + str(document["extraction_method"]))
            st.write(
                "Explanation: "
                + str(document.get("explanation") or "Watermarked demo document.")
            )
            if fields:
                evidence = document.get("field_evidence", {})
                st.dataframe(
                    [
                        {
                            "Extracted field": key.replace("_", " ").title(),
                            "Value": value if value is not None else "Missing",
                            "Source evidence": evidence.get(key) or "No matching text line",
                        }
                        for key, value in fields.items()
                    ],
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info(
                    "No structured fields were extracted. The original PDF remains attached to this application."
                )
            if checks:
                st.dataframe(
                    [
                        {
                            "Check": check.get("check", ""),
                            "Result": check.get("status", ""),
                            "Document value": check.get("document_value") or "—",
                            "Application value": check.get("declared_value") or "—",
                            "Evidence": check.get("evidence") or "—",
                            "Explanation": check.get("explanation") or "—",
                        }
                        for check in checks
                    ],
                    width="stretch",
                    hide_index=True,
                )
            st.caption(
                "Authenticity: "
                + str(
                    document.get(
                        "authenticity_status", "Not independently verified"
                    )
                )
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
    columns = st.columns(len(STAGES), gap="large")
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
    clauses = policy.get("clauses", [])
    kyc_clause = next(
        (clause for clause in clauses if clause.get("clause_id") == "CP-6.1"),
        {},
    )
    kyc_observed = kyc_clause.get("observed", {})
    kyc_status = str(
        kyc_observed.get("status", kyc_observed.get("pan_status", ""))
    ).casefold()
    kyc_score = float(
        kyc_observed.get("name_match", kyc_observed.get("name_match_score", 1.0))
        or 0
    )
    kyc_referral = recommendation == "Refer" and kyc_clause.get("status") == "refer"
    if kyc_referral and kyc_score < 0.85 and (
        kyc_status == "verified"
        or "manual identity review"
        in str(kyc_observed.get("reason", "")).casefold()
    ):
        title = "REFER: manual identity review"
    elif kyc_referral and kyc_status != "verified":
        title = "REFER: complete eKYC"
    elif recommendation == "Refer" and documents_failed:
        title = "REFER: document review"
    elif recommendation == "Decline" and kyc_clause.get("status") == "decline":
        title = "DECLINE: invalid PAN"
    else:
        title = recommendation.upper()
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
    if kyc_referral:
        summary = (
            "Complete the simulated identity check before a person continues the review."
            if kyc_status != "verified"
            else "Identity needs manual review because the name match is below 0.85."
        )
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
    columns = st.columns(4, gap="large")
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
