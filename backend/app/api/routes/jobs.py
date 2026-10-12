"""Job posting endpoints: list, detail, CSV upload (validate or import), delete, stats."""
from __future__ import annotations

import os
import re

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Pagination, get_pagination
from app.core.config import settings
from app.core.database import get_db
from app.core.errors import BadRequestError, NotFoundError
from app.models.job import JobPosting
from app.models.job_skill import JobSkill
from app.models.prediction import PipelineRun, Prediction
from app.models.skill import Skill
from app.services.ingestion import ingest_csv, validate_upload
from app.utils.cache import analysis_cache

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _like(term: str) -> str:
    return "%" + re.sub(r"([%_\\])", r"\\\1", term.strip()) + "%"


def _job_row(j: JobPosting, n_skills: int) -> dict:
    return {"id": j.id, "source_job_id": j.source_job_id, "title": j.title, "company": j.company,
            "location": j.location, "industry": j.industry, "role": j.role, "country": j.country,
            "posted_date": j.posted_date.isoformat(), "is_duplicate": j.is_duplicate, "skills_count": n_skills,
            "source": j.source}


@router.get("", summary="List job postings")
def list_jobs(q: str | None = Query(None, max_length=100, description="Search title or company"),
              role: str | None = None, industry: str | None = None, year: int | None = Query(None, ge=2000, le=2100),
              country: str | None = None, include_duplicates: bool = False,
              p: Pagination = Depends(get_pagination), db: Session = Depends(get_db)) -> dict:
    conds = []
    if not include_duplicates:
        conds.append(JobPosting.is_duplicate.is_(False))
    if q:
        conds.append(JobPosting.title.ilike(_like(q), escape="\\") | JobPosting.company.ilike(_like(q), escape="\\"))
    for col, val in ((JobPosting.role, role), (JobPosting.industry, industry), (JobPosting.country, country),
                     (JobPosting.year, year)):
        if val:
            conds.append(col == val)
    total = db.scalar(select(func.count()).select_from(JobPosting).where(*conds)) or 0
    counts = select(JobSkill.job_id, func.count().label("n")).group_by(JobSkill.job_id).subquery()
    rows = db.execute(
        select(JobPosting, func.coalesce(counts.c.n, 0)).outerjoin(counts, counts.c.job_id == JobPosting.id)
        .where(*conds).order_by(JobPosting.posted_date.desc(), JobPosting.id.desc()).offset(p.offset).limit(p.page_size)
    ).all()
    return {"items": [_job_row(j, n) for j, n in rows], "total": total, "page": p.page, "page_size": p.page_size,
            "pages": max(1, -(-total // p.page_size))}


@router.get("/stats", summary="Data set status: counts, date range, pending work")
def job_stats(db: Session = Depends(get_db)) -> dict:
    total = db.scalar(select(func.count()).select_from(JobPosting)) or 0
    dups = db.scalar(select(func.count()).select_from(JobPosting).where(JobPosting.is_duplicate.is_(True))) or 0
    pending_clean = db.scalar(select(func.count()).select_from(JobPosting).where(JobPosting.cleaned_at.is_(None))) or 0
    pending_extract = db.scalar(select(func.count()).select_from(JobPosting).where(
        JobPosting.cleaned_at.is_not(None), JobPosting.is_duplicate.is_(False), JobPosting.skills_extracted_at.is_(None))) or 0
    dmin, dmax, last_created = db.execute(
        select(func.min(JobPosting.posted_date), func.max(JobPosting.posted_date), func.max(JobPosting.created_at))).one()
    by_year = db.execute(select(JobPosting.year, func.count()).where(JobPosting.is_duplicate.is_(False), JobPosting.year.is_not(None))
                         .group_by(JobPosting.year).order_by(JobPosting.year)).all()
    last_pred = db.scalar(select(func.max(Prediction.prediction_date)))
    last_run = db.scalar(select(PipelineRun).where(PipelineRun.status == "completed").order_by(PipelineRun.id.desc()).limit(1))
    stale = bool(total) and (last_pred is None or pending_clean > 0 or pending_extract > 0
                             or (last_created is not None and last_created > last_pred))
    return {"total_postings": total, "duplicates": dups, "active_postings": total - dups,
            "pending_cleaning": pending_clean, "pending_extraction": pending_extract,
            "skills_extracted_links": db.scalar(select(func.count()).select_from(JobSkill)) or 0,
            "date_min": dmin.isoformat() if dmin else None, "date_max": dmax.isoformat() if dmax else None,
            "postings_by_year": [{"year": y, "postings": n} for y, n in by_year],
            "has_predictions": last_pred is not None, "last_prediction": last_pred.isoformat() if last_pred else None,
            "analysis_stale": stale, "last_run": last_run.result if last_run else None}


@router.get("/{job_id}", summary="Job posting detail with extracted skills")
def get_job(job_id: int, db: Session = Depends(get_db)) -> dict:
    job = db.get(JobPosting, job_id)
    if job is None:
        raise NotFoundError(f"Job posting {job_id} does not exist")
    skills = db.execute(
        select(Skill.id, Skill.name, Skill.category, JobSkill.confidence_score, JobSkill.extraction_method)
        .join(JobSkill, JobSkill.skill_id == Skill.id).where(JobSkill.job_id == job_id).order_by(JobSkill.confidence_score.desc())
    ).all()
    return {**_job_row(job, len(skills)), "description": job.description, "clean_description": job.clean_description,
            "employment_type": job.employment_type, "city": job.city, "region": job.region,
            "duplicate_of_id": job.duplicate_of_id,
            "skills": [{"skill_id": s, "name": n, "category": c, "confidence": conf, "method": m} for s, n, c, conf, m in skills]}


@router.post("/upload", summary="Upload a CSV of job postings (use dry_run=true to validate only)")
async def upload_jobs(file: UploadFile = File(...), dry_run: bool = Query(False), db: Session = Depends(get_db)) -> dict:
    name = os.path.basename(file.filename or "")
    name = re.sub(r"[^\w.\- ]", "_", name)[:200]
    limit = settings.max_upload_bytes
    buf = bytearray()
    while chunk := await file.read(1024 * 1024):
        buf.extend(chunk)
        if len(buf) > limit:
            raise BadRequestError(f"File too large: the limit is {settings.MAX_UPLOAD_SIZE_MB} MB.", status_code=413)
    validate_upload(name, file.content_type, len(buf))
    report = ingest_csv(db, bytes(buf), name, dry_run=dry_run)
    if report.imported:
        analysis_cache.clear()
    return report.as_dict()


@router.delete("/{job_id}", summary="Delete a job posting", status_code=200)
def delete_job(job_id: int, db: Session = Depends(get_db)) -> dict:
    job = db.get(JobPosting, job_id)
    if job is None:
        raise NotFoundError(f"Job posting {job_id} does not exist")
    db.query(JobPosting).filter(JobPosting.duplicate_of_id == job_id).update({"duplicate_of_id": None})
    db.execute(JobSkill.__table__.delete().where(JobSkill.job_id == job_id))
    db.delete(job)
    db.commit()
    analysis_cache.clear()
    return {"deleted": job_id, "note": "Re-run the pipeline to refresh trends and predictions."}
