"""Grounded extraction and consistency checks for intake PDF evidence."""

from __future__ import annotations

from difflib import SequenceMatcher
from datetime import date, datetime
import hashlib
from io import BytesIO
import json
import logging
import re
from typing import Any, Mapping

from loanpilot.agent.llm import generate_json_with_gemini

LOGGER = logging.getLogger(__name__)
MAX_PDF_BYTES = 10 * 1024 * 1024
SALARY_TOLERANCE = 0.10

CATEGORIES = {
    "Identity proof": "identity_proof",
    "Salary slip": "salary_slip",
    "Bank statement": "bank_statement",
    "Employment proof": "employment_proof",
    "Other supporting document": "supporting_other",
}
REQUIRED_CATEGORIES = ("identity_proof", "payslip", "bank_statement_summary")
SALARY_BANK_CATEGORIES = ("salary_slip", "bank_statement")
_CATEGORY_LABELS = {value: key for key, value in CATEGORIES.items()}
_CATEGORY_LABELS.update(
    {
        "payslip": "Salary slip",
        "bank_statement_summary": "Bank statement",
    }
)
_SUPPORTED_CATEGORIES = {*CATEGORIES.values(), "payslip", "bank_statement_summary"}


def _ocr_pdf(content: bytes) -> tuple[str, str | None]:
    """Use optional local OCR libraries when both are installed and usable."""
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
    except ImportError:
        return "", "OCR is unavailable; install pdf2image, pytesseract, and Tesseract to read scanned PDFs."
    try:
        pages = convert_from_bytes(content, timeout=20)
        text = "\n".join(pytesseract.image_to_string(page) for page in pages).strip()
    except Exception as error:
        LOGGER.info("Local OCR could not read an uploaded PDF (%s).", type(error).__name__)
        return "", "OCR could not read this scanned PDF."
    return (text, None) if text else ("", "OCR found no readable text.")


def extract_pdf_text(content: bytes) -> tuple[str, str, str]:
    """Return extracted text, extraction status, and a user-safe explanation."""
    if not content:
        return "", "Unreadable", "The PDF is empty."
    if len(content) > MAX_PDF_BYTES:
        return "", "Unsupported", "The PDF exceeds the 10 MB upload limit."
    if b"%PDF-" not in content[:1024]:
        return "", "Unsupported", "The file is not a valid PDF."

    text = ""
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(bytes(content)))
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as error:
        LOGGER.info("PDF text extraction failed (%s); trying OCR.", type(error).__name__)

    if text:
        return text, "Readable", "Text extracted from the PDF."
    ocr_text, ocr_error = _ocr_pdf(content)
    if ocr_text:
        return ocr_text, "Readable (OCR)", "Text extracted with local OCR."
    if ocr_error and ocr_error.startswith("OCR is unavailable"):
        return "", "Unreadable", "The PDF has no extractable text. " + ocr_error
    return "", "Unreadable", ocr_error or "No text could be extracted."


def _prompt_fields(
    category: str, text: str
) -> tuple[dict[str, Any], str, str]:
    """Ask Gemini for only explicitly visible values; fall back to local labels."""
    label = _CATEGORY_LABELS[category]
    prompt = (
        "Extract facts explicitly stated in this uploaded document. Return one JSON "
        "object with only the applicable fields from this schema. Use null for "
        "absent values; never infer or repair information. Include a short "
        "grounded explanation of the extracted content, and do not assess "
        "consistency or authenticity. "
        f"Category: {label}. Schema: employee_name, account_holder_name, name, "
        "employer_name, bank_name, salary_month, statement_period, gross_salary, "
        "net_salary, deductions, employee_id, date_of_birth, masked_identifier, "
        "document_type, joining_date, employment_status, "
        "average_monthly_salary_credits, salary_credit_transactions "
        "(list of explicitly stated date and amount pairs), explanation. "
        f"Document text:\n{text[:30000]}"
    )
    try:
        result = generate_json_with_gemini(prompt)
        if not isinstance(result, dict):
            raise ValueError("Gemini did not return a JSON object.")
        explanation = result.pop("explanation", "")
        grounded = _ground_fields(result, text)
        for field in (
            "gross_salary",
            "net_salary",
            "deductions",
            "average_monthly_salary_credits",
        ):
            value = grounded.get(field)
            if isinstance(value, str):
                amount = re.fullmatch(
                    r"\s*(?:(?:INR|Rs\.?|₹)\s*)?([\d,]+(?:\.\d{1,2})?)\s*",
                    value,
                    re.IGNORECASE,
                )
                grounded[field] = (
                    float(amount.group(1).replace(",", "")) if amount else None
                )
        transactions = grounded.get("salary_credit_transactions")
        if isinstance(transactions, list):
            for transaction in transactions:
                if not isinstance(transaction, dict):
                    continue
                amount = transaction.get("amount")
                if isinstance(amount, str):
                    match = re.fullmatch(
                        r"\s*(?:(?:INR|Rs\.?|₹)\s*)?([\d,]+(?:\.\d{1,2})?)\s*",
                        amount,
                        re.IGNORECASE,
                    )
                    transaction["amount"] = (
                        float(match.group(1).replace(",", "")) if match else None
                    )
        for key, value in _local_fields(category, text).items():
            if grounded.get(key) is None:
                grounded[key] = value
        return (
            grounded,
            "Gemini",
            explanation.strip()[:500] if isinstance(explanation, str) else "",
        )
    except Exception as error:
        LOGGER.info(
            "Gemini document extraction unavailable (%s); using labelled local extraction.",
            type(error).__name__,
        )
        return _local_fields(category, text), "Local labelled extraction", ""


