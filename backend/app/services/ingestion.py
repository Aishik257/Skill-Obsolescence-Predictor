"""CSV ingestion: validation, de-duplication by job id, and bulk insert.

A row falls into exactly one bucket, checked in this order:
malformed -> missing required field -> missing/invalid date -> missing description
-> duplicate job id (inside the file or already in the database) -> valid.

Rows without a description are reported but not imported: they cannot mention any skill
and would otherwise dilute every skill's share of postings.
"""
from __future__ import annotations

import csv
import io
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from dateutil import parser as date_parser
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import BadRequestError
from app.models.job import JobPosting
from app.utils.text import sanitize_cell

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ["job_id", "title", "description", "posted_date"]
OPTIONAL_COLUMNS = ["company", "location", "industry", "employment_type", "source"]
ALLOWED_CONTENT_TYPES = {
    "text/csv", "application/csv", "text/plain", "application/vnd.ms-excel", "application/octet-stream", "",
}
MIN_DATE = date(2000, 1, 1)
MAX_ERRORS_REPORTED = 50
INSERT_CHUNK = 1000


@dataclass
class IngestionReport:
    file_name: str
    dry_run: bool
    total_records: int = 0
    valid_records: int = 0
    imported: int = 0
    duplicates_removed: int = 0
    duplicates_in_file: int = 0
    duplicates_existing: int = 0
    invalid_records: int = 0
    missing_descriptions: int = 0
    missing_dates: int = 0
    invalid_dates: int = 0
    malformed_records: int = 0
    missing_required_fields: int = 0
    date_range: dict[str, str | None] = field(default_factory=lambda: {"min": None, "max": None})
    columns_detected: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def parse_date(raw: str | None) -> tuple[date | None, str | None]:
    """Parse a posting date. Returns (date, None) or (None, "missing_date" | "invalid_date")."""
    if raw is None or not raw.strip():
        return None, "missing_date"
    text = raw.strip()
    try:
        parsed = date.fromisoformat(text[:10]) if len(text) >= 10 and text[4] == "-" else None
        if parsed is None:
            parsed = date_parser.parse(text, dayfirst=False, fuzzy=False).date()
    except (ValueError, OverflowError, TypeError):
        return None, "invalid_date"
    if parsed < MIN_DATE or parsed > date.today() + timedelta(days=1):
        return None, "invalid_date"
    return parsed, None


def decode_csv_bytes(content: bytes) -> str:
    """Decode uploaded bytes, rejecting binary files."""
    if not content.strip():
        raise BadRequestError("Invalid CSV format: the file is empty.")
    if b"\x00" in content[:4096]:
        raise BadRequestError("Invalid CSV format: the file looks binary, not a text CSV.")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise BadRequestError("Invalid CSV format: the file is not valid UTF-8 text.")


def validate_upload(file_name: str, content_type: str | None, size: int) -> None:
    """File-level checks done before parsing (extension, MIME type, size)."""
    name = (file_name or "").lower()
    if not name.endswith(".csv"):
        raise BadRequestError("Invalid file type: please upload a .csv file.")
    if (content_type or "").split(";")[0].strip().lower() not in ALLOWED_CONTENT_TYPES:
        raise BadRequestError(f"Invalid file type: unsupported content type '{content_type}'.")
    if size > settings.max_upload_bytes:
        raise BadRequestError(f"File too large: the limit is {settings.MAX_UPLOAD_SIZE_MB} MB.", status_code=413)
    if size == 0:
        raise BadRequestError("Invalid CSV format: the file is empty.")


def _add_error(report: IngestionReport, row_number: int, reason: str, detail: str = "") -> None:
    report.invalid_records += 1
    if len(report.errors) < MAX_ERRORS_REPORTED:
        report.errors.append({"row": row_number, "reason": reason, "detail": detail})


