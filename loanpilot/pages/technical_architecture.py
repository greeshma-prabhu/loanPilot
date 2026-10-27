"""Technical Architecture page."""

from loanpilot.theme import render_placeholder


def render() -> None:
    """Render the technical architecture placeholder."""
    render_placeholder(
        "Technical Architecture",
        "Show the target components and their responsibilities.",
        7,
    )
