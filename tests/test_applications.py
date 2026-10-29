"""Applications list and case-view tests."""

from datetime import datetime
import pytest
from streamlit.testing.v1 import AppTest

from loanpilot.components import calculate_foir, fmt_inr
from loanpilot.data.queries import create_intake_application, list_applications
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.store import SQLiteStore


@pytest.fixture(scope="module")
def seeded_store(tmp_path_factory) -> SQLiteStore:
    """Create a store with legacy seeded records and one genuine intake record."""
    store = SQLiteStore(tmp_path_factory.mktemp("applications") / "demo.db")
    seed_demo_data(store, reset=True)
    _create_user_application(store)
    return store


def _create_user_application(store: SQLiteStore) -> str:
    """Create a user-owned intake record with the evidence needed by the case view."""
    application_id = "APP-NEW-APPLICATION-TEST"
    create_intake_application(
        {
            "name": "Test Applicant",
            "dob": "1990-01-01",
            "age": 36,
            "city": "Pune",
            "mobile": "9000000000",
            "employer": "Test Employer",
            "employment_type": "Salaried",
            "current_tenure_months": 60,
            "total_experience_months": 120,
            "net_monthly_income": 100000,
            "existing_emi": 0,
            "pan_demo_id": "TEST1234A",
        },
        {
            "requested_amount": 200000,
            "tenure_months": 36,
            "purpose": "Education",
            "submitted_at": datetime.now().isoformat(timespec="seconds"),
        },
        {
            "provider": "Test bureau",
            "score": 800,
            "thin_file": False,
            "active_accounts": 1,
            "enquiries_6m": 0,
            "max_dpd_24m": 0,
            "written_off": False,
            "utilization_pct": 5,
        },
        {"status": "verified", "checks": []},
        [
            {
                "doc_type": doc_type,
                "file_name": f"{doc_type}.pdf",
                "file_path": str(store.path.parent / f"{doc_type}.pdf"),
                "text_content": f"Verified test {doc_type} document.",
            }
            for doc_type in ("identity", "address", "income", "bank_statement")
        ],
        store,
        application_id=application_id,
    )
    return application_id


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
        "from loanpilot.pages import ai_assessment\n"
        "ai_assessment.SQLiteStore = lambda: SQLiteStore("
        f"{str(store.path)!r})\n"
        "from loanpilot.navigation import NAVIGATION, OPERATE_PAGES\n"
        "navigation = st.navigation(NAVIGATION)\n"
        "if '_test_route_set' not in st.session_state:\n"
        "    st.session_state['_test_route_set'] = True\n"
        "    st.switch_page(OPERATE_PAGES['applications'])\n"
        "navigation.run()\n"
    )
    return AppTest.from_string(script)


def test_applications_list_shows_only_user_created_records(seeded_store) -> None:
    """Seeded and synthetic cases stay stored but do not appear in the worklist."""
    app = _render_app(seeded_store).run()
    assert not app.exception
    assert app.title[0].value == "Applications"
    assert any("1 matching applications" in item.value for item in app.caption)
    assert any("Test Applicant" in markdown.value for markdown in app.markdown)
    assert not any("Priya Menon" in markdown.value for markdown in app.markdown)
    assert not any(button.key.startswith("open_APP-PERSONA-") for button in app.button)
    table = next(markdown.value for markdown in app.markdown if "<table" in markdown.value)
    assert table.count("<tr>") == 2
    stored_ids = set(list_applications({}, seeded_store)["application_id"])
    assert {"APP-PERSONA-1", "APP-HIST-001", "APP-NEW-APPLICATION-TEST"} <= stored_ids


def test_stage_filter_narrows_user_created_applications(seeded_store) -> None:
    """Stage filtering continues to work for genuine user-created applications."""
    app = _render_app(seeded_store).run()
    app.selectbox(key="applications_stage").select("Submitted").run()
    assert not app.exception
    assert any("1 matching applications" in item.value for item in app.caption)
    table = next(markdown.value for markdown in app.markdown if "<table" in markdown.value)
    assert table.count("<tr>") == 2


def test_opening_user_case_renders_all_tabs(seeded_store) -> None:
    """A user-created application opens its full case workspace."""
    application_id = "APP-NEW-APPLICATION-TEST"
    app = _render_app(seeded_store).run()
    app.selectbox(key="list_case_select").select(application_id).run()
    app.button(key="open_selected_application").click().run()
    assert not app.exception
    assert any("Test Applicant" in markdown.value for markdown in app.markdown)
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


def test_case_opens_assessment_and_preserves_selected_application(seeded_store) -> None:
    """The assessment button switches pages with the selected case preserved."""
    app = _render_navigation_app(seeded_store).run()
    app.selectbox(key="list_case_select").select("APP-NEW-APPLICATION-TEST").run()
    app.button(key="open_selected_application").click().run()
    app.button(key="open_ai_assessment").click().run()
    assert not app.exception
    assert app.title[0].value == "AI Assessment"
    assert app.session_state["selected_application"] == "APP-NEW-APPLICATION-TEST"


def test_back_callback_returns_to_applications(seeded_store) -> None:
    """The case back button clears selection and returns to list mode."""
    app = _render_navigation_app(seeded_store).run()
    app.selectbox(key="list_case_select").select("APP-NEW-APPLICATION-TEST").run()
    app.button(key="open_selected_application").click().run()
    app.button(key="back_to_applications").click().run()
    assert not app.exception
    assert app.title[0].value == "Applications"
    assert "selected_application" not in app.session_state


def test_seeded_only_store_shows_clean_empty_state_without_loading_demos(tmp_path) -> None:
    """A store containing only seeded examples is operationally empty."""
    empty_store = SQLiteStore(tmp_path / "empty.db")
    seed_demo_data(empty_store, reset=True)
    app = _render_app(empty_store).run()
    assert not app.exception
    assert [item.value for item in app.title] == ["Applications"]
    assert any("No applications have been submitted yet." in element.value for element in app.info)
    assert not any("Load demo data" in button.label for button in app.button)


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
