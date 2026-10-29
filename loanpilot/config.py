"""Application identity and paths rooted at the project directory."""

from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BANK_NAME = "Aarambh Bank"
APP_NAME = "LoanPilot: Agentic Personal Loan Approval"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
BANK_LOGO_PATH = PROJECT_ROOT / "loanpilot" / "assets" / "aarambh-bank-logo.svg"

DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIR / "loanpilot.db"
DOCUMENTS_DIR = DATA_DIR / "documents"
DOCUMENT_LIBRARY_DIR = DATA_DIR / "document_library"
CUSTOM_CASES_PATH = PROJECT_ROOT / "loanpilot" / "data" / "custom_cases.json"
POLICY_PATH = PROJECT_ROOT / "loanpilot" / "policy" / "credit_policy.json"
ILLUSTRATIVE_METRICS_PATH = (
    PROJECT_ROOT / "loanpilot" / "policy" / "illustrative_metrics.json"
)
LEDGER_PATH = PROJECT_ROOT / "loanpilot" / "ledger.json"
AGENT_RECORDED_DIR = PROJECT_ROOT / "loanpilot" / "agent" / "recorded"
DOCS_DIR = PROJECT_ROOT / "docs"
TESTS_DIR = PROJECT_ROOT / "tests"
APP_PATH = PROJECT_ROOT / "app.py"
