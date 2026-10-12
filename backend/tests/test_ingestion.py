import pytest
from sqlalchemy import func, select

from app.core.errors import BadRequestError
from app.models.job import JobPosting
from app.services.ingestion import ingest_csv, parse_date, validate_upload
from tests.factories import row, to_csv


def count(db):
    return db.scalar(select(func.count()).select_from(JobPosting))


def test_valid_csv_is_imported_with_report(db):
    csv_bytes = to_csv([row(job_id="A"), row(job_id="B", posted_date="2023-01-02"), row(job_id="C", posted_date="2025-12-31")])
    report = ingest_csv(db, csv_bytes, "ok.csv")
    assert (report.total_records, report.imported, report.invalid_records, report.duplicates_removed) == (3, 3, 0, 0)
    assert report.date_range == {"min": "2023-01-02", "max": "2025-12-31"}
    assert count(db) == 3


def test_dry_run_validates_without_inserting(db):
    report = ingest_csv(db, to_csv([row(job_id="A")]), "x.csv", dry_run=True)
    assert report.valid_records == 1 and report.imported == 0 and count(db) == 0


def test_missing_required_column_is_rejected(db):
    with pytest.raises(BadRequestError, match="missing required column"):
        ingest_csv(db, to_csv([row()], columns=["job_id", "title", "description"]), "bad.csv")


def test_duplicates_inside_file_and_existing_are_removed(db):
    ingest_csv(db, to_csv([row(job_id="X")]), "first.csv")
    report = ingest_csv(db, to_csv([row(job_id="X"), row(job_id="Y"), row(job_id="Y")]), "second.csv")
    assert report.duplicates_existing == 1 and report.duplicates_in_file == 1
    assert report.duplicates_removed == 2 and report.imported == 1 and count(db) == 2


def test_invalid_missing_dates_descriptions_and_fields(db):
    rows = [row(job_id="1", posted_date="not a date"), row(job_id="2", posted_date=""), row(job_id="3", posted_date="2027-13-45"),
            row(job_id="4", description=""), row(job_id="5", title=""), row(job_id="", title="T"),
            row(job_id="7", posted_date="2999-01-01"), row(job_id="8")]
    report = ingest_csv(db, to_csv(rows), "mixed.csv")
    assert report.total_records == 8 and report.imported == 1
    assert report.invalid_dates == 3 and report.missing_dates == 1
    assert report.missing_descriptions == 1 and report.missing_required_fields == 2
    assert report.invalid_records == 6  # missing descriptions are reported separately, not as invalid rows
    assert {e["reason"] for e in report.errors} >= {"invalid_date", "missing_date", "missing_required_field"}


def test_malformed_rows_are_reported():
    text = "job_id,title,description,posted_date\nA,T,D,2024-01-01\nB,T,D,2024-01-02,EXTRA\nC,T\n".encode()
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        report = ingest_csv(db, text, "m.csv", dry_run=True)
    assert report.malformed_records == 2 and report.valid_records == 1


@pytest.mark.parametrize("content,msg", [(b"", "empty"), (b"\x00\x01\x02binary", "binary"), (b"job_id,title,description,posted_date\n", "no data rows")])
def test_unreadable_files_raise_bad_request(db, content, msg):
    with pytest.raises(BadRequestError, match=msg):
        ingest_csv(db, content, "f.csv")


def test_upload_validation(monkeypatch):
    validate_upload("jobs.csv", "text/csv", 100)
    with pytest.raises(BadRequestError, match="Invalid file type"):
        validate_upload("jobs.exe", "text/csv", 100)
    with pytest.raises(BadRequestError, match="content type"):
        validate_upload("jobs.csv", "image/png", 100)
    with pytest.raises(BadRequestError) as exc:
        validate_upload("jobs.csv", "text/csv", 10**9)
    assert exc.value.status_code == 413


@pytest.mark.parametrize("raw,ok", [("2024-02-29", True), ("2024-02-30", False), ("03/04/2024", True), ("garbage", False), ("", False)])
def test_parse_date(raw, ok):
    assert (parse_date(raw)[0] is not None) is ok
