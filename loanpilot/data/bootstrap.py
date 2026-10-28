"""First-run initialization and repair for the synthetic demo data."""

from pathlib import Path
from threading import Lock

from loanpilot.config import DATABASE_PATH, PROJECT_ROOT
from loanpilot.data.documents import seed_persona_documents, validate_persona_documents
from loanpilot.data.policy import seed_policy_docs
from loanpilot.data.queries import get_persona_document_records
from loanpilot.data.schema import create_schema
from loanpilot.data.seed import PERSONAS, seed_demo_data
from loanpilot.data.store import SQLiteStore

_PERSONA_DOCUMENT_TYPES = {
    "payslip",
    "bank_statement_summary",
    "kyc_sheet",
}
_BOOTSTRAP_LOCK = Lock()


def bootstrap_demo_data(
    store: SQLiteStore | None = None,
    *,
    project_root: Path = PROJECT_ROOT,
) -> str | None:
    """Create missing schema, synthetic seed data, policy rows, and sample PDFs."""
    with _BOOTSTRAP_LOCK:
        return _bootstrap_demo_data(store, project_root=project_root)


def _bootstrap_demo_data(
    store: SQLiteStore | None,
    *,
    project_root: Path,
) -> str | None:
    """Run bootstrap while holding the process-wide initialization lock."""
    database_path = (
        DATABASE_PATH
        if project_root == PROJECT_ROOT
        else project_root / "data" / "loanpilot.db"
    )
    store = store or SQLiteStore(database_path)
    documents_dir = project_root / "data" / "documents"
    create_schema(store)

    counts = store.table_counts()
    if counts.get("cur_customers", 0) == 0:
        seed_demo_data(store, project_root=project_root)
        return "initialized"

    if counts.get("raw_policy_docs", 0) == 0:
        seed_policy_docs(store)

    if not _persona_documents_are_complete(store, documents_dir, project_root):
        seed_persona_documents(
            store,
            documents_dir=documents_dir,
            project_root=project_root,
        )
        validate_persona_documents(store, project_root=project_root)
        return "documents_restored"
    return None


def _persona_documents_are_complete(
    store: SQLiteStore,
    documents_dir: Path,
    project_root: Path,
) -> bool:
    """Check all seeded persona documents and their project-rooted files."""
    application_ids = [f"APP-{persona_key}" for persona_key in PERSONAS]
    saved_personas = store.query(
        "SELECT application_id FROM cur_applications "
        "WHERE application_id LIKE 'APP-PERSONA-%'"
    )
    if set(saved_personas["application_id"]) != set(application_ids):
        return True
    rows = get_persona_document_records(application_ids, store)
    expected = {
        (application_id, document_type)
        for application_id in application_ids
        for document_type in _PERSONA_DOCUMENT_TYPES
    }
    found = {
        (str(row.application_id), str(row.doc_type))
        for row in rows.itertuples(index=False)
        if row.doc_type is not None
    }
    if found != expected or not documents_dir.is_dir():
        return False
    return all(
        (project_root / Path(row.file_path)).is_file()
        and (project_root / Path(row.file_path)).stat().st_size > 0
        for row in rows.itertuples(index=False)
        if row.file_path is not None
    )
