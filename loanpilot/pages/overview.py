"""Overview page."""

from loanpilot.theme import render_placeholder


def render() -> None:
    """Render the overview placeholder."""
    render_placeholder(
        "Overview",
        "A landing page for the personal-loan approval demonstration.",
        6,
    )