def _ground_fields(fields: dict[str, Any], text: str) -> dict[str, Any]:
    """Discard any model value that cannot be found in the extracted source text."""
    normalized_text = re.sub(r"[^\w]", "", text.casefold())

    def supported(value: Any) -> bool:
        if isinstance(value, dict):
            return bool(value) and all(supported(item) for item in value.values())
        if isinstance(value, list):
            return all(supported(item) for item in value)
        if isinstance(value, (int, float)):
            digits = re.sub(r"\D", "", str(value))
            return bool(digits) and digits in normalized_text
        if isinstance(value, str):
            normalized_value = re.sub(r"[^\w]", "", value.casefold())
            return bool(normalized_value) and normalized_value in normalized_text
        return value is None

    grounded = {
        key: value
        for key, value in fields.items()
        if value is None or supported(value)
    }
    identifier = grounded.get("masked_identifier")
    if isinstance(identifier, str):
        identifier_chars = re.sub(r"\W", "", identifier)
        if identifier_chars and not any(marker in identifier for marker in ("*", "•", "X", "x")):
            grounded["masked_identifier"] = f"••••{identifier_chars[-4:]}"
    return grounded


def _money(text: str, *labels: str) -> float | None:
    labels_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:{labels_pattern})\s*[:\-]?\s*(?:INR|Rs\.?|₹)?\s*([\d,]+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    return float(match.group(1).replace(",", "")) if match else None


def _line_value(text: str, *labels: str) -> str | None:
    labels_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:{labels_pattern})\s*[:\-]\s*([^\r\n]+)",
        text,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def _local_fields(category: str, text: str) -> dict[str, Any]:
    """Extract only values found on labelled lines when Gemini is unavailable."""
    fields: dict[str, Any] = {}
    if category in {"payslip", "salary_slip"}:
        fields = {
            "employee_name": _line_value(text, "Employee", "Employee name", "Applicant", "Name"),
            "employer_name": _line_value(text, "Employer on payslip", "Employer", "Company"),
            "salary_month": _line_value(text, "Pay month", "Salary month", "Month"),
            "gross_salary": _money(text, "Gross pay", "Gross salary"),
            "net_salary": _money(text, "Net pay", "Net salary"),
            "deductions": _money(text, "Deductions", "Total deductions"),
            "employee_id": _line_value(text, "Employee ID", "Employee number"),
        }
    elif category in {"bank_statement_summary", "bank_statement"}:
        credits = []
        monthly_credits: dict[tuple[int, int], float] = {}
        for line in text.splitlines():
            transaction = _salary_credit_from_line(line)
            if transaction:
                credits.append(transaction)
                credit_month = _parse_month(str(transaction.get("date") or ""))
                if credit_month:
                    monthly_credits[credit_month] = (
                        monthly_credits.get(credit_month, 0.0)
                        + float(transaction["amount"])
                    )
        average_salary_credits = _money(
            text, "Average monthly salary credits", "Average salary credits"
        )
        if average_salary_credits is None and monthly_credits:
            average_salary_credits = sum(monthly_credits.values()) / len(monthly_credits)
        fields = {
            "account_holder_name": _line_value(
                text, "Account holder", "Account name", "Applicant", "Name"
            ),
            "bank_name": _line_value(text, "Bank name", "Bank"),
            "statement_period": _line_value(text, "Period", "Statement period"),
            "salary_credit_transactions": credits,
            "average_monthly_salary_credits": average_salary_credits,
        }
    elif category == "identity_proof":
        raw_id = _line_value(text, "PAN demo identifier", "Identifier", "ID number")
        masked = None
        if raw_id:
            digits = re.sub(r"\W", "", raw_id)
            masked = f"••••{digits[-4:]}" if len(digits) >= 4 else None
        fields = {
            "document_type": _line_value(text, "Document type") or "Identity proof",
            "name": _line_value(text, "Holder name", "Applicant", "Name"),
            "date_of_birth": _line_value(text, "Date of birth", "DOB"),
            "masked_identifier": masked,
        }
    elif category == "employment_proof":
        fields = {
            "employee_name": _line_value(text, "Employee", "Employee name", "Applicant", "Name"),
            "employer_name": _line_value(text, "Employer", "Company"),
            "joining_date": _line_value(text, "Joining date", "Date of joining"),
            "employment_status": _line_value(text, "Employment status", "Status"),
        }
    else:
        fields = {"description": text[:240].strip() or None}
    return {key: value for key, value in fields.items() if value is not None}


