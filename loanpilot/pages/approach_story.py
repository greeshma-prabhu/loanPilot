"""Approach Story page."""

from loanpilot.theme import render_placeholder


def render() -> None:
    """Render the approach story placeholder."""
    render_placeholder(
        "Approach Story",
        "Explain the intended customer journey and agentic approach.",
        7,
    )
