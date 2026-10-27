"""New Application page."""

from loanpilot.theme import render_placeholder


def render() -> None:
    """Render the new application placeholder."""
    render_placeholder(
        "New Application",
        "Start a personal-loan application through a guided intake flow.",
        6,
    )
