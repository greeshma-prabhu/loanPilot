"""About & FAQ page."""

from loanpilot.theme import render_placeholder


def render() -> None:
    """Render the about and FAQ placeholder."""
    render_placeholder(
        "About & FAQ",
        "Find project context, demo boundaries, and frequently asked questions.",
        7,
    )
