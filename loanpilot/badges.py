"""Implementation-status badges for the demo UI."""

from html import escape
from typing import Literal

import streamlit as st

BadgeKind = Literal["real", "simulated", "planned"]

_BADGES: dict[BadgeKind, tuple[str, str, str, str]] = {
    "real": ("✓", "Real (runs here)", "#e5f4e9", "#1f6b3b", "Real"),
    "simulated": ("◷", "Simulated (stub or synthetic)", "#fff2d6", "#805400", "Simulated"),
    "planned": ("○", "Planned (target state)", "#eef0f2", "#4b5563", "Planned"),
}


def implementation_badge(kind: BadgeKind) -> str:
    """Return an accessible, text-labelled implementation status chip."""
    if kind not in _BADGES:
        raise ValueError(f"Unsupported implementation badge kind: {kind}")
    icon, label, background, foreground, tooltip = _BADGES[kind]
    return (
        f'<span title="{escape(tooltip)}" '
        f'style="display:inline-flex;align-items:center;gap:.35rem;'
        f'padding:.2rem .65rem;border-radius:999px;background:{background};'
        f'color:{foreground};font-size:.82rem;font-weight:600;'
        f'border:1px solid {foreground}33;">'
        f'<span aria-hidden="true">{icon}</span>{escape(label)}</span>'
    )


def render_badge_legend() -> None:
    """Render the sidebar legend for implementation-status badges."""
    st.markdown("### Implementation status")
    for kind in ("real", "simulated", "planned"):
        st.markdown(implementation_badge(kind), unsafe_allow_html=True)
        st.caption(_BADGES[kind][1].split(" (", maxsplit=1)[1].rstrip(")"))