def _salary_credit_from_line(line: str) -> dict[str, Any] | None:
    """Recognize credits only when transaction text explicitly indicates payroll."""
    lowered = line.casefold()
    if re.search(r"\baverage\b", lowered):
        return None
    if not re.search(r"\b(salary|payroll|wages?)\b", lowered):
        return None
    if re.search(r"\b(debit|withdrawal|reversal|reversed|returned|return)\b", lowered):
        return None
    labelled_amount = _money(line, "salary credit", "salary credits")
    if labelled_amount is None:
        credit_marker = re.search(r"\b(?:cr|credit)\b", line, re.IGNORECASE)
        if not credit_marker:
            return None
        date_match = re.search(
            r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b|\b\d{4}-\d{1,2}(?:-\d{1,2})?\b|"
            r"\b\d{1,2}[-/](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
            r"[-/]\d{2,4}\b",
            line,
            re.IGNORECASE,
        )
        without_date = (
            line[: date_match.start()] + (" " * (date_match.end() - date_match.start()))
            + line[date_match.end()]
            if date_match
            else line
        )
        amount_matches = list(
            re.finditer(
                r"(?:INR|Rs\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)",
                without_date,
                re.IGNORECASE,
            )
        )
        if not amount_matches:
            return None
        preceding = [
            match
            for match in amount_matches
            if match.end() <= credit_marker.start()
        ]
        selected = preceding[-1] if preceding else next(
            (match for match in amount_matches if match.start() >= credit_marker.end()),
            None,
        )
        if selected is None:
            return None
        try:
            labelled_amount = float(selected.group(1).replace(",", ""))
        except ValueError:
            return None
    if labelled_amount <= 0:
        return None
    date_match = re.search(
        r"\b(\d{4}-\d{1,2}(?:-\d{1,2})?|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|"
        r"\d{1,2}[-/](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"[-/]\d{2,4})\b",
        line,
        re.IGNORECASE,
    )
    return {
        "date": date_match.group(1) if date_match else "",
        "description": line.strip()[:160],
        "amount": labelled_amount,
    }


