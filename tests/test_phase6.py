"""Phase 6 application-intake and overview dashboard tests."""

import shutil

import pytest
from streamlit.testing.v1 import AppTest

from loanpilot import config
from loanpilot.data.queries import (
    create_intake_application,
    get_application,
    get_audit_log,
    get_agent_trace,
    get_bureau,
    get_documents,
    get_kyc,
    human_decision_is_override,
    list_intake_customers,
    list_applications,
    record_human_decision,
)
from loanpilot.data.demo_seed import seed_synthetic_applications
from loanpilot.data.schema import create_schema
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.store import SQLiteStore
from loanpilot.pages import overview
from loanpilot.pages.new_application import (
    _document_texts,
    _initial_intake,
    _pdf_bytes,
    _uploaded_identity_result,
    estimate_bureau_score,
)


@pytest.fixture(scope="module")
def seeded_store(tmp_path_factory) -> SQLiteStore:
    """Create one isolated synthetic database for dashboard and navigation tests."""
    store = SQLiteStore(tmp_path_factory.mktemp("phase6") / "demo.db")
    seed_demo_data(store, reset=True)
    seed_synthetic_applications(store)
    return store


def _navigation_app(store: SQLiteStore, start_page: str) -> AppTest:
    """Build a multipage AppTest around an isolated SQLite store."""
    script = (
        "import streamlit as st\n"
        "st.session_state['auth'] = {'name': 'Phase6 Analyst', 'role': 'Credit Analyst'}\n"
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
    """Five-step new-customer intake generates identity and financial evidence."""
    documents_dir = config.DATA_DIR / "test-final-flow-documents"
    uploads_dir = config.PROJECT_ROOT / "data" / "test-final-flow-uploads"
    monkeypatch.setattr(config, "DOCUMENTS_DIR", documents_dir)
    monkeypatch.setattr(config, "DATA_DIR", uploads_dir)
    app = _navigation_app(seeded_store, "new_application").run()
    assert not app.button(key="intake_next").disabled
    app.button(key="intake_next").click().run()
    assert app.session_state["intake_step"] == 0
    assert any("Name and city are required" in item.value for item in app.warning)
    app.text_input(key="intake_widget_name").set_value("Test Applicant").run()
    app.text_input(key="intake_widget_city").set_value("Pune").run()
    app.text_input(key="intake_widget_mobile").set_value("9000000000").run()
    app.button(key="intake_next").click().run()
    assert app.session_state["intake_step"] == 1
    assert any("Use fake or sample documents only" in item.value for item in app.warning)
    assert not any("could not read documents" in item.value for item in app.info)
    app.button(key="intake_generate_identity").click().run()
    assert app.session_state["intake"]["kyc"]["status"] == "verified"
    app.button(key="intake_next").click().run()
    app.text_input(key="intake_widget_employer").set_value("Demo Employer").run()
    app.button(key="intake_next").click().run()
    app.button(key="intake_next").click().run()
    assert app.session_state["intake_step"] == 4
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
    assert (
        list_applications({"search": application_id}, seeded_store).iloc[0]["owner"]
        == "Phase6 Analyst"
    )
    assert app.title[0].value == "New Application"
    docs = get_documents(application_id, seeded_store)
    assert len(docs) == 4
    assert "identity_sheet" in set(docs.doc_type)
    payload = get_kyc(application_id, seeded_store).iloc[0]["payload"]
    assert payload["status"] == "verified"
    assert payload["method"] == "Demo identity"
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
    identity_folder = uploads_dir / "uploads" / application_id
    if identity_folder.exists():
        shutil.rmtree(identity_folder)


def test_document_controls_keep_values_when_switching_modes(tmp_path) -> None:
    """Checkbox choices persist when their controls are temporarily hidden."""
    store = SQLiteStore(tmp_path / "intake-controls.db")
    create_schema(store)
    app = AppTest.from_string(
        "import streamlit as st\n"
        "from loanpilot.pages.new_application import _initial_intake, render\n"
        "from loanpilot.data.store import SQLiteStore\n"
        "st.session_state['intake_step'] = 4\n"
        "st.session_state['intake'] = {**_initial_intake(), "
        "'name': 'Test Applicant', 'city': 'Pune', 'employer': 'Demo Employer'}\n"
        f"render(SQLiteStore({str(store.path)!r}))\n"
    ).run()
    problem_key = "intake_widget_document_problem"
    mode_key = "intake_widget_document_mode"
    problem_box = app.checkbox(key=problem_key)
    problem_box.check().run()
    assert app.checkbox(key=problem_key).value is True

    app.radio(key=mode_key).set_value("Upload my own PDFs").run()
    app.radio(key=mode_key).set_value(
        "Generate synthetic documents from my entries"
    ).run()
    assert app.checkbox(key=problem_key).value is True
    assert app.session_state["intake"]["document_problem"] is True

    app.checkbox(key="intake_widget_consent").check().run()
    assert app.checkbox(key="intake_widget_consent").value is True


def test_autofill_uses_synthetic_details_and_keeps_consent_unchecked(tmp_path) -> None:
    """Autofill supplies a coherent example while leaving consent to the user."""
    store = SQLiteStore(tmp_path / "intake-autofill.db")
    create_schema(store)
    app = _render_page("new_application", store).run()
    app.text_input(key="intake_widget_name").set_value("Old entry").run()
    app.button(key="intake_autofill_demo").click().run()

    data = app.session_state["intake"]
    assert app.session_state["intake_step"] == 0
    assert data["name"] == "Demo Applicant"
    assert data["city"] == "Pune"
    assert data["mobile"] == "9000000000"
    assert data["employer"] == "Aarambh Demo Services"
    assert data["income"] == 60000.0
    assert data["consent"] is False
    assert data["declaration"] is False
    assert app.text_input(key="intake_widget_name").value == "Demo Applicant"


def _create_policy_case(store: SQLiteStore, kyc: dict) -> str:
    """Create a policy-clean synthetic application so KYC controls the outcome."""
    from datetime import date, datetime
    from uuid import uuid4

    data = _initial_intake()
    data.update(
        {
            "name": "Strong Test Applicant",
            "dob": "1990-01-01",
            "city": "Pune",
            "mobile": "9000000000",
            "employer": "Synthetic Test Employer",
            "employment_type": "Salaried",
            "job_months": 60,
            "experience_months": 120,
            "income": 100000.0,
            "existing_emi": 0.0,
            "amount": 200000.0,
            "tenure": 36,
            "purpose": "Education",
            "pan": f"DEMO{uuid4().hex[:8].upper()}",
            "document_problem": False,
        }
    )
    documents = _document_texts(data)
    application_id = f"APP-KYC-{uuid4().hex[:10].upper()}"
    applicant = {
        "name": data["name"],
        "dob": data["dob"],
        "age": 36,
        "city": data["city"],
        "mobile": data["mobile"],
        "employer": data["employer"],
        "employment_type": data["employment_type"],
        "current_tenure_months": data["job_months"],
        "total_experience_months": data["experience_months"],
        "net_monthly_income": data["income"],
        "existing_emi": data["existing_emi"],
        "pan_demo_id": data["pan"],
    }
    return create_intake_application(
        applicant,
        {
            "requested_amount": data["amount"],
            "tenure_months": data["tenure"],
            "purpose": data["purpose"],
            "submitted_at": datetime.now().isoformat(timespec="seconds"),
        },
        {
            "provider": "Synthetic test bureau",
            "score": 800,
            "thin_file": False,
            "active_accounts": 1,
            "enquiries_6m": 0,
            "max_dpd_24m": 0,
            "written_off": False,
            "utilization_pct": 5,
        },
        kyc,
        [
            {
                "doc_type": doc_type,
                "file_name": f"{doc_type}.pdf",
                "file_path": f"data/test/{application_id}/{doc_type}.pdf",
                "text_content": text,
            }
            for doc_type, text in documents.items()
        ],
        store,
        application_id=application_id,
    )


def _run_page_callback(source: str) -> AppTest:
    """Run one no-widget case callback inside a supported Streamlit context."""
    return AppTest.from_string(source).run()


def test_existing_customer_intake_skips_ekyc_and_reuses_customer(tmp_path, monkeypatch) -> None:
    """Existing core-banking customer intake retains the original customer ID."""
    store = SQLiteStore(tmp_path / "existing-customer.db")
    seed_demo_data(store, reset=True)
    customer = list_intake_customers(store).iloc[0]
    original_customer_count = store.table_counts()["cur_customers"]
    monkeypatch.setattr(
        config,
        "DOCUMENTS_DIR",
        config.PROJECT_ROOT / "data" / "test-existing-customer-documents",
    )
    app = _render_page("new_application", store).run()
    app.radio(key="intake_widget_customer_type").set_value("Existing customer").run()
    assert app.session_state["intake"]["customer_id"] == customer["customer_id"]
    assert app.session_state["intake"]["kyc"]["method"] == "KYC on file (core banking)"
    assert "From core banking" in "\n".join(item.value for item in app.caption)
    app.button(key="intake_next").click().run()
    assert app.session_state["intake_step"] == 1
    assert "intake_widget_identity_mode" not in app.session_state
    app.button(key="intake_next").click().run()
    app.button(key="intake_next").click().run()
    assert app.session_state["intake_step"] == 3
    app.checkbox(key="intake_widget_consent").check().run()
    app.checkbox(key="intake_widget_declaration").check().run()
    app.button(key="submit_application").click().run()
    assert not app.exception
    application_id = app.session_state["intake_application_id"]
    saved = get_application(application_id, store).iloc[0]
    assert saved["customer_id"] == customer["customer_id"]
    assert store.table_counts()["cur_customers"] == original_customer_count
    kyc = get_kyc(application_id, store).iloc[0]["payload"]
    assert kyc["status"] == "verified"
    assert kyc["method"] == "KYC on file (core banking)"


def test_pending_kyc_refers_and_verified_rerun_keeps_trace_history(tmp_path, monkeypatch) -> None:
    """The pending KYC panel completes identity and reruns with trace history."""
    monkeypatch.setattr("loanpilot.agent.llm._api_key", lambda: None)
    store = SQLiteStore(tmp_path / "kyc-rerun.db")
    create_schema(store)
    pending = {
        "status": "pending",
        "pan_status": "pending",
        "name_match": 0.0,
        "name_match_score": 0.0,
        "method": "Not completed",
        "reason": "eKYC was skipped.",
    }
    application_id = _create_policy_case(store, pending)
    from loanpilot.agent.orchestrator import run_assessment

    first = run_assessment(application_id, store)
    assert first["recommendation"] == "Refer"
    clause = next(item for item in first["policy"]["clauses"] if item["clause_id"] == "CP-6.1")
    assert clause["status"] == "refer"
    assert clause["observed"]["reason"] == "Complete eKYC before a decision."

    script = (
        "import streamlit as st\n"
        "from loanpilot.pages.applications import render\n"
        "from loanpilot.data.store import SQLiteStore\n"
        f"st.session_state['selected_application'] = {application_id!r}\n"
        f"render(SQLiteStore({str(store.path)!r}))\n"
    )
    app = _run_page_callback(script)
    assert not app.exception
    assert any("Complete eKYC to continue" in element.value for element in app.warning)
    app.radio(key=f"case_kyc_method_{application_id}").set_value("Use demo identity").run()
    app.button(key=f"case_kyc_complete_{application_id}").click().run()
    assert get_kyc(application_id, store).iloc[0]["payload"]["status"] == "verified"
    assert "eKYC completed" in " ".join(
        get_audit_log(application_id, store)["action"].tolist()
    )
    rerun_button = next(button for button in app.button if button.label == "Re-run AI assessment")
    rerun_button.click().run(timeout=60)
    saved = get_application(application_id, store).iloc[0]
    assert saved["ai_recommendation"] == "Approve"
    trace = store.query(
        "SELECT DISTINCT run_id FROM cur_agent_trace WHERE application_id = ?",
        (application_id,),
    )
    assert len(trace) == 2
    assert len(get_agent_trace(application_id, first["run_id"], store)) == 5
    assert len(get_agent_trace(application_id, store=store)) == 5


def test_kyc_manual_review_reason_and_invalid_pan_decline(tmp_path, monkeypatch) -> None:
    """A low name match refers for manual review; invalid PAN is declined."""
    monkeypatch.setattr("loanpilot.agent.llm._api_key", lambda: None)
    store = SQLiteStore(tmp_path / "kyc-policy.db")
    create_schema(store)
    from loanpilot.agent.orchestrator import run_assessment

    from loanpilot.pages.new_application import _apply_identity_problem

    problem = {
        **_initial_intake(),
        "document_problem": True,
        "problem_type": "Name differs from the identity document (match about 0.70)",
        "kyc": {
            "status": "verified",
            "pan_status": "verified",
            "name_match": 1.0,
            "name_match_score": 1.0,
            "method": "Demo identity",
        },
    }
    _apply_identity_problem(problem)
    assert problem["kyc"]["status"] == "pending"
    assert problem["kyc"]["name_match"] == 0.70
    mismatch_id = _create_policy_case(store, problem["kyc"])
    mismatch = run_assessment(mismatch_id, store)
    assert mismatch["recommendation"] == "Refer"
    mismatch_clause = next(
        item for item in mismatch["policy"]["clauses"] if item["clause_id"] == "CP-6.1"
    )
    assert mismatch_clause["status"] == "refer"
    assert mismatch_clause["observed"]["reason"] == "Manual identity review is required."

    invalid_id = _create_policy_case(
        store,
        {
            "status": "invalid",
            "pan_status": "not_found",
            "name_match": 1.0,
            "name_match_score": 1.0,
            "method": "eKYC document upload (simulated registry check)",
        },
    )
    invalid = run_assessment(invalid_id, store)
    assert invalid["recommendation"] == "Decline"
    invalid_clause = next(
        item for item in invalid["policy"]["clauses"] if item["clause_id"] == "CP-6.1"
    )
    assert invalid_clause["status"] == "decline"
    assert invalid_clause["observed"]["reason"] == "PAN is invalid or not found."


def test_identity_upload_matching_and_unreadable_inputs(tmp_path, monkeypatch) -> None:
    """Readable matching PDFs verify; missing text stays pending without exceptions."""
    monkeypatch.setattr("loanpilot.agent.llm._api_key", lambda: None)
    intake = _initial_intake()
    intake.update({"name": "Synthetic Holder", "pan": "DEMO1234AB"})
    matching = {}
    for doc_type in ("pan_identity", "aadhaar_identity"):
        text = f"Name: Synthetic Holder\nPAN: {intake['pan']}"
        matching[doc_type] = {
            "name": f"{doc_type}.pdf",
            "mime_type": "application/pdf",
            "content": _pdf_bytes("Synthetic identity", text.splitlines()),
        }
    result = _uploaded_identity_result({**intake, "identity_documents": matching})
    assert result["status"] == "verified"
    assert result["name_match"] == 1.0
    assert result["pan_status"] == "verified"

    unreadable = {
        doc_type: {
            "name": f"{doc_type}.pdf",
            "mime_type": "application/pdf",
            "content": b"not a readable PDF",
        }
        for doc_type in ("pan_identity", "aadhaar_identity")
    }
    failed = _uploaded_identity_result({**intake, "identity_documents": unreadable})
    assert failed["status"] == "pending"
    assert failed["reason"] == "could not read documents"


def test_rerun_is_blocked_after_human_decision(tmp_path, monkeypatch) -> None:
    """The callback refuses a fresh trace after a human has decided."""
    monkeypatch.setattr("loanpilot.agent.llm._api_key", lambda: None)
    store = SQLiteStore(tmp_path / "kyc-human-decision.db")
    create_schema(store)
    from loanpilot.agent.orchestrator import run_assessment

    application_id = _create_policy_case(
        store,
        {
            "status": "verified",
            "pan_status": "verified",
            "name_match": 1.0,
            "name_match_score": 1.0,
            "method": "Demo identity",
        },
    )
    result = run_assessment(application_id, store)
    decision = "Approve"
    record_human_decision(
        application_id,
        decision,
        "Approved after reviewing all synthetic evidence.",
        human_decision_is_override(result["recommendation"], decision),
        "Demo Reviewer",
        "2026-10-29T12:00:00",
        "Sanction",
        store,
    )
    before = len(get_agent_trace(application_id, store=store))
    script = (
        "from loanpilot.pages.applications import _rerun_case_assessment\n"
        "from loanpilot.data.store import SQLiteStore\n"
        f"_rerun_case_assessment({application_id!r}, SQLiteStore({str(store.path)!r}))\n"
    )
    app = _run_page_callback(script)
    assert not app.exception
    assert "cannot be rerun after a human decision" in app.session_state["kyc_rerun_error"]
    assert len(get_agent_trace(application_id, store=store)) == before


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


def test_overview_analytics_match_persisted_application_records(seeded_store) -> None:
    """Monthly chart periods and status totals match actual unique application rows."""
    records = overview._portfolio_records(seeded_store)
    assert records["application_id"].is_unique
    years = sorted(records["year"].unique().tolist(), reverse=True)
    assert years
    for year in years:
        monthly = overview._monthly_counts(records, int(year))
        assert int(monthly["count"].sum()) == int((records["year"] == year).sum())

    app = _render_page("overview", seeded_store).run()
    assert not app.exception
    assert app.title[0].value == "Welcome back"
    assert len(app.get("plotly_chart")) == 2
    assert app.selectbox[0].label == "Application year"
    assert [int(year) for year in app.selectbox[0].options] == years
    headings = [item.value for item in app.subheader]
    assert headings == [
        "Application Trends",
        "Needs Your Attention",
        "Recent Applications",
    ]


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
        assert any("Application trends will appear" in item.value for item in app.info)
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
