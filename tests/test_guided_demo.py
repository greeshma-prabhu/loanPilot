"""Tests for the isolated Guided Loan Journey walkthrough."""

import pytest
from streamlit.testing.v1 import AppTest

from loanpilot.pages import guided_demo


def _guided_demo_app() -> AppTest:
    return AppTest.from_string(
        "from loanpilot.pages.guided_demo import render\nrender()\n"
    )


def test_synthetic_assessment_calculates_emi_and_foir_from_inputs() -> None:
    """The demo EMI follows the reducing-balance formula and FOIR uses both EMIs."""
    results = guided_demo._assessment_results()
    monthly_rate = results["rate"] / 12
    expected_emi = (
        guided_demo.APPLICANT["requested_amount"]
        * monthly_rate
        * (1 + monthly_rate) ** guided_demo.APPLICANT["tenure_months"]
        / ((1 + monthly_rate) ** guided_demo.APPLICANT["tenure_months"] - 1)
    )
    expected_foir = (
        guided_demo.APPLICANT["existing_emi"] + expected_emi
    ) / guided_demo.APPLICANT["monthly_income"]

    assert results["emi"] == pytest.approx(expected_emi)
    assert results["foir"] == pytest.approx(expected_foir)
    assert results["policy"]["recommendation"] == "Approve"


@pytest.mark.parametrize(
    ("now", "remaining"),
    [(100.0, 5.0), (102.5, 2.5), (105.0, 0.0), (106.0, 0.0), (99.0, 5.0)],
)
def test_assessment_wait_is_five_seconds_and_nonblocking(
    now: float, remaining: float
) -> None:
    """Elapsed time is calculated without sleeping or blocking the Streamlit run."""
    assert guided_demo._assessment_remaining_seconds(100.0, now=now) == remaining


def test_demo_progression_override_rationale_and_restart() -> None:
    """Every stage is navigable, overrides require a reason, and restart is local."""
    app = _guided_demo_app().run()
    assert not app.exception
    assert any(
        "Illustrative demo using synthetic applicant data" in item.value
        for item in app.info
    )

    app.button(key="guided_demo_start").click().run()
    assert app.session_state["guided_demo_step"] == 0
    assert any("Priya Menon" in item.value for item in app.markdown)

    app.button(key="guided_demo_next").click().run()
    assert app.session_state["guided_demo_step"] == 1
    assert app.session_state["guided_demo_assessment_started_at"]
    assert app.progress
    app.session_state["guided_demo_assessment_ready"] = True
    app.run()
    assert not app.exception
    assert any(item.label == "FOIR" for item in app.metric)

    app.button(key="guided_demo_next").click().run()
    assert app.session_state["guided_demo_step"] == 2
    assert not app.exception
    app.radio(key="guided_demo_reviewer_outcome").set_value(
        "Override: Refer for additional review"
    ).run()
    assert app.button(key="guided_demo_next").disabled
    app.text_area(key="guided_demo_reviewer_rationale").set_value(
        "Additional verification is needed."
    ).run()
    app.button(key="guided_demo_next").click().run()
    assert app.session_state["guided_demo_step"] == 3
    assert any("Referred – Illustrative Demo" in item.value for item in app.markdown)

    app.button(key="guided_demo_restart").click().run()
    assert "guided_demo_started" not in app.session_state
    assert any(button.label == "Start Guided Demo" for button in app.button)
    assert not app.exception


def test_guided_demo_does_not_change_application_database(tmp_path) -> None:
    """Rendering and progressing the synthetic walkthrough leaves app data untouched."""
    from loanpilot.data.schema import create_schema
    from loanpilot.data.store import SQLiteStore

    store = SQLiteStore(tmp_path / "guided-demo-isolation.db")
    create_schema(store)
    before = int(
        store.query("SELECT COUNT(*) AS count FROM cur_applications").iloc[0]["count"]
    )

    app = _guided_demo_app().run()
    app.button(key="guided_demo_start").click().run()
    app.button(key="guided_demo_next").click().run()
    after = int(
        store.query("SELECT COUNT(*) AS count FROM cur_applications").iloc[0]["count"]
    )

    assert before == after
    assert not app.exception
