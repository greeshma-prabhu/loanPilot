"""Reusable presentation components for application case views."""

from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from loanpilot.badges import implementation_badge

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
    """Return a text-labelled status chip with a kind-specific icon."""
    styles = {
        "neutral": ("•", "#eef0f2", "#4b5563"),
        "success": ("✓", "#e5f4e9", "#1f6b3b"),
        "warning": ("!", "#fff2d6", "#805400"),
        "danger": ("×", "#fde8e7", "#9d2f2a"),
        "info": ("i", "#e4f1f8", "#205b79"),
        "demo": ("◇", "#e8f4f2", "#17665f"),
    }
    icon, background, foreground = styles.get(kind, styles["neutral"])
    return (
        f'<span title="{escape(text)}" style="display:inline-flex;align-items:center;'
        f'gap:.3rem;padding:.2rem .6rem;border-radius:999px;'
        f'background:{background};color:{foreground};font-size:.82rem;'
        f'font-weight:600;border:1px solid {foreground}33;">'
        f'<span aria-hidden="true">{icon}</span>{escape(text)}</span>'
    )


def case_header_card(application: Any) -> None:
    """Render a compact case identity and status header."""
    value = application.to_dict() if hasattr(application, "to_dict") else application
    name = escape(str(value.get("name", value.get("applicant", "Applicant"))))
    application_id = escape(str(value.get("application_id", "Application")))
    stage = escape(str(value.get("stage", "Unknown")))
    recommendation = value.get("ai_recommendation")
    recommendation_label = (
        f"AI: {escape(str(recommendation))}"
        if recommendation is not None and not pd.isna(recommendation)
        else "AI: pending"
    )
    st.markdown(
        '<div style="padding:1rem 1.2rem;border:1px solid #dce7e5;'
        'border-radius:.7rem;background:#fff;margin:.6rem 0 1rem;">'
        f'<div style="font-size:1.35rem;font-weight:650;color:#173b39;">{name}</div>'
        f'<div style="color:#526563;margin:.25rem 0 .7rem;">{application_id}</div>'
        f'{status_chip(stage, "info")} &nbsp; {status_chip(recommendation_label, "neutral")}'
        "</div>",
        unsafe_allow_html=True,
    )


def kpi_card(
    label: str,
    value: str,
    *,
    help_text: str | None = None,
    real: bool = False,
) -> None:
    """Render one KPI with an optional formula tooltip and computed badge."""
    badge = implementation_badge("real") if real else ""
    st.markdown(
        '<div style="min-height:6.2rem;padding:.8rem;border:1px solid #dce7e5;'
        'border-radius:.65rem;background:#fff;">'
        f'<div style="font-size:.88rem;color:#526563;">{escape(label)}</div>'
        f'<div style="font-size:1.25rem;font-weight:650;color:#173b39;'
        f'margin:.25rem 0;">{escape(value)}</div>'
        f'{badge}</div>',
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
            st.markdown(f"**{icon} {state}**")
            st.caption(stage)
