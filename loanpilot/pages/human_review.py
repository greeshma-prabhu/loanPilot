"""Human Review page."""

from loanpilot.theme import render_placeholder


def render() -> None:
    """Render the human review placeholder."""
    render_placeholder(
        "Human Review",
        "Provide a review workspace for a human decision-maker.",
        5,
    )
