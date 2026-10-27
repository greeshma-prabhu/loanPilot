"""Smoke tests for the LoanPilot shell and placeholder pages."""

from streamlit.testing.v1 import AppTest

from loanpilot.badges import implementation_badge
from loanpilot.config import APP_PATH
from loanpilot.pages import (
    about_faq,
    ai_assessment,
    applications,
    approach_story,
    data_explorer,
    human_review,
    new_application,
    overview,
    technical_architecture,
)

PAGE_MODULES = [
    overview,
    applications,
    new_application,
    ai_assessment,
    human_review,
    approach_story,
    technical_architecture,
    data_explorer,
    about_faq,
]


def test_app_runs_without_exception() -> None:
    """The navigation entry point should render its default page."""
    app = AppTest.from_file(str(APP_PATH)).run()
    assert not app.exception
    assert any(button.label == "Reset demo data" for button in app.button)


def test_each_page_renders_without_exception() -> None:
    """Every page module should render independently."""
    for module in PAGE_MODULES:
        app = AppTest.from_string(
            f"from {module.__name__} import render\nrender()"
        ).run()
        assert not app.exception, module.__name__


def test_badge_helper_output() -> None:
    """Badge markup should include a visible label, icon, and tooltip."""
    badge = implementation_badge("simulated")
    assert "Simulated (stub or synthetic)" in badge
    assert "title=" in badge
    assert "aria-hidden" in badge