def ingest_csv(db: Session, content: bytes, file_name: str, dry_run: bool = False) -> IngestionReport:
    """Validate (and unless ``dry_run`` import) a CSV of job postings."""
    text = decode_csv_bytes(content)
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        header = [h.strip().lower() for h in (reader.fieldnames or [])]
    except csv.Error as exc:
        raise BadRequestError(f"Invalid CSV format: {exc}") from exc
    if not header:
        raise BadRequestError("Invalid CSV format: no header row found.")
    reader.fieldnames = header
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing_cols:
        raise BadRequestError(
            f"Invalid CSV format: missing required column(s): {', '.join(missing_cols)}. "
            f"Expected columns: {', '.join(REQUIRED_COLUMNS + OPTIONAL_COLUMNS)}."
        )

    report = IngestionReport(file_name=file_name, dry_run=dry_run, columns_detected=header)
    absent_optional = [c for c in OPTIONAL_COLUMNS if c not in header]
    if absent_optional:
        report.warnings.append(
            f"Optional column(s) not found: {', '.join(absent_optional)}. Role/industry/location filters will be limited."
        )

    existing_ids: set[str] = set(db.scalars(select(JobPosting.source_job_id)))
    seen_in_file: set[str] = set()
    rows_to_insert: list[dict] = []
    dates: list[date] = []

    try:
        for row_number, row in enumerate(reader, start=2):
            report.total_records += 1
            if None in row:  # more fields than header columns
                report.malformed_records += 1
                _add_error(report, row_number, "malformed_row", "row has more fields than the header")
                continue
            if any(v is None for v in row.values()):  # fewer fields than header columns
                report.malformed_records += 1
                _add_error(report, row_number, "malformed_row", "row has fewer fields than the header")
                continue
            job_id = sanitize_cell(row.get("job_id"), 128)
            title = sanitize_cell(row.get("title"), 300)
            if not job_id or not title:
                report.missing_required_fields += 1
                _add_error(report, row_number, "missing_required_field", "job_id and title are required")
                continue
            posted, date_problem = parse_date(row.get("posted_date"))
            if date_problem:
                if date_problem == "missing_date":
                    report.missing_dates += 1
                else:
                    report.invalid_dates += 1
                _add_error(report, row_number, date_problem, str(row.get("posted_date")))
                continue
            description = sanitize_cell(row.get("description"), 100_000)
            if not description:
                report.missing_descriptions += 1
                continue
            if job_id in seen_in_file:
                report.duplicates_in_file += 1
                continue
            seen_in_file.add(job_id)
            if job_id in existing_ids:
                report.duplicates_existing += 1
                continue

            report.valid_records += 1
            dates.append(posted)
            rows_to_insert.append({
                "source_job_id": job_id,
                "title": title,
                "company": sanitize_cell(row.get("company"), 200),
                "location": sanitize_cell(row.get("location"), 200),
                "description": description,
                "employment_type": sanitize_cell(row.get("employment_type"), 50),
                "industry": sanitize_cell(row.get("industry"), 100),
                "posted_date": posted,
                "source": sanitize_cell(row.get("source"), 100) or "upload",
            })
    except csv.Error as exc:
        raise BadRequestError(f"Invalid CSV format near row {report.total_records + 2}: {exc}") from exc

    report.duplicates_removed = report.duplicates_in_file + report.duplicates_existing
    if report.total_records == 0:
        raise BadRequestError("Invalid CSV format: the file has a header but no data rows.")
    if dates:
        report.date_range = {"min": min(dates).isoformat(), "max": max(dates).isoformat()}

    if not dry_run and rows_to_insert:
        for i in range(0, len(rows_to_insert), INSERT_CHUNK):
            db.execute(insert(JobPosting), rows_to_insert[i:i + INSERT_CHUNK])
        db.commit()
        report.imported = len(rows_to_insert)
        logger.info("Imported %d postings from %s", report.imported, file_name)
    return report


def summarize_reasons(report: IngestionReport) -> dict[str, int]:
    """Counts of invalid rows by reason (handy for logs and tests)."""
    return dict(Counter(e["reason"] for e in report.errors))
