"""Phase 6 application-intake and overview dashboard tests."""

import shutil

import pytest
from streamlit.testing.v1 import AppTest

from loanpilot import config
from loanpilot.data.queries import (
    create_intake_application,
    get_application,
    get_audit_log,
    get_bureau,
    get_documents,
    get_kyc,
    list_applications,
    overview_metrics,
)
from loanpilot.data.schema import create_schema
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.store import SQLiteStore
from loanpilot.pages import overview
from loanpilot.pages.new_application import estimate_bureau_score


@pytest.fixture(scope="module")
def seeded_store(tmp_path_factory) -> SQLiteStore:
    """Create one isolated synthetic database for dashboard and navigation tests."""
    store = SQLiteStore(tmp_path_factory.mktemp("phase6") / "demo.db")
    seed_demo_data(store, reset=True)
    return store


def _navigation_app(store: SQLiteStore, start_page: str) -> AppTest:
    """Build a multipage AppTest around an isolated SQLite store."""
    script = (
        "import streamlit as st\n"
        "from loanpilot.data.store import SQLiteStore\n"
        "from loanpilot.pages import ai_assessment, new_application, overview\n"
        f"store_path = {str(store.path)!r}\n"
        "new_application.SQLiteStore = lambda: SQLiteStore(store_path)\n"
        "ai_assessment.SQLiteStore = lambda: SQLiteStore(store_path)\n"
        "overview.SQLiteStore = lambda: SQLiteStore(store_path)\n"
        "from loanpilot.navigation import NAVIGATION, OPERATE_PAGES\n"
        "navigation = st.navigation(NAVIGATION)\n"
        "if '_phase6_route_set' not in st.session_state:\n"
        "    st.session_state['_phase6_route_set'] = True\n"
        f"    st.switch_page(OPERATE_PAGES[{start_page!r}])\n"
        "navigation.run()\n"
    )
    return AppTest.from_string(script)


def _render_page(module: str, store: SQLiteStore) -> AppTest:
    """Render one page with a test-owned store."""
    script = (
        f"from loanpilot.pages.{module} import render\n"
        "from loanpilot.data.store import SQLiteStore\n"
        f"render(SQLiteStore({str(store.path)!r}))\n"
    )
    return AppTest.from_string(script)


def test_custom_applicant_submits_and_lands_on_assessment(
    seeded_store, monkeypatch
) -> None:
    """Four-step intake generates flagged documents and opens the submitted case."""
    documents_dir = config.DATA_DIR / "test-final-flow-documents"
    monkeypatch.setattr(config, "DOCUMENTS_DIR", documents_dir)
    app = _navigation_app(seeded_store, "new_application").run()
    assert app.button(key="intake_next").disabled
    app.text_input(key="intake_widget_name").set_value("Test Applicant").run()
    app.text_input(key="intake_widget_city").set_value("Pune").run()
    app.text_input(key="intake_widget_mobile").set_value("9000000000").run()
    app.button(key="intake_next").click().run()
    app.text_input(key="intake_widget_employer").set_value("Demo Employer").run()
    app.button(key="intake_next").click().run()
    app.button(key="intake_next").click().run()
    assert app.radio(key="intake_widget_document_mode").value.startswith("Generate")
    app.checkbox(key="intake_widget_document_problem").check().run()
    app.selectbox(key="intake_widget_problem_type").select(
        "Salary credits about 30% below the payslip"
    ).run()
    app.checkbox(key="intake_widget_consent").check().run()
    app.checkbox(key="intake_widget_declaration").check().run()
    app.button(key="submit_application").click().run(timeout=20)
    assert not app.exception
    application_id = app.session_state["intake_application_id"]
    assert app.title[0].value == "New Application"
    docs = get_documents(application_id, seeded_store)
    assert len(docs) == 3
    statement = docs.loc[
        docs.doc_type == "bank_statement_summary", "text_content"
    ].iloc[0]
    assert "Average monthly salary credits: Rs 35,000.00" in statement
    app.button(key="intake_run_assessment").click().run()
    assert app.title[0].value == "AI Assessment"
    assert app.session_state["selected_application"] == application_id
    assert app.selectbox(key="assessment_application_selector").value == application_id
    from loanpilot.agent.orchestrator import run_assessment

    run_assessment(application_id, seeded_store)
    trace = seeded_store.query(
        "SELECT tool_calls_json FROM cur_agent_trace "
        "WHERE application_id = ? AND step_no = 1",
        (application_id,),
    )
    assert "document_failure" in trace.iloc[-1]["tool_calls_json"]
    for document in get_documents(application_id, seeded_store).to_dict("records"):
        assert (config.PROJECT_ROOT / document["file_path"]).is_file()
    folder = documents_dir / application_id
    if folder.exists():
        shutil.rmtree(folder)


