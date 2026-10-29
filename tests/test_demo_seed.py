"""Persistence, reconciliation, and dashboard aggregation for synthetic examples."""

from loanpilot.data.demo_seed import seed_synthetic_applications
from loanpilot.data.queries import list_applications
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore
from loanpilot.pages.overview import _portfolio_records
from streamlit.testing.v1 import AppTest


def test_app_startup_seeds_each_database_path_once(tmp_path, monkeypatch) -> None:
    """Authenticated reruns do not repeatedly invoke the seeding routine."""
    import loanpilot.data.demo_seed as demo_seed
    from app import _seed_demo_database_once

    store = SQLiteStore(tmp_path / "seed-once.db")
    calls = []
    monkeypatch.setattr(
        demo_seed,
        "seed_synthetic_applications",
        lambda database: calls.append(database.path),
    )

    _seed_demo_database_once(store)
    _seed_demo_database_once(store)

    assert calls == [store.path]


def test_seed_creates_exactly_ten_labeled_records_without_external_evidence(
    tmp_path,
) -> None:
    store = SQLiteStore(tmp_path / "synthetic-seed.db")
    create_schema(store)

    assert seed_synthetic_applications(store) == 10
    assert seed_synthetic_applications(store) == 0
    assert store.query(
        "SELECT COUNT(*) AS count FROM cur_applications "
        "WHERE application_id LIKE 'APP-SYNTH-%'"
    ).iloc[0]["count"] == 10
    assert store.query(
        "SELECT COUNT(*) AS count FROM demo_seed_markers "
        "WHERE seed_name = 'overview_synthetic_applications'"
    ).iloc[0]["count"] == 1
    assert store.query(
        "SELECT COUNT(*) AS count FROM raw_documents"
    ).iloc[0]["count"] == 0
    assert store.query(
        "SELECT COUNT(*) AS count FROM raw_bureau_responses"
    ).iloc[0]["count"] == 0
    assert store.query(
        "SELECT COUNT(*) AS count FROM raw_kyc_responses"
    ).iloc[0]["count"] == 0
    assert store.query(
        "SELECT COUNT(*) AS count FROM cur_disbursements"
    ).iloc[0]["count"] == 0

    listed = list_applications({"user_created_only": True}, store)
    assert len(listed) == 10
    assert listed["application_id"].str.startswith("APP-SYNTH-").all()

    portfolio = _portfolio_records(store)
    assert len(portfolio) == 10
    assert portfolio["status"].value_counts().to_dict() == {
        "Pending": 8,
        "Approved": 1,
        "Rejected": 1,
    }


def test_seed_preserves_existing_user_application_and_reconciles_missing_seed_row(
    tmp_path,
) -> None:
    store = SQLiteStore(tmp_path / "synthetic-seed-existing.db")
    create_schema(store)
    store.execute(
        """
        INSERT INTO cur_customers (
            customer_id, name, dob, age, city, employer, employment_type,
            current_tenure_months, total_experience_months, net_monthly_income,
            pan_demo_id, kyc_status, relationship_since
        ) VALUES (
            'C-USER-EXISTING', 'Existing User', '1990-01-01', 36, 'Pune',
            'Employer', 'Salaried', 24, 60, 50000, 'USER-PAN-1',
            'Not checked', ''
        )
        """
    )
    store.execute(
        """
        INSERT INTO cur_applications (
            application_id, customer_id, requested_amount, tenure_months,
            purpose, channel, submitted_at, stage
        ) VALUES (
            'APP-USER-EXISTING', 'C-USER-EXISTING', 125000, 24,
            'Education', 'Online', '2026-01-01T10:00:00', 'Pending'
        )
        """
    )

    assert seed_synthetic_applications(store) == 10
    assert seed_synthetic_applications(store) == 0
    existing = store.query(
        "SELECT c.name, a.requested_amount, a.stage "
        "FROM cur_applications a JOIN cur_customers c "
        "ON c.customer_id = a.customer_id "
        "WHERE a.application_id = 'APP-USER-EXISTING'"
    ).iloc[0]
    assert existing.to_dict() == {
        "name": "Existing User",
        "requested_amount": 125000.0,
        "stage": "Pending",
    }
    assert len(store.query("SELECT application_id FROM cur_applications")) == 11
    assert len(_portfolio_records(store)) == 11
    app = AppTest.from_string(
        "from loanpilot.data.store import SQLiteStore\n"
        "from loanpilot.pages.overview import render\n"
        f"render(SQLiteStore({str(store.path)!r}))"
    ).run()
    assert not app.exception
    assert [metric.value for metric in app.metric] == ["11", "1", "9", "1"]
    rendered = "\n".join(
        str(element.value)
        for name in ("info", "caption", "markdown")
        for element in getattr(app, name, [])
    )
    assert "10 clearly labeled synthetic demo applications" not in rendered
    assert "10 dated applications in" not in rendered
    assert "10 applications across all available dates" not in rendered

    store.execute("DELETE FROM cur_decisions WHERE application_id = 'APP-SYNTH-003'")
    assert seed_synthetic_applications(store) == 0
    assert store.query(
        "SELECT COUNT(*) AS count FROM cur_decisions "
        "WHERE application_id = 'APP-SYNTH-003'"
    ).iloc[0]["count"] == 1