def _normalize(value: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", value.casefold()).split())


def _compare_names(document_value: Any, declared_value: Any) -> str:
    if not document_value or not declared_value:
        return "Missing information"
    ratio = SequenceMatcher(
        None, _normalize(str(document_value)), _normalize(str(declared_value))
    ).ratio()
    return "Match" if ratio >= 0.92 else "Minor difference" if ratio >= 0.78 else "Mismatch"


def _check(
    label: str,
    status: str,
    *,
    document_value: Any = None,
    declared_value: Any = None,
    evidence: str = "",
    explanation: str = "",
) -> dict[str, Any]:
    return {
        "check": label,
        "status": status,
        "document_value": document_value,
        "declared_value": declared_value,
        "evidence": evidence,
        "explanation": explanation,
    }


def _field_evidence(text: str, value: Any) -> str:
    if value is None:
        return ""
    needle = re.sub(r"[^\w]", "", str(value).casefold())
    for line in text.splitlines():
        normalized_line = re.sub(r"[^\w]", "", line.casefold())
        if needle and needle in normalized_line:
            return line.strip()[:240]
    return ""


def _parse_month(value: str) -> tuple[int, int] | None:
    """Parse common month/date formats without guessing a missing year."""
    for pattern in (
        "%Y-%m-%d",
        "%Y-%m",
        "%B %Y",
        "%b %Y",
        "%m/%Y",
        "%m-%Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d/%m/%y",
        "%d-%m-%y",
        "%d-%b-%Y",
        "%d-%B-%Y",
        "%d/%b/%Y",
        "%d/%B/%Y",
    ):
        try:
            parsed = datetime.strptime(value.strip(), pattern)
            return parsed.year, parsed.month
        except ValueError:
            continue
    return None


def _period_months(period: str) -> list[tuple[int, int]]:
    month_names = (
        "January|February|March|April|May|June|July|August|September|"
        "October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|"
        "Oct|Nov|Dec"
    )
    matches = re.findall(
        rf"({month_names})\s+(\d{{4}})|(\d{{4}})[-/](\d{{1,2}})",
        period,
        re.IGNORECASE,
    )
    parsed = []
    for month_name, year_name, year_numeric, month_numeric in matches:
        try:
            value = (
                datetime.strptime(f"{month_name} {year_name}", "%B %Y")
                if month_name
                else datetime(int(year_numeric), int(month_numeric), 1)
            )
        except ValueError:
            try:
                value = datetime.strptime(f"{month_name} {year_name}", "%b %Y")
            except ValueError:
                continue
        parsed.append((value.year, value.month))
    if not parsed:
        return []
    start = min(parsed)
    end = max(parsed)
    current = start[0] * 12 + start[1] - 1
    finish = end[0] * 12 + end[1] - 1
    return [(month // 12, month % 12 + 1) for month in range(current, finish + 1)]


def _transaction_months(transactions: Any) -> set[tuple[int, int]]:
    found = set()
    if not isinstance(transactions, list):
        return found
    for transaction in transactions:
        if not isinstance(transaction, dict):
            continue
        raw_date = str(transaction.get("date") or "").strip()
        month = _parse_month(raw_date)
        if month:
            found.add(month)
        else:
            matched = re.search(r"\b(\d{4})-(\d{1,2})\b", raw_date)
            if matched and 1 <= int(matched.group(2)) <= 12:
                found.add((int(matched.group(1)), int(matched.group(2))))
    return found


def analyze_uploads(
    uploads: list[Mapping[str, Any]],
    applicant: Mapping[str, Any],
    *,
    required_categories: tuple[str, ...] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Extract, compare, and summarize uploaded files without asserting authenticity."""
    documents: list[dict[str, Any]] = []
    seen_hashes: dict[str, str] = {}
    for index, upload in enumerate(uploads):
        filename = str(upload.get("file_name", "document.pdf"))
        content = bytes(upload.get("content") or b"")
        category = str(upload.get("category") or "")
        if category not in _SUPPORTED_CATEGORIES:
            raise ValueError(f"Choose a supported category for {filename}.")
        if not filename.casefold().endswith(".pdf"):
            raise ValueError(f"{filename}: only PDF documents are supported.")
        stored_text = str(upload.get("text_content") or "").strip()
        if not content and stored_text:
            text = stored_text
            extraction_status = "Readable (stored text)"
            extraction_message = "Using previously stored extracted text."
        else:
            text, extraction_status, extraction_message = extract_pdf_text(content)
            if extraction_status == "Unsupported" and "10 MB" in extraction_message:
                raise ValueError(f"{filename}: {extraction_message}")
            if extraction_status == "Unsupported":
                extraction_status = "Unreadable"
        digest = hashlib.sha256(content or text.encode("utf-8")).hexdigest()
        duplicate_of = seen_hashes.get(digest)
        seen_hashes.setdefault(digest, filename)
        fields, extraction_method, ai_explanation = (
            _prompt_fields(category, text)
            if text
            else ({}, "Unavailable", "")
        )
        evidence = {
            key: _field_evidence(text, value)
            for key, value in fields.items()
            if value is not None
        }
        if (
            category in {"bank_statement_summary", "bank_statement"}
            and fields.get("average_monthly_salary_credits") is not None
            and not evidence.get("average_monthly_salary_credits")
            and fields.get("salary_credit_transactions")
        ):
            evidence["average_monthly_salary_credits"] = (
                "Calculated from extracted salary credit lines: "
                + "; ".join(
                    f"{item['date']} Rs {item['amount']:,.2f}"
                    for item in fields["salary_credit_transactions"]
                )
            )
        documents.append(
            {
                "doc_id": upload.get("doc_id"),
                "doc_type": category,
                "category": category,
                "file_name": filename,
                "file_path": "",
                "text_content": text,
                "content": content,
                "extraction_status": extraction_status,
                "extraction_message": extraction_message,
                "extraction_method": extraction_method,
                "extracted_fields": fields,
                "field_evidence": evidence,
                "checks": [],
                "verification_status": "Unable to verify" if not text else "Needs manual review",
                "ai_explanation": ai_explanation,
                "explanation": extraction_message,
                "authenticity_status": "Not independently verified",
                "duplicate_of": duplicate_of if duplicate_of and index else None,
                "content_hash": digest,
            }
        )

    name_values: list[tuple[str, str]] = []
    employer_values: list[tuple[str, str]] = []
    for document in documents:
        fields = document["extracted_fields"]
        name = (
            fields.get("employee_name")
            or fields.get("account_holder_name")
            or fields.get("name")
        )
        if name:
            name_values.append((str(name), document["file_name"]))
        employer = fields.get("employer_name")
        if employer:
            employer_values.append((str(employer), document["file_name"]))

    declared_name = str(applicant.get("name") or "")
    declared_employer = str(applicant.get("employer") or "")
    salary_values: list[tuple[float, str]] = []
    statement_values: list[tuple[float, str]] = []
    for document in documents:
        fields = document["extracted_fields"]
        checks: list[dict[str, Any]] = []
        if document["extraction_status"].startswith("Readable"):
            name = (
                fields.get("employee_name")
                or fields.get("account_holder_name")
                or fields.get("name")
            )
            if name:
                checks.append(
                    _check(
                        "Applicant name",
                        _compare_names(name, declared_name),
                        document_value=name,
                        declared_value=declared_name,
                        evidence=document["field_evidence"].get(
                            "employee_name",
                            document["field_evidence"].get(
                                "account_holder_name", document["field_evidence"].get("name", "")
                            ),
                        ),
                        explanation="Compared the extracted name with the application entry.",
                    )
                )
            employer = fields.get("employer_name")
            if employer and declared_employer:
                checks.append(
                    _check(
                        "Employer name",
                        _compare_names(employer, declared_employer),
                        document_value=employer,
                        declared_value=declared_employer,
                        evidence=document["field_evidence"].get("employer_name", ""),
                        explanation="Compared the extracted employer with the application entry.",
                    )
                )
            if document["category"] in {"payslip", "salary_slip"}:
                net = fields.get("net_salary")
                if isinstance(net, (int, float)):
                    salary_values.append((float(net), document["file_name"]))
                    declared_income = applicant.get("income")
                    variance = (
                        abs(float(net) - float(declared_income)) / float(declared_income)
                        if declared_income
                        else None
                    )
                    status = (
                        "Missing information"
                        if variance is None
                        else "Match"
                        if variance <= SALARY_TOLERANCE
                        else "Mismatch"
                    )
                    checks.append(
                        _check(
                            "Net salary vs declared income",
                            status,
                            document_value=net,
                            declared_value=declared_income,
                            evidence=document["field_evidence"].get("net_salary", ""),
                            explanation=(
                                f"Compared using a {SALARY_TOLERANCE:.0%} tolerance."
                            ),
                        )
                    )
            if document["category"] in {"bank_statement_summary", "bank_statement"}:
                average = fields.get("average_monthly_salary_credits")
                if isinstance(average, (int, float)):
                    statement_values.append((float(average), document["file_name"]))
                period = fields.get("statement_period")
                period_month_list = (
                    _period_months(str(period)) if isinstance(period, str) else []
                )
                transaction_month_list = _transaction_months(
                    fields.get("salary_credit_transactions")
                )
                if period_month_list and transaction_month_list:
                    missing_months = sorted(
                        set(period_month_list) - transaction_month_list
                    )
                    checks.append(
                        _check(
                            "Salary credit months in statement period",
                            "Match" if not missing_months else "Missing information",
                            document_value=len(transaction_month_list),
                            declared_value=len(period_month_list),
                            evidence=str(period),
                            explanation=(
                                "All months in the stated period have salary credits."
                                if not missing_months
                                else f"Salary credit evidence is missing for {len(missing_months)} period month(s)."
                            ),
                        )
                    )
            if document["category"] == "employment_proof":
                joining_date = fields.get("joining_date")
                if isinstance(joining_date, str):
                    joining_month = _parse_month(joining_date)
                    declared_months = applicant.get("job_months")
                    if joining_month and isinstance(declared_months, (int, float)):
                        current = date.today()
                        evidenced_months = (
                            (current.year - joining_month[0]) * 12
                            + current.month
                            - joining_month[1]
                        )
                        difference = abs(evidenced_months - int(declared_months))
                        checks.append(
                            _check(
                                "Employment duration",
                                "Match" if difference <= 2 else "Minor difference" if difference <= 4 else "Mismatch",
                                document_value=evidenced_months,
                                declared_value=int(declared_months),
                                evidence=document["field_evidence"].get("joining_date", ""),
                                explanation="Compared the joining date with months in the current job.",
                            )
                        )
        if document.get("duplicate_of"):
            checks.append(
                _check(
                    "Duplicate document",
                    "Needs manual review",
                    document_value=document["duplicate_of"],
                    explanation="This file has the same content as an earlier upload.",
                )
            )
        document["checks"] = checks

    cross_checks: list[dict[str, Any]] = []
    if len(name_values) > 1:
        distinct_names = {_normalize(value) for value, _ in name_values}
        cross_checks.append(
            _check(
                "Names across documents",
                "Match" if len(distinct_names) == 1 else "Mismatch",
                document_value=", ".join(value for value, _ in name_values),
                explanation="Compared names extracted from uploaded documents.",
            )
        )
    if len(employer_values) > 1:
        distinct_employers = {_normalize(value) for value, _ in employer_values}
        cross_checks.append(
            _check(
                "Employers across documents",
                "Match" if len(distinct_employers) == 1 else "Mismatch",
                document_value=", ".join(value for value, _ in employer_values),
                explanation="Compared employer names extracted from uploaded documents.",
            )
        )
    if salary_values and statement_values:
        payslip_net, payslip_file = salary_values[0]
        statement_average, statement_file = statement_values[0]
        variance = abs(payslip_net - statement_average) / payslip_net if payslip_net else None
        cross_checks.append(
            _check(
                "Payslip vs salary credits",
                "Missing information"
                if variance is None
                else "Match"
                if variance <= SALARY_TOLERANCE
                else "Mismatch",
                document_value=statement_average,
                declared_value=payslip_net,
                evidence=f"{payslip_file} and {statement_file}",
                explanation=f"Compared values using a {SALARY_TOLERANCE:.0%} tolerance.",
            )
        )

    categories = {document["category"] for document in documents}
    required = required_categories or REQUIRED_CATEGORIES
    missing = [category for category in required if category not in categories]
    for category in missing:
        cross_checks.append(
            _check(
                f"Required {_CATEGORY_LABELS[category]}",
                "Missing information",
                explanation="No document was uploaded for this required category.",
            )
        )
    statuses = [
        check["status"]
        for document in documents
        for check in document["checks"]
    ] + [check["status"] for check in cross_checks]
    has_unreadable = any(
        not document["extraction_status"].startswith("Readable")
        for document in documents
    )
    if has_unreadable or "Mismatch" in statuses or "Needs manual review" in statuses:
        overall_status = "Needs manual review"
    elif missing:
        overall_status = "Incomplete"
    elif "Minor difference" in statuses or "Missing information" in statuses:
        overall_status = "Partially verified"
    else:
        overall_status = "Verified / Consistent"

    explanations = []
    if missing:
        explanations.append(
            "Missing required documents: "
            + ", ".join(_CATEGORY_LABELS[category] for category in missing)
            + "."
        )
    mismatch_count = statuses.count("Mismatch")
    if mismatch_count:
        explanations.append(
            f"{mismatch_count} consistency check(s) require human review."
        )
    if has_unreadable:
        explanations.append("One or more PDFs could not be read.")
    if not explanations:
        explanations.append(
            "Available documents were compared with the details provided; issuer authenticity was not checked."
        )
    report = {
        "overall_status": overall_status,
        "checks": cross_checks,
        "missing_categories": missing,
        "explanation": " ".join(explanations),
        "authenticity_status": "Not independently verified",
        "analysis_method": "Gemini when configured; otherwise labelled local extraction and deterministic comparisons.",
        "salary_tolerance": SALARY_TOLERANCE,
    }
    salary_bank_verification = _salary_bank_verification(
        documents, applicant, required_categories=required_categories
    )
    if salary_bank_verification is not None:
        report["salary_statement_verification"] = salary_bank_verification
        report["explanation"] = salary_bank_verification["explanation"]
        if salary_bank_verification["status"] == "MATCH":
            report["overall_status"] = "Verified / Consistent"
        elif salary_bank_verification["status"] == "MISMATCH":
            report["overall_status"] = "Needs manual review"
        else:
            report["overall_status"] = (
                "Incomplete"
                if missing
                and not any(
                    not document["extraction_status"].startswith("Readable")
                    for document in documents
                )
                else "Needs manual review"
            )
    for document in documents:
        document["verification_status"] = _document_status(document)
        document["explanation"] = _document_explanation(document)
        document["overall_status"] = report["overall_status"]
    return documents, report


def _salary_bank_verification(
    documents: list[dict[str, Any]],
    applicant: Mapping[str, Any],
    *,
    required_categories: tuple[str, ...] | None,
) -> dict[str, Any] | None:
    """Compare salary evidence, retaining source-linked transaction detail."""
    is_salary_bank_workflow = required_categories == SALARY_BANK_CATEGORIES or any(
        document["category"] in SALARY_BANK_CATEGORIES
        or document["category"] in {"payslip", "bank_statement_summary"}
        for document in documents
    )
    if not is_salary_bank_workflow:
        return None

    salary_slip = next(
        (
            document
            for document in documents
            if document["category"] in {"salary_slip", "payslip"}
        ),
        None,
    )
    bank_statement = next(
        (
            document
            for document in documents
            if document["category"] in {"bank_statement", "bank_statement_summary"}
        ),
        None,
    )
    salary_fields = (salary_slip or {}).get("extracted_fields", {})
    bank_fields = (bank_statement or {}).get("extracted_fields", {})
    salary_name = salary_fields.get("employee_name") or salary_fields.get("name")
    bank_name = (
        bank_fields.get("account_holder_name")
        or bank_fields.get("employee_name")
        or bank_fields.get("name")
    )
    net_salary = salary_fields.get("net_salary")
    raw_credits = bank_fields.get("salary_credit_transactions")
    usable_credits = [
        {
            "date": str(item.get("date") or ""),
            "description": str(item.get("description") or ""),
            "amount": float(item["amount"]),
        }
        for item in (raw_credits if isinstance(raw_credits, list) else [])
        if isinstance(item, dict)
        and isinstance(item.get("amount"), (int, float))
        and float(item["amount"]) > 0
    ]

    monthly_totals: dict[tuple[int, int], float] = {}
    for credit in usable_credits:
        month = _parse_month(credit["date"])
        if month:
            monthly_totals[month] = (
                monthly_totals.get(month, 0.0) + credit["amount"]
            )
    monthly_credits = [
        {"month": f"{year:04d}-{month:02d}", "amount": amount}
        for (year, month), amount in sorted(monthly_totals.items())
    ]
    explicit_average = bank_fields.get("average_monthly_salary_credits")
    if isinstance(explicit_average, (int, float)):
        average_credit = float(explicit_average)
    elif monthly_credits:
        average_credit = sum(item["amount"] for item in monthly_credits) / len(
            monthly_credits
        )
    elif usable_credits:
        average_credit = sum(item["amount"] for item in usable_credits) / len(
            usable_credits
        )
    else:
        average_credit = None

    name_status = (
        "Match"
        if salary_name and bank_name and _normalize(str(salary_name)) == _normalize(str(bank_name))
        else "Mismatch"
        if salary_name and bank_name
        else "Missing information"
    )
    declared_name_status = (
        "Match"
        if salary_name
        and applicant.get("name")
        and _normalize(str(salary_name)) == _normalize(str(applicant.get("name")))
        else "Mismatch"
        if salary_name and applicant.get("name")
        else "Missing information"
    )
    difference = (
        abs(float(net_salary) - average_credit)
        if isinstance(net_salary, (int, float)) and average_credit is not None
        else None
    )
    variance = difference / float(net_salary) if difference is not None and net_salary else None
    if name_status in {"Mismatch", "Minor difference"} or declared_name_status in {
        "Mismatch",
        "Minor difference",
    }:
        status = "MISMATCH"
    elif variance is not None and variance > SALARY_TOLERANCE:
        status = "MISMATCH"
    elif (
        salary_slip is None
        or bank_statement is None
        or not salary_slip["extraction_status"].startswith("Readable")
        or not bank_statement["extraction_status"].startswith("Readable")
        or not salary_name
        or not bank_name
        or not isinstance(net_salary, (int, float))
        or average_credit is None
    ):
        status = "INCONCLUSIVE"
    else:
        status = "MATCH"

    if status == "MATCH":
        explanation = (
            "The applicant names are consistent and the salary slip net salary "
            "is within the configured tolerance of identified bank salary credits."
        )
    elif status == "MISMATCH":
        findings = []
        if name_status in {"Mismatch", "Minor difference"} or declared_name_status in {
            "Mismatch",
            "Minor difference",
        }:
            findings.append(
                "The applicant names differ across the submitted details and documents."
            )
        if variance is not None and variance > SALARY_TOLERANCE:
            findings.append(
                "The salary slip net salary materially differs from identified bank salary credits."
            )
        explanation = " ".join(findings)
    else:
        findings = []
        if salary_slip is None:
            findings.append("A salary slip was not provided.")
        elif not salary_slip["extraction_status"].startswith("Readable"):
            findings.append("The salary slip could not be read.")
        if bank_statement is None:
            findings.append("A bank statement was not provided.")
        elif not bank_statement["extraction_status"].startswith("Readable"):
            findings.append("The bank statement could not be read.")
        if salary_slip and bank_statement and average_credit is None:
            findings.append(
                "Salary credit transactions could not be confidently identified."
            )
        if not findings:
            findings.append("The available salary evidence is incomplete.")
        explanation = " ".join(findings)

    result = {
        "status": status,
        "salary_slip_net_salary": (
            float(net_salary) if isinstance(net_salary, (int, float)) else None
        ),
        "bank_statement_salary_credits": usable_credits,
        "bank_statement_monthly_salary_credits": monthly_credits,
        "bank_statement_average_monthly_salary_credit": average_credit,
        "difference": difference,
        "name_comparison": {
            "salary_slip_name": salary_name,
            "bank_statement_name": bank_name,
            "declared_applicant_name": applicant.get("name"),
            "status": (
                "Mismatch"
                if name_status in {"Mismatch", "Minor difference"}
                or declared_name_status in {"Mismatch", "Minor difference"}
                else "Match"
                if name_status == "Match" and declared_name_status == "Match"
                else "Missing information"
            ),
        },
        "tolerance": SALARY_TOLERANCE,
        "explanation": explanation,
    }
    try:
        generated = generate_json_with_gemini(
            "Rewrite the following finding in one concise sentence. Use only these "
            "facts, do not add evidence, and do not claim authenticity. Return a "
            "JSON object with an explanation string.\n"
            + json.dumps(result, ensure_ascii=False, sort_keys=True)
        )
        generated_explanation = generated.get("explanation")
        if isinstance(generated_explanation, str) and generated_explanation.strip():
            result["explanation"] = generated_explanation.strip()[:500]
            result["explanation_method"] = "Gemini"
    except Exception as error:
        LOGGER.info(
            "Gemini verification explanation unavailable (%s); using deterministic finding.",
            type(error).__name__,
        )
        result["explanation_method"] = "Grounded deterministic explanation"
    return result


def _document_status(document: Mapping[str, Any]) -> str:
    if not str(document["extraction_status"]).startswith("Readable"):
        return "Unable to verify"
    statuses = {check["status"] for check in document.get("checks", [])}
    if "Mismatch" in statuses or "Needs manual review" in statuses:
        return "Needs manual review"
    if "Minor difference" in statuses or "Missing information" in statuses:
        return "Partially verified"
    return "Verified / Consistent"


def _document_explanation(document: Mapping[str, Any]) -> str:
    if not str(document["extraction_status"]).startswith("Readable"):
        return str(document["extraction_message"])
    problems = [
        str(check["check"])
        for check in document.get("checks", [])
        if check["status"] not in {"Match", "Verified / Consistent"}
    ]
    comparison = (
        "Review: " + ", ".join(problems) + "."
        if problems
        else "Extracted fields were compared with available application details."
    )
    ai_explanation = str(document.get("ai_explanation") or "").strip()
    return (
        f"Gemini extraction explanation: {ai_explanation} {comparison}"
        if ai_explanation
        else comparison
    )


def synthetic_verification_report(documents: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Describe generated samples without presenting them as verified evidence."""
    return {
        "overall_status": "Synthetic demo documents",
        "checks": [],
        "missing_categories": [],
        "explanation": (
            f"{len(documents)} watermarked sample PDFs were generated from the "
            "applicant's entries. They are demonstration artifacts, not independent evidence."
        ),
        "authenticity_status": "Not independently verified",
        "analysis_method": "Synthetic document generation; no verification performed.",
        "salary_tolerance": SALARY_TOLERANCE,
    }


def decode_verification_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Decode JSON-backed verification columns returned from SQLite."""
    result = dict(row)
    for source, target in (
        ("extracted_fields_json", "extracted_fields"),
        ("field_evidence_json", "field_evidence"),
        ("checks_json", "checks"),
    ):
        try:
            result[target] = json.loads(result.pop(source) or "{}")
        except (json.JSONDecodeError, TypeError):
            result[target] = {}
    return result