def test_custom_applicant_persists_case_documents_and_mock_responses(tmp_path) -> None:
    """Intake writes the customer, application, document, bureau, KYC and audit rows."""
    store = SQLiteStore(tmp_path / "custom.db")
    create_schema(store)
    applicant = {
        "name": "Demo Applicant",
        "dob": "1994-06-15",
        "age": 32,
        "city": "Pune",
        "mobile": "9000000000",
        "employer": "Synthetic Employer",
        "employment_type": "Salaried",
        "current_tenure_months": 10,
        "total_experience_months": 10,
        "net_monthly_income": 50000,
        "existing_emi": 0,
        "pan_demo_id": "DEMO-TEST-1001",
    }
    application = {
        "requested_amount": 200000,
        "tenure_months": 36,
        "purpose": "Education",
        "submitted_at": "2026-10-27T12:00:00",
    }
    bureau = {"score": None, "thin_file": True, "provider": "Synthetic test"}
    kyc = {"pan_status": "pending", "name_match_score": 1.0}
    documents = [
        {
            "doc_type": "payslip",
            "file_name": "payslip.pdf",
            "file_path": "data/uploads/test/payslip.pdf",
            "text_content": "[DOCUMENT FLAG: PDF could not be read]",
        }
    ]
    application_id = create_intake_application(
        applicant, application, bureau, kyc, documents, store
    )
    saved = get_application(application_id, store).iloc[0]
    assert saved["stage"] == "Submitted"
    assert saved["requested_amount"] == 200000
    assert saved["net_monthly_income"] == 50000
    assert saved["mobile"] == "9000000000"
    assert len(get_documents(application_id, store)) == 1
    assert "[DOCUMENT FLAG" in get_documents(application_id, store).iloc[0]["text_content"]
    assert bool(get_bureau(application_id, store).iloc[0]["payload"]["thin_file"])
    assert get_kyc(application_id, store).iloc[0]["payload"]["pan_status"] == "pending"
    assert len(get_audit_log(application_id, store)) == 1
    assert store.table_counts()["cur_customers"] == 1
    assert estimate_bureau_score(50000, 0, 10, 10, "DEMO-TEST-1001") is None


def test_bureau_score_is_stable_and_responds_to_income_burden_and_tenure() -> None:
    """The deterministic bureau score reflects income, obligations and tenure."""
    base = estimate_bureau_score(50000, 5000, 12, 24, "DEMO-STABLE")
    assert base == estimate_bureau_score(50000, 5000, 12, 24, "DEMO-STABLE")
    assert estimate_bureau_score(80000, 0, 60, 24, "DEMO-HIGH") > base
    assert estimate_bureau_score(50000, 20000, 12, 24, "DEMO-DEBT") < base
    assert estimate_bureau_score(50000, 0, 10, 11, "DEMO-THIN") is None


def test_overview_metrics_match_database_counts(seeded_store) -> None:
    """Dashboard counters agree with independent direct table counts."""
    metrics = overview_metrics(seeded_store)
    pipeline = seeded_store.query(
        """
        SELECT COUNT(*) AS count FROM cur_applications
        WHERE stage NOT IN ('Rejected', 'Disbursed (simulated)', 'Awaiting documents')
        """
    ).iloc[0]["count"]
    review = seeded_store.query(
        "SELECT COUNT(*) AS count FROM cur_applications WHERE stage = ?",
        ("Human Review",),
    ).iloc[0]["count"]
    approvals = seeded_store.query(
        "SELECT COUNT(*) AS count FROM cur_decisions WHERE ai_recommendation = ?",
        ("Approve",),
    ).iloc[0]["count"]
    assert metrics["pipeline_count"] == pipeline
    assert metrics["pending_review_count"] == review
    assert metrics["approve_count"] == approvals

    app = _render_page("overview", seeded_store).run()
    assert not app.exception
    assert app.title[0].value == "Overview"
    assert any("Start demo with Priya Menon" == button.label for button in app.button)
    chart_titles = [item.value for item in app.markdown]
    assert any("Open cases by stage" in title for title in chart_titles)
    assert any("AI decision mix" in title for title in chart_titles)
    assert any(item.label == "Risk-band distribution" for item in app.expander)
    cases = overview._demo_custom_cases(seeded_store)
    active = ~cases["stage"].isin(
        {"Rejected", "Disbursed (simulated)", "Awaiting documents"}
    )
    closed = ~active
    assert len(cases) == int(active.sum()) + int(closed.sum())


