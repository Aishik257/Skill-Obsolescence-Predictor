"""Pipeline endpoints: run stages synchronously or in the background and poll progress."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import NotFoundError
from app.models.prediction import PipelineRun
from app.services import pipeline as pipe

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _run(kind: str, background: bool, reextract: bool, db: Session) -> dict:
    if background:
        return {"run_id": pipe.start_background(kind, reextract), "status": "running", "kind": kind,
                "message": "Pipeline started. Poll GET /api/pipeline/status?run_id=<id> for progress."}
    return pipe.run_sync(db, kind, reextract)


def _run_dict(r: PipelineRun) -> dict:
    return {"run_id": r.id, "kind": r.kind, "status": r.status, "step": r.step, "progress": r.progress,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "result": r.result, "error": r.error, "log": r.log or []}


@router.post("/clean", summary="Clean and de-duplicate imported postings")
def clean(background: bool = Query(False), db: Session = Depends(get_db)) -> dict:
    return _run("clean", background, False, db)


@router.post("/extract-skills", summary="Extract and normalize skills from postings")
def extract_skills(background: bool = Query(False), reextract: bool = Query(False, description="Re-process every posting"),
                   db: Session = Depends(get_db)) -> dict:
    return _run("extract-skills", background, reextract, db)


@router.post("/analyze", summary="Historical aggregation, co-occurrence and replacement analysis")
def analyze(background: bool = Query(False), db: Session = Depends(get_db)) -> dict:
    return _run("analyze", background, False, db)


@router.post("/forecast", summary="Select and train forecasting models for every skill")
def forecast(background: bool = Query(False), db: Session = Depends(get_db)) -> dict:
    return _run("forecast", background, False, db)


@router.post("/predict", summary="Classify trends, score obsolescence risk and write explanations")
def predict(background: bool = Query(False), db: Session = Depends(get_db)) -> dict:
    return _run("predict", background, False, db)


@router.post("/run-all", summary="Run the complete pipeline")
def run_all(background: bool = Query(False), reextract: bool = Query(False), db: Session = Depends(get_db)) -> dict:
    return _run("run-all", background, reextract, db)


@router.get("/status", summary="Progress of a pipeline run (latest run if run_id is omitted)")
def status(run_id: int | None = None, db: Session = Depends(get_db)) -> dict:
    run = db.get(PipelineRun, run_id) if run_id else db.scalar(select(PipelineRun).order_by(PipelineRun.id.desc()).limit(1))
    if run is None:
        if run_id:
            raise NotFoundError(f"Pipeline run {run_id} does not exist")
        return {"status": "idle", "progress": 0, "step": None, "log": []}
    return _run_dict(run)


@router.get("/runs", summary="Recent pipeline runs")
def runs(limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(PipelineRun).order_by(PipelineRun.id.desc()).limit(limit)).all()
    return {"items": [{k: v for k, v in _run_dict(r).items() if k != "log"} for r in rows]}
