"""Applications page."""

from loanpilot.theme import render_placeholder


def render() -> None:
    """Render the applications placeholder."""
    render_placeholder(
        "Applications",
        "Review the application queue and its current processing stages.",
        3,
    )
