"""Applications list and case-view tests."""

import pytest
from streamlit.testing.v1 import AppTest

from loanpilot.components import calculate_foir, fmt_inr
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.store import SQLiteStore


@pytest.fixture(scope="module")
def seeded_store(tmp_path_factory) -> SQLiteStore:
    """Create one isolated synthetic database for app smoke tests."""
    store = SQLiteStore(tmp_path_factory.mktemp("applications") / "demo.db")
    seed_demo_data(store, reset=True)
    return store


def _render_app(store: SQLiteStore) -> AppTest:
    """Create an AppTest script that renders with an isolated demo store."""
    script = (
        "from loanpilot.pages.applications import render\n"
        "from loanpilot.data.store import SQLiteStore\n"
        f"render(SQLiteStore({str(store.path)!r}))\n"
    )
    return AppTest.from_string(script)


def _render_navigation_app(store: SQLiteStore) -> AppTest:
    """Create a test navigation session with the shared registered page objects."""
    script = (
        "import streamlit as st\n"
        "from loanpilot.data.store import SQLiteStore\n"
        "from loanpilot.pages import applications\n"
        "applications.SQLiteStore = lambda: SQLiteStore("
        f"{str(store.path)!r})\n"
        "from loanpilot.navigation import NAVIGATION, OPERATE_PAGES\n"
        "navigation = st.navigation(NAVIGATION)\n"
        "if '_test_route_set' not in st.session_state:\n"
        "    st.session_state['_test_route_set'] = True\n"
        "    st.switch_page(OPERATE_PAGES['applications'])\n"
        "navigation.run()\n"
    )
    return AppTest.from_string(script)


def test_applications_list_renders_and_pins_demo_cases(seeded_store) -> None:
    """The list shows all 66 applications and pinned persona stories."""
    app = _render_app(seeded_store).run()
    assert not app.exception
    assert app.title[0].value == "Applications"
    assert any("Matching applications" in metric.label and metric.value == "66" for metric in app.metric)
    assert any("Priya Menon" in markdown.value for markdown in app.markdown)
    assert any(button.label == "Open Priya Menon case" for button in app.button)
    table = app.dataframe[0]
    assert len(table.value) == 66


def test_stage_filter_narrows_applications(seeded_store) -> None:
    """Selecting the Submitted stage narrows the list to six ready personas."""
    app = _render_app(seeded_store).run()
    app.selectbox(key="applications_stage").select("Submitted").run()
    assert not app.exception
    assert any(metric.label == "Matching applications" and metric.value == "6" for metric in app.metric)
    table = app.dataframe[0]
    assert len(table.value) == 6


@pytest.mark.parametrize(
    ("application_id", "applicant"),
    [
        ("APP-PERSONA-1", "Priya Menon"),
        ("APP-PERSONA-4", "Anita Rao"),
    ],
)
def test_opening_persona_case_renders_all_tabs(
    seeded_store, application_id: str, applicant: str
) -> None:
    """Opening a pinned persona case renders its full case-view tab set."""
    app = _render_app(seeded_store).run()
    app.button(key=f"open_{application_id}").click().run()
    assert not app.exception
    assert any(applicant in markdown.value for markdown in app.markdown)
    assert [tab.label for tab in app.tabs] == [
        "Summary",
        "Documents",
        "Financials",
        "Checks",
        "AI Trace",
        "Decision",
        "Sanction & Disbursement",
        "Audit Log",
    ]


def test_anita_financials_show_verified_foir_above_55_percent(seeded_store) -> None:
    """Anita's lower verified salary makes her computed FOIR exceed 55%."""
    app = _render_app(seeded_store).run()
    app.button(key="open_APP-PERSONA-4").click().run()
    financials = app.tabs[2]
    assert any(
        "FOIR · verified income" in markdown.value and "62.0%" in markdown.value
        for markdown in financials.markdown
    )


def test_case_opens_assessment_and_preserves_selected_application(seeded_store) -> None:
    """The assessment button switches pages with the selected case preserved."""
    app = _render_navigation_app(seeded_store).run()
    app.button(key="open_APP-PERSONA-1").click().run()
    app.button(key="open_ai_assessment").click().run()
    assert not app.exception
    assert app.title[0].value == "AI Assessment"
    assert app.session_state["selected_application"] == "APP-PERSONA-1"


def test_back_callback_returns_to_applications(seeded_store) -> None:
    """The case back button clears selection and returns to list mode."""
    app = _render_navigation_app(seeded_store).run()
    app.button(key="open_APP-PERSONA-1").click().run()
    app.button(key="back_to_applications").click().run()
    assert not app.exception
    assert app.title[0].value == "Applications"
    assert "selected_application" not in app.session_state


def test_empty_database_shows_load_demo_button(tmp_path) -> None:
    """An empty store provides a friendly load-data action without crashing."""
    empty_store = SQLiteStore(tmp_path / "empty.db")
    app = _render_app(empty_store).run()
    assert not app.exception
    assert any("No demo applications are loaded" in element.value for element in app.info)
    assert any(button.label == "Load demo data" for button in app.button)


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (400000, "Rs 4,00,000"),
        (95000, "Rs 95,000"),
        (15000000, "Rs 1,50,00,000"),
    ],
)
def test_format_inr_uses_indian_grouping(amount: int, expected: str) -> None:
    """Amounts are grouped in the expected Indian digit format."""
    assert fmt_inr(amount) == expected


def test_foir_formula_uses_total_monthly_obligations() -> None:
    """FOIR is total monthly EMI divided by verified monthly income."""
    assert calculate_foir(20000, 13538.16, 54120) == pytest.approx(
        (20000 + 13538.16) / 54120
    )
    assert calculate_foir(20000, 13538.16, 0) is None
