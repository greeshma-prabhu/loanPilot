"""Keep persistent user demo cases isolated from the test databases."""

from datetime import datetime
from uuid import uuid4

import pytest

from loanpilot import config
from loanpilot.data.queries import create_intake_application
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore
from loanpilot.pages.new_application import _document_texts


@pytest.fixture(scope="session", autouse=True)
def isolate_persistent_custom_cases(tmp_path_factory):
    """Prevent local permanent cases from changing deterministic fixture counts."""
    original = config.CUSTOM_CASES_PATH
    config.CUSTOM_CASES_PATH = (
        tmp_path_factory.mktemp("isolated-custom-cases") / "custom_cases.json"
    )
    yield
    config.CUSTOM_CASES_PATH = original


@pytest.fixture
def create_user_case():
    """Provide a real intake record factory for operational-page tests."""
    def create(store: SQLiteStore, application_id: str, name: str = "Test Applicant") -> str:
        create_schema(store)
        intake = {
            "name": name,
            "dob": "1990-01-01",
            "age": 36,
            "city": "Pune",
            "mobile": "9000000000",
            "employer": "Test Employer",
            "employment_type": "Salaried",
            "job_months": 60,
            "experience_months": 120,
            "income": 100000.0,
            "existing_emi": 0.0,
            "amount": 200000.0,
            "tenure": 36,
            "purpose": "Education",
            "pan": f"TEST{uuid4().hex[:8].upper()}",
            "document_problem": False,
            "problem_type": "",
        }
        documents = _document_texts(intake)
        create_intake_application(
            {
                "name": intake["name"],
                "dob": intake["dob"],
                "age": intake["age"],
                "city": intake["city"],
                "mobile": intake["mobile"],
                "employer": intake["employer"],
                "employment_type": intake["employment_type"],
                "current_tenure_months": intake["job_months"],
                "total_experience_months": intake["experience_months"],
                "net_monthly_income": intake["income"],
                "existing_emi": intake["existing_emi"],
                "pan_demo_id": intake["pan"],
            },
            {
                "requested_amount": intake["amount"],
                "tenure_months": intake["tenure"],
                "purpose": intake["purpose"],
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
                    "file_path": str(store.path.parent / f"{application_id}-{doc_type}.pdf"),
                    "text_content": text,
                }
                for doc_type, text in documents.items()
            ],
            store,
            application_id=application_id,
        )
        return application_id

    return create
