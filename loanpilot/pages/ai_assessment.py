"""AI Assessment page."""

from loanpilot.theme import render_placeholder


def render() -> None:
    """Render the AI assessment placeholder."""
    render_placeholder(
        "AI Assessment",
        "Inspect a proposed assessment and its supporting rationale.",
        4,
    )
