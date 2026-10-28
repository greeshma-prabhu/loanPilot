"""First-run initialization tests with an isolated project root."""

from time import perf_counter

from loanpilot.data.bootstrap import bootstrap_demo_data
from loanpilot.data.queries import get_documents
from loanpilot.data.store import SQLiteStore


def test_bootstrap_initializes_repairs_and_is_idempotent(tmp_path) -> None:
    """Create missing sample data quickly, then restore missing PDFs safely."""
    project_root = tmp_path
    store = SQLiteStore(project_root / "data" / "loanpilot.db")

    started = perf_counter()
    assert bootstrap_demo_data(store, project_root=project_root) == "initialized"
    assert perf_counter() - started < 15
    assert store.table_counts()["cur_customers"] == 500
    assert store.table_counts()["cur_applications"] >= 60

    documents = get_documents("APP-PERSONA-1", store)
    assert len(documents) == 3
    missing_file = project_root / documents.iloc[0]["file_path"]
    missing_file.unlink()

    assert (
        bootstrap_demo_data(store, project_root=project_root)
        == "documents_restored"
    )
    assert missing_file.is_file()
    assert bootstrap_demo_data(store, project_root=project_root) is None
    assert store.table_counts()["raw_documents"] == 18
