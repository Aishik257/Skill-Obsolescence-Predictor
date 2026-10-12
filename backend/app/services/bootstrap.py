"""Schema migration and sample-data seeding, shared by scripts/seed_database.py and AUTO_SEED."""
from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.core.config import BACKEND_ROOT, settings
from app.core.errors import BadRequestError
from app.models import (Forecast, JobPosting, JobSkill, ModelMetric, PipelineRun, Prediction, SkillCandidate,
                        SkillRelation, SkillTrend)
from app.services import pipeline
from app.services.ingestion import ingest_csv
from app.services.normalization import sync_taxonomy

logger = logging.getLogger(__name__)


def upgrade_schema() -> None:
    """Apply Alembic migrations up to head."""
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(cfg, "head")


def reset_data(db: Session) -> None:
    """Delete all postings and derived analytics (the skill taxonomy is kept)."""
    for model in (Forecast, ModelMetric, Prediction, SkillRelation, SkillTrend, SkillCandidate, JobSkill, PipelineRun):
        db.execute(delete(model))
    db.execute(text("UPDATE job_postings SET duplicate_of_id = NULL"))
    db.execute(delete(JobPosting))
    db.commit()


def seed(db: Session, csv_path: Path | None = None, reset: bool = False, run_pipeline: bool = True) -> dict:
    """Load the taxonomy and a job-postings CSV, then run the full analysis pipeline."""
    csv_path = csv_path or settings.sample_data_path
    if not csv_path.exists():
        raise BadRequestError(f"Sample dataset not found at {csv_path}. Run scripts/generate_sample_data.py first.")
    if reset:
        reset_data(db)
    tax = sync_taxonomy(db)
    existing = db.scalar(select(func.count()).select_from(JobPosting)) or 0
    ingestion = None
    if existing == 0:
        report = ingest_csv(db, csv_path.read_bytes(), csv_path.name)
        ingestion = report.as_dict()
        logger.info("Seed: imported %d of %d rows from %s", report.imported, report.total_records, csv_path.name)
    result = pipeline.run_sync(db, "run-all") if run_pipeline else None
    return {"taxonomy": tax, "ingestion": ingestion, "pipeline": result}


def database_is_empty(db: Session) -> bool:
    return (db.scalar(select(func.count()).select_from(JobPosting)) or 0) == 0