def test_guided_demo_opens_priya_case(seeded_store, monkeypatch) -> None:
    """The dashboard assesses peers but leaves Priya live for the presenter."""
    monkeypatch.setattr("loanpilot.agent.llm._api_key", lambda: None)
    app = _navigation_app(seeded_store, "overview").run()
    app.button(key="start_guided_demo").click().run(timeout=30)
    assert not app.exception
    assert app.title[0].value == "Case workspace"
    assert app.session_state["selected_application"] == "APP-PERSONA-1"
    assert get_application("APP-PERSONA-1", seeded_store).iloc[0][
        "ai_recommendation"
    ] is None
    for application_number in range(2, 7):
        assert get_application(
            f"APP-PERSONA-{application_number}", seeded_store
        ).iloc[0]["ai_recommendation"] is not None


def test_shared_handoff_button_carries_case_to_human_review(monkeypatch) -> None:
    """The shared decision button selects its case before switching pages."""
    monkeypatch.setattr("streamlit.switch_page", lambda page: None)
    app = AppTest.from_string(
        "from loanpilot.components import render_human_review_button\n"
        "render_human_review_button('APP-PERSONA-4')\n"
    ).run()
    app.button(key="decision_review_APP-PERSONA-4").click().run()
    assert not app.exception
    assert app.session_state["review_open"] == "APP-PERSONA-4"
    assert app.session_state["selected_application"] == "APP-PERSONA-4"


@pytest.mark.parametrize("module", ["overview", "new_application"])
def test_phase6_pages_render_with_empty_database(module: str, tmp_path) -> None:
    """Dashboard and intake show a friendly empty state without data."""
    store = SQLiteStore(tmp_path / f"{module}.db")
    create_schema(store)
    app = _render_page(module, store).run()
    assert not app.exception
    if module == "overview":
        assert any(button.label == "Start demo with Priya Menon" for button in app.button)
    else:
        assert app.title[0].value == "New Application"


def test_permanent_custom_case_survives_reset_but_temporary_case_does_not(
    tmp_path, monkeypatch
) -> None:
    """Reset recreates saved custom definitions and drops unsaved custom rows."""
    custom_path = tmp_path / "loanpilot" / "data" / "custom_cases.json"
    monkeypatch.setattr(config, "CUSTOM_CASES_PATH", custom_path)
    project_root = tmp_path / "project"
    project_root.mkdir()
    store = SQLiteStore(tmp_path / "permanent.db")
    applicant_data = {
        "name": "Permanent Demo",
        "dob": "1994-06-15",
        "city": "Pune",
        "pan": "DEMO-PERMANENT",
        "mobile": "9000000000",
        "employer": "Demo Employer",
        "employment_type": "Salaried",
        "job_months": 10,
        "experience_months": 10,
        "income": 50000.0,
        "existing_emi": 0.0,
        "amount": 200000.0,
        "tenure": 36,
        "purpose": "Education",
        "document_mode": "Generate synthetic documents from my entries",
        "document_problem": False,
        "problem_type": "Salary credits about 30% below the payslip",
        "uploads": {},
        "consent": True,
        "declaration": True,
        "permanent": True,
    }
    from loanpilot.pages.new_application import _permanent_case_entry

    _permanent_case_entry(applicant_data, "APP-CUSTOM-1")
    seed_demo_data(store, reset=True, project_root=project_root)
    assert not get_application("APP-CUSTOM-1", store).empty

    temporary_id = create_intake_application(
        {
            "name": "Temporary Demo",
            "dob": "1994-06-15",
            "age": 32,
            "city": "Pune",
            "mobile": "9000000001",
            "employer": "Demo Employer",
            "employment_type": "Salaried",
            "current_tenure_months": 10,
            "total_experience_months": 10,
            "net_monthly_income": 50000,
            "existing_emi": 0,
            "pan_demo_id": "DEMO-TEMPORARY",
        },
        {
            "requested_amount": 200000,
            "tenure_months": 36,
            "purpose": "Education",
            "submitted_at": "2026-10-28T12:00:00",
        },
        {"score": None, "thin_file": True},
        {"pan_status": "pending"},
        [],
        store,
        application_id="APP-NEW-TEMPORARY",
    )
    seed_demo_data(store, reset=True, project_root=project_root)
    assert not get_application("APP-CUSTOM-1", store).empty
    assert get_application(temporary_id, store).empty
    assert custom_path.is_file()


def test_unreadable_pdf_returns_explicit_flag() -> None:
    """Malformed PDF bytes yield a flagged text result instead of an exception."""
    from loanpilot.pages.new_application import _extract_pdf_text

    text, flag = _extract_pdf_text(b"not a PDF")
    assert text == ""
    assert flag
