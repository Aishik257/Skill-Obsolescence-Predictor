"""Cleaning and de-duplication of imported job postings.

Cleaning is incremental: only rows whose ``cleaned_at`` is NULL are processed. Duplicate
detection compares each new posting with every posting that shares its normalized company
and normalized title, within a time window, using TF-IDF cosine similarity of the
descriptions. The earliest posting is kept; later near-copies are flagged ``is_duplicate``
and excluded from every analytic.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.job import JobPosting
from app.utils.geo import parse_location
from app.utils.roles import normalize_role
from app.utils.text import clean_text, normalize_company, normalize_title

logger = logging.getLogger(__name__)

DUPLICATE_SIMILARITY = 0.90
DUPLICATE_WINDOW_DAYS = 60
BATCH = 2000


@dataclass
class CleaningReport:
    cleaned: int = 0
    duplicates_found: int = 0
    empty_after_cleaning: int = 0
    unknown_role: int = 0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def derive_fields(job: JobPosting) -> dict:
    """Compute all cleaned/derived columns for one posting."""
    place = parse_location(job.location)
    d = job.posted_date
    return {
        "clean_description": clean_text(job.description),
        "normalized_title": normalize_title(job.title),
        "normalized_company": normalize_company(job.company),
        "role": normalize_role(job.title),
        "city": place.city,
        "country": place.country,
        "region": place.region,
        "year": d.year,
        "quarter": (d.month - 1) // 3 + 1,
        "month": d.month,
    }


def clean_pending_jobs(db: Session) -> tuple[CleaningReport, list[int]]:
    """Clean all uncleaned postings. Returns the report and the ids that were cleaned."""
    report = CleaningReport()
    cleaned_ids: list[int] = []
    now = datetime.now(timezone.utc)
    while True:
        batch = db.scalars(
            select(JobPosting).where(JobPosting.cleaned_at.is_(None)).order_by(JobPosting.id).limit(BATCH)
        ).all()
        if not batch:
            break
        mappings = []
        for job in batch:
            fields = derive_fields(job)
            if not fields["clean_description"]:
                report.empty_after_cleaning += 1
            if fields["role"] == "Other":
                report.unknown_role += 1
            mappings.append({"id": job.id, "cleaned_at": now, **fields})
            cleaned_ids.append(job.id)
        db.execute(update(JobPosting), mappings)
        db.commit()
        report.cleaned += len(batch)
    return report, cleaned_ids


def deduplicate(db: Session, new_job_ids: list[int]) -> int:
    """Flag near-duplicate postings among groups that contain at least one new job."""
    if not new_job_ids:
        return 0
    keys: set[tuple[str, str]] = set()
    for i in range(0, len(new_job_ids), 5000):
        rows = db.execute(
            select(JobPosting.normalized_company, JobPosting.normalized_title).where(
                JobPosting.id.in_(new_job_ids[i:i + 5000])
            )
        ).all()
        keys.update((c or "", t or "") for c, t in rows)

    groups: dict[tuple[str, str], list[tuple]] = defaultdict(list)
    all_jobs = db.execute(
        select(JobPosting.id, JobPosting.normalized_company, JobPosting.normalized_title, JobPosting.posted_date,
               JobPosting.clean_description, JobPosting.is_duplicate)
        .where(JobPosting.cleaned_at.is_not(None))
    ).all()
    for row in all_jobs:
        key = (row.normalized_company or "", row.normalized_title or "")
        if key in keys and row.normalized_title:
            groups[key].append(row)

    flagged: list[dict] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda r: (r.posted_date, r.id))
        docs = [m.clean_description or "" for m in members]
        try:
            matrix = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True).fit_transform(docs)
        except ValueError:  # empty vocabulary
            continue
        sims = (matrix @ matrix.T).toarray()
        kept: list[int] = []
        for idx, member in enumerate(members):
            original = None
            for k in kept:
                if (member.posted_date - members[k].posted_date).days > DUPLICATE_WINDOW_DAYS:
                    continue
                if sims[idx, k] >= DUPLICATE_SIMILARITY:
                    original = members[k].id
                    break
            if original is None:
                kept.append(idx)
                if member.is_duplicate:  # previously flagged but no longer matches (e.g. original deleted)
                    flagged.append({"id": member.id, "is_duplicate": False, "duplicate_of_id": None})
            elif not member.is_duplicate:
                flagged.append({"id": member.id, "is_duplicate": True, "duplicate_of_id": original})

    if flagged:
        db.execute(update(JobPosting), flagged)
        db.commit()
    n = sum(1 for f in flagged if f["is_duplicate"])
    logger.info("Duplicate detection flagged %d postings across %d groups", n, len(groups))
    return n


def run_cleaning(db: Session) -> dict:
    """Clean pending postings and de-duplicate them. Returns a summary dict."""
    report, ids = clean_pending_jobs(db)
    report.duplicates_found = deduplicate(db, ids)
    return report.as_dict()
