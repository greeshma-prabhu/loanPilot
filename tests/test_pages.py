"""Smoke tests for the LoanPilot shell and placeholder pages."""

from streamlit.testing.v1 import AppTest
import pytest
import pandas as pd

from loanpilot.badges import implementation_badge
from loanpilot.config import APP_PATH
from loanpilot.data.queries import save_assessment_decision
from loanpilot.data.schema import create_schema
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.store import SQLiteStore
from loanpilot.pages import overview
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

_STORE_PAGES = {
    "overview",
    "applications",
    "new_application",
    "ai_assessment",
    "human_review",
    "data_explorer",
}


@pytest.fixture(scope="module")
def seeded_store(tmp_path_factory) -> SQLiteStore:
    """Create an isolated seeded database for page rendering checks."""
    store = SQLiteStore(tmp_path_factory.mktemp("page-smoke") / "seeded.db")
    seed_demo_data(store, reset=True)
    return store


def _render_page(module, store: SQLiteStore) -> AppTest:
    """Render a page against a test-owned store where it accepts one."""
    page_name = module.__name__.rsplit(".", 1)[-1]
    argument = f"SQLiteStore({str(store.path)!r})" if page_name in _STORE_PAGES else ""
    imports = "from loanpilot.data.store import SQLiteStore\n" if argument else ""
    return AppTest.from_string(
        f"{imports}from {module.__name__} import render\nrender({argument})"
    )


def test_app_runs_without_exception() -> None:
    """The navigation entry point should render its default page."""
    app = AppTest.from_file(str(APP_PATH)).run()
    assert not app.exception
    assert any(button.label == "Start demo with Priya Menon" for button in app.button)


def test_know_more_opens_explanatory_navigation() -> None:
    """The sidebar Know more action opens its explanatory-page dialog."""
    app = AppTest.from_file(str(APP_PATH)).run()
    app.button(key="open_know_more").click().run()
    assert not app.exception
    assert any("Explore how this demonstration" in item.value for item in app.caption)


def test_know_more_pages_are_registered_in_hidden_navigation() -> None:
    """Dialog links target pages registered with Streamlit navigation."""
    from loanpilot.navigation import KNOW_MORE_PAGES, NAVIGATION

    registered_pages = {page for pages in NAVIGATION.values() for page in pages}
    assert set(KNOW_MORE_PAGES.values()).issubset(registered_pages)


@pytest.mark.parametrize(
    ("module", "data_state"),
    [(module, state) for module in PAGE_MODULES for state in ("empty", "seeded")],
    ids=lambda value: value.__name__.rsplit(".", 1)[-1] if hasattr(value, "__name__") else value,
)
def test_each_page_loads_for_empty_and_seeded_data(module, data_state, tmp_path, seeded_store) -> None:
    """Smoke-test every page with both empty and seeded database state."""
    if data_state == "seeded":
        store = seeded_store
    else:
        store = SQLiteStore(tmp_path / f"{module.__name__.rsplit('.', 1)[-1]}.db")
        create_schema(store)
    app = _render_page(module, store).run()
    assert not app.exception, f"{module.__name__} with {data_state} data"


def test_overview_empty_state_has_single_start_demo_action(tmp_path) -> None:
    """An empty dashboard directs the presenter to its single command-centre action."""
    store = SQLiteStore(tmp_path / "overview-empty.db")
    create_schema(store)
    app = _render_page(overview, store).run()
    assert not app.exception
    assert sum(button.label == "Start demo with Priya Menon" for button in app.button) == 1


def test_human_review_empty_assessments_points_to_overview(seeded_store) -> None:
    """The empty review queue directs presenters to AI Assessment."""
    app = _render_page(
        next(module for module in PAGE_MODULES if module.__name__.endswith(".human_review")),
        seeded_store,
    ).run()
    assert not app.exception
    assert any(
        "Nothing waiting for review. Run an assessment first." in item.value
        for item in app.info
    )
    assert any(button.label == "Open AI Assessment" for button in app.button)


def test_synthetic_data_banner_is_only_shown_on_about(seeded_store) -> None:
    """The synthetic-data statement is absent globally and retained in About & FAQ."""
    text = "Demonstration with synthetic data. Not a real bank system or credit decision."
    for module in PAGE_MODULES:
        app = _render_page(module, seeded_store).run()
        visible_text = "\n".join(
            str(element.value)
            for name in (
                "title", "header", "subheader", "caption", "markdown",
                "info", "warning", "success", "error",
            )
            for element in getattr(app, name, [])
        )
        if module is about_faq:
            assert text in visible_text
        else:
            assert text not in visible_text, module.__name__


def test_prepare_demo_skips_priya_and_is_idempotent(seeded_store, monkeypatch) -> None:
    """Starting demo assesses other cases and leaves Priya untouched."""
    calls = []

    def fake_assessment(application_id: str, store: SQLiteStore) -> None:
        calls.append(application_id)
        save_assessment_decision(
            application_id,
            "Approve",
            "{}",
            "2026-10-27T12:00:00",
            store,
        )

    monkeypatch.setattr(overview, "run_assessment", fake_assessment)
    assessed, skipped = overview._prepare_demo(seeded_store)
    assert assessed == 5
    assert skipped == 1
    assert len(calls) == 5

    applications = overview.list_applications({"demo_only": True}, seeded_store)
    priya = applications.loc[applications["applicant"] == "Priya Menon"].iloc[0]
    assert pd.isna(priya["ai_recommendation"])

    repeated_assessed, repeated_skipped = overview._prepare_demo(seeded_store)
    assert repeated_assessed == 0
    assert repeated_skipped == 6
    assert len(calls) == 5


def test_badge_helper_output() -> None:
    """Badge markup should include a visible label, icon, and tooltip."""
    badge = implementation_badge("simulated")
    assert "Simulated (stub or synthetic)" in badge
    assert "title=" in badge
    assert "aria-hidden" in badge
