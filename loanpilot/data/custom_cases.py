"""Persistence helpers for permanent synthetic demo cases."""

import json
from datetime import date
from pathlib import Path
from typing import Any

from loanpilot import config
from loanpilot.data.queries import create_intake_application
from loanpilot.data.store import SQLiteStore


def load_custom_cases(path: Path | None = None) -> list[dict[str, Any]]:
    """Read permanent custom-case definitions from the project-root ledger."""
    source = path or config.CUSTOM_CASES_PATH
    if not source.is_file():
        return []
    loaded = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(loaded, list):
        raise ValueError(f"Custom case file must contain a JSON list: {source}")
    return loaded


def remove_custom_cases(path: Path | None = None) -> None:
    """Remove only the explicit permanent custom-case definitions file."""
    source = path or config.CUSTOM_CASES_PATH
    if source.is_file():
        source.unlink()


def seed_custom_cases(
    store: SQLiteStore,
    *,
    project_root: Path | None = None,
    path: Path | None = None,
) -> int:
    """Recreate each saved custom case with stable identifiers and synthetic PDFs."""
    from loanpilot.pages.new_application import (
        _document_texts,
        _pdf_bytes,
        estimate_bureau_score,
    )

    root = project_root or config.PROJECT_ROOT
    cases = load_custom_cases(path)
    for row in cases:
        application_id = str(row["application_id"])
        number = int(application_id.rsplit("-", 1)[1])
        data = dict(row["inputs"])
        data["document_mode"] = "Use synthetic demo documents"
        data.setdefault("document_problem", False)
        data.setdefault("problem_type", "Salary credits about 30% below the payslip")
        dob = date.fromisoformat(str(data["dob"]))
        today = date(2026, 10, 28)
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        score = estimate_bureau_score(
            float(data["income"]),
            float(data["existing_emi"]),
            int(data["job_months"]),
            int(data["experience_months"]),
            str(data["pan"]),
        )
        generated = _document_texts(data)
        folder = root / "data" / "documents" / application_id
        folder.mkdir(parents=True, exist_ok=True)
        documents = []
        for doc_type, text in generated.items():
            filename = f"{doc_type}.pdf"
            target = folder / filename
            target.write_bytes(_pdf_bytes(doc_type, text.splitlines()))
            documents.append(
                {
                    "doc_type": doc_type,
                    "file_name": filename,
                    "file_path": target.relative_to(root).as_posix(),
                    "text_content": text,
                }
            )
        existing_customer = data.get("customer_type") == "Existing customer"
        applicant = {
            "name": data["name"],
            "dob": dob.isoformat(),
            "age": age,
            "city": data["city"],
            "mobile": data["mobile"],
            "employer": data["employer"],
            "employment_type": data["employment_type"],
            "current_tenure_months": int(data["job_months"]),
            "total_experience_months": int(data["experience_months"]),
            "net_monthly_income": float(data["income"]),
            "existing_emi": float(data["existing_emi"]),
            "pan_demo_id": data["pan"],
            "existing_customer": existing_customer,
        }
        application = {
            "requested_amount": float(data["amount"]),
            "tenure_months": int(data["tenure"]),
            "purpose": data["purpose"],
            "submitted_at": "2026-10-28T12:00:00",
        }
        bureau = {
            "provider": "Synthetic bureau simulator",
            "score": score,
            "thin_file": int(data["experience_months"]) < 12,
            "active_accounts": 0,
            "enquiries_6m": 0 if int(data["experience_months"]) < 12 else 1,
            "max_dpd_24m": 0,
            "written_off": False,
            "utilization_pct": 0.0,
            "document_flags": [],
        }
        kyc = dict(
            data.get("kyc")
            or {
                "status": "pending",
                "pan_status": "pending",
                "name_match": 0.0,
                "name_match_score": 0.0,
                "method": "Not completed",
                "provider": "Simulated identity check",
            }
        )
        kyc.setdefault("pan_demo_id", data["pan"])
        kyc.setdefault("cersai", "not applicable (unsecured)")
        if not existing_customer and kyc.get("method") == "Demo identity":
            identity_text = "\n".join(
                (
                    "SYNTHETIC IDENTITY SHEET",
                    f"Name: {data['name']}",
                    f"PAN demo identifier: {data['pan']}",
                    "Registry result: verified (simulated)",
                    "SYNTHETIC SAMPLE, DEMO ONLY",
                )
            )
            identity_folder = root / "data" / "uploads" / application_id / "kyc"
            identity_folder.mkdir(parents=True, exist_ok=True)
            identity_path = identity_folder / "identity_sheet.pdf"
            identity_path.write_bytes(_pdf_bytes("Synthetic identity sheet", identity_text.splitlines()))
            documents.append(
                {
                    "doc_type": "identity_sheet",
                    "file_name": identity_path.name,
                    "file_path": identity_path.relative_to(root).as_posix(),
                    "text_content": identity_text,
                }
            )
        create_intake_application(
            applicant,
            application,
            bureau,
            kyc,
            documents,
            store,
            application_id=application_id,
            customer_id=(
                str(data["customer_id"])
                if existing_customer
                else f"CUST-CUSTOM-{number}"
            ),
        )
    return len(cases)
