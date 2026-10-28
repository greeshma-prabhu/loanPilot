"""Explanatory-page and safe Data Explorer tests."""

import json

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from loanpilot import config
from loanpilot.data.queries import (
    explorer_catalog,
    run_canned_read_query,
    validate_read_only_select,
)
from loanpilot.data.schema import create_schema
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.store import SQLiteStore
from loanpilot.ledger import ledger_frame
from loanpilot.pages import about_faq, approach_story, data_explorer, technical_architecture

PAGES = (approach_story, technical_architecture, data_explorer, about_faq)


def _render(page, docs_path=None, store=None) -> AppTest:
    """Create an isolated page-render test with optional project documentation."""
    prelude = (
        "from pathlib import Path\n"
        f"from {page.__name__} import render\n"
    )
    if docs_path is not None:
        prelude += (
            "from loanpilot import config\n"
            f"config.DOCS_DIR = Path({str(docs_path)!r})\n"
        )
    if store is not None:
        prelude += (
            "from loanpilot.data.store import SQLiteStore\n"
            f"render(SQLiteStore({str(store.path)!r}))\n"
        )
    else:
        prelude += "render()\n"
    return AppTest.from_string(prelude)


@pytest.mark.parametrize("page", PAGES)
def test_explanatory_pages_render_without_optional_documents(page, tmp_path) -> None:
    """Every Phase 7 page renders when the optional research note is absent."""
    docs = tmp_path / "docs"
    docs.mkdir()
    app = _render(page, docs_path=docs).run()
    assert not app.exception, page.__name__


@pytest.mark.parametrize("page", (approach_story, about_faq))
def test_research_and_usage_pages_render_when_docs_exist(page, tmp_path) -> None:
    """Optional research and AI usage Markdown is included when present."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "research_note.md").write_text("# Research\nSynthetic evidence note.", encoding="utf-8")
    (docs / "ai_usage_log.md").write_text("# AI usage\nRecorded tools.", encoding="utf-8")
    app = _render(page, docs_path=docs).run()
    assert not app.exception


def test_data_explorer_only_runs_read_only_selects(tmp_path) -> None:
    """Canned queries are SELECT-only, capped, and do not mutate the database."""
    store = SQLiteStore(tmp_path / "explorer.db")
    seed_demo_data(store, reset=True)
    before = store.table_counts()
    assert validate_read_only_select("SELECT application_id FROM cur_applications") == (
        "SELECT application_id FROM cur_applications LIMIT 10"
    )
    assert validate_read_only_select(
        "SELECT application_id FROM cur_applications LIMIT 900"
    ).endswith("LIMIT 10")
    for sql in (
        "DROP TABLE cur_applications",
        "UPDATE cur_applications SET stage='Sanction'",
        "SELECT 1; DELETE FROM cur_applications",
        "WITH x AS (SELECT 1) SELECT * FROM x",
    ):
        with pytest.raises(ValueError):
            validate_read_only_select(sql)
    for query_name in (
        "Recent applications",
        "Customer income sample",
        "Document inventory",
    ):
        assert len(run_canned_read_query(query_name, store)) <= 10
    with pytest.raises(ValueError):
        run_canned_read_query("DROP TABLE cur_applications", store)
    assert store.table_counts() == before
    app = _render(data_explorer, store=store).run()
    assert not app.exception


def test_explorer_catalog_has_three_layers_and_bounded_samples(tmp_path) -> None:
    """Catalog metadata includes each layer and never returns more than five sample rows."""
    store = SQLiteStore(tmp_path / "catalog.db")
    seed_demo_data(store, reset=True)
    catalog = explorer_catalog(store)
    assert set(catalog) == {"raw", "curated", "serving"}
    for objects in catalog.values():
        assert objects
        assert all(len(item["sample"]) <= 5 for item in objects)


def test_explorer_formats_canned_values_without_changing_raw_fields() -> None:
    """Visible query values use Indian grouping and readable date formatting."""
    from loanpilot.pages.data_explorer import _format_explorer_values

    frame = pd.DataFrame(
        {
            "requested_amount": [200000],
            "submitted_at": ["2026-10-27T15:07:00"],
        }
    )
    visible = _format_explorer_values(frame)
    assert visible.iloc[0]["Requested amount"] == "Rs 2,00,000"
    assert visible.iloc[0]["Submitted"] == "27 Oct 2026, 3:07 PM"
    assert frame.iloc[0]["requested_amount"] == 200000


def test_ledger_tables_follow_ledger_file() -> None:
    """Displayed ledger rows preserve component names and file-backed statuses."""
    expected = json.loads(config.LEDGER_PATH.read_text(encoding="utf-8"))
    actual = ledger_frame()
    assert actual["component"].tolist() == [entry["component"] for entry in expected]
    assert set(actual["status"]).issubset(
        {"Real", "Simulated", "Planned", "Not applicable"}
    )
    about_app = _render(about_faq).run()
    assert not about_app.exception
