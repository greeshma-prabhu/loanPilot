"""Application identity and paths rooted at the project directory."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BANK_NAME = "Aarambh Bank"
APP_NAME = "LoanPilot: Agentic Personal Loan Approval"

DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIR / "loanpilot.db"
DOCUMENTS_DIR = DATA_DIR / "documents"
POLICY_PATH = PROJECT_ROOT / "loanpilot" / "policy" / "credit_policy.json"
DOCS_DIR = PROJECT_ROOT / "docs"
TESTS_DIR = PROJECT_ROOT / "tests"
APP_PATH = PROJECT_ROOT / "app.py"
