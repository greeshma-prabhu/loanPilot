"""Data Explorer page."""

from loanpilot.theme import render_placeholder


def render() -> None:
    """Render the data explorer placeholder."""
    render_placeholder(
        "Data Explorer",
        "Explore the synthetic data model once it is introduced in a later phase.",
        7,
    )
