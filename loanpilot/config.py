"""Application identity and paths rooted at the project directory."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BANK_NAME = "Aarambh Bank"
APP_NAME = "LoanPilot: Agentic Personal Loan Approval"

DATA_DIR = PROJECT_ROOT / "data"
DOCS_DIR = PROJECT_ROOT / "docs"
TESTS_DIR = PROJECT_ROOT / "tests"
APP_PATH = PROJECT_ROOT / "app.py"

