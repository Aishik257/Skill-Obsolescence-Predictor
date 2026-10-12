from datetime import date

from sqlalchemy import select

from app.models.job import JobPosting
from app.services.cleaning import run_cleaning
from app.services.ingestion import ingest_csv
from app.utils.geo import parse_location
from app.utils.roles import normalize_role
from app.utils.text import clean_text, normalize_company, normalize_title
from tests.factories import row, to_csv


def test_clean_text_removes_html_entities_and_normalizes_unicode():
    raw = "<p>Experience&nbsp;with <b>Python</b></p><script>alert(1)</script><ul><li>SQL • Docker</li></ul>“quoted”​"
    out = clean_text(raw)
    assert "<" not in out and "alert" not in out and "&nbsp;" not in out
    assert "Python" in out and '"quoted"' in out and "​" not in out and "  " not in out


def test_title_company_normalization():
    assert normalize_title("Senior Python Developer (II)") == normalize_title("python developer")
    assert normalize_company("Acme Inc.") == normalize_company("ACME, LLC") == "acme"


def test_role_and_location_parsing():
    assert normalize_role("Senior Machine Learning Engineer") == "ML Engineer"
    assert normalize_role("Front-End Developer") == "Frontend Developer"
    assert normalize_role("Site Reliability Engineer") == "DevOps Engineer"
    assert normalize_role("Sales Manager") == "Other"
    p = parse_location("Bengaluru, India")
    assert (p.country, p.region) == ("India", "Asia-Pacific")
    assert parse_location("Austin, TX").country == "United States"
    assert parse_location("Remote - Germany").country == "Germany"
    assert parse_location("Somewhere unknown").country is None
    assert parse_location(None).region is None


def test_cleaning_derives_date_parts_and_flags_near_duplicate(db):
    desc = "We need a developer. Experience with Python, Docker and Kubernetes in production systems. " * 3
    rows = [row(job_id="1", description=desc, posted_date="2024-02-10"),
            row(job_id="2", description=desc + " Apply today!", posted_date="2024-03-01"),  # repost
            row(job_id="3", description="Completely different text about data analysis, SQL, Tableau and reporting duties.",
                posted_date="2024-02-12")]
    ingest_csv(db, to_csv(rows), "t.csv")
    result = run_cleaning(db)
    assert result["cleaned"] == 3 and result["duplicates_found"] == 1
    jobs = {j.source_job_id: j for j in db.scalars(select(JobPosting))}
    assert jobs["1"].is_duplicate is False and jobs["2"].is_duplicate is True and jobs["3"].is_duplicate is False
    assert jobs["2"].duplicate_of_id == jobs["1"].id
    assert (jobs["1"].year, jobs["1"].quarter, jobs["1"].month) == (2024, 1, 2)
    assert jobs["1"].posted_date == date(2024, 2, 10) and jobs["1"].country == "United States"


def test_reposts_far_apart_are_not_duplicates(db):
    desc = "Experience with Python and Docker for backend services. " * 4
    ingest_csv(db, to_csv([row(job_id="1", description=desc, posted_date="2022-01-10"),
                           row(job_id="2", description=desc, posted_date="2024-01-10")]), "t.csv")
    assert run_cleaning(db)["duplicates_found"] == 0
