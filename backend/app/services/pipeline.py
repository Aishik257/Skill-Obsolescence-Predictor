"""Pipeline orchestration: clean -> extract -> analyze -> forecast -> predict.

Each stage stores its output in PostgreSQL, so dashboards read cached results and the heavy
work only re-runs when the user (or a script) asks for it. A process-wide lock guarantees a
single run at a time; progress is written to ``pipeline_runs`` so the UI can poll it.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import BadRequestError, ConflictError, PipelineError
from app.ml.forecasting import next_quarters
from app.ml.train import save_bundle, series_for, train_all
from app.models.job import JobPosting
from app.models.job_skill import JobSkill
from app.models.prediction import Forecast, ModelMetric, PipelineRun, Prediction, SkillRelation
from app.models.skill import Skill
from app.services import replacement as repl
from app.services.analysis_data import Filters, job_conditions, load_frequency_data, role_skill_shares
from app.services.cleaning import run_cleaning
from app.services.extraction_runner import reset_extraction, run_extraction
from app.services.insights import build_explanation
from app.services.normalization import sync_taxonomy
from app.services.obsolescence import score_skill
from app.services.trend_analysis import classify_trend, compute_all_metrics, persist_monthly_trends
from app.utils.cache import analysis_cache

logger = logging.getLogger(__name__)

_run_lock = threading.Lock()

STEP_MESSAGES = {
    "validate": "Validating data...", "clean": "Cleaning data...", "extract": "Extracting skills...",
    "analyze": "Analyzing historical trends...", "forecast": "Training forecasting model...",
    "predict": "Generating predictions...", "done": "Completed!",
}
# (stage, share of the progress bar)
RUN_ALL_STAGES = [("validate", 2), ("clean", 10), ("extract", 40), ("analyze", 12), ("forecast", 20), ("predict", 16)]
FORECAST_STEPS = {1: 4, 2: 8, 3: 12}  # horizon (years) -> quarter index
HEADLINE_HORIZON = 2


class Reporter:
    """Writes progress/log lines to the PipelineRun row."""

    def __init__(self, db: Session, run: PipelineRun, stages: list[tuple[str, int]]):
        self.db, self.run = db, run
        self.stages = dict(stages)
        self.order = [s for s, _ in stages]
        self.log: list[dict] = []

    def _base(self, stage: str) -> int:
        return sum(self.stages[s] for s in self.order[:self.order.index(stage)])

    def start(self, stage: str, detail: str = "") -> None:
        self._write(stage, self._base(stage), detail)

    def tick(self, stage: str, frac: float, detail: str = "") -> None:
        self._write(stage, self._base(stage) + int(self.stages[stage] * min(max(frac, 0), 1)), detail)

    def _write(self, stage: str, progress: int, detail: str) -> None:
        msg = STEP_MESSAGES.get(stage, stage) + (f" {detail}" if detail else "")
        self.log.append({"t": datetime.now(timezone.utc).isoformat(), "stage": stage, "message": msg})
        self.run.step, self.run.progress, self.run.log = msg, min(progress, 99), self.log[-50:]
        self.db.commit()


# --------------------------------------------------------------------------- stages
def stage_validate(db: Session) -> dict:
    total = db.scalar(select(func.count()).select_from(JobPosting)) or 0
    if total == 0:
        raise BadRequestError("No job postings available. Upload a CSV or load the sample dataset first.")
    no_desc = db.scalar(select(func.count()).select_from(JobPosting).where(
        (JobPosting.description.is_(None)) | (JobPosting.description == ""))) or 0
    return {"total_postings": total, "empty_descriptions": no_desc}


def stage_clean(db: Session) -> dict:
    return run_cleaning(db)


def stage_extract(db: Session, progress: Callable[[int, int], None] | None = None, reextract: bool = False) -> dict:
    if reextract:
        reset_extraction(db)
    return run_extraction(db, progress=progress)


def stage_analyze(db: Session) -> dict:
    """Monthly aggregates (skill_trends) plus co-occurrence and replacement relations."""
    sync_taxonomy(db)
    monthly = persist_monthly_trends(db)
    data = load_frequency_data(db, None, "quarter")
    if data.is_empty():
        raise BadRequestError("No cleaned postings with extracted skills. Run cleaning and skill extraction first.")
    metrics = compute_all_metrics(data)
    skills = {s.id: s for s in db.scalars(select(Skill))}
    cooc, repl_rows = repl.compute_relations(db, data, metrics, skills, settings.MIN_JOBS_PER_PERIOD)
    db.execute(delete(SkillRelation))
    for rows in (cooc, repl_rows):
        for i in range(0, len(rows), 5000):
            db.bulk_insert_mappings(SkillRelation, rows[i:i + 5000])
    db.commit()
    with_metrics = sum(1 for m in metrics.values() if m is not None)
    return {"trend_rows": monthly, "skills_with_trends": with_metrics, "skills_detected": len(data.skill_ids),
            "cooccurrence_pairs": len(cooc), "replacement_hypotheses": len(repl_rows)}


def stage_forecast(db: Session) -> dict:
    """Select and fit forecasting models per skill (rolling-origin CV) and store paths + metrics."""
    data = load_frequency_data(db, None, "quarter")
    if data.is_empty():
        raise BadRequestError("No data to forecast. Run the analysis first.")
    results, version = train_all(data)
    db.execute(delete(Forecast))
    db.execute(delete(ModelMetric))
    fc_rows, mm_rows = [], []
    ok = insufficient = 0
    for sid, (keys, res) in results.items():
        if res.status != "ok" or res.path is None:
            insufficient += 1
            continue
        ok += 1
        for step, (y, q) in enumerate(next_quarters(keys[-1], len(res.path.steps)), start=1):
            i = step - 1
            fc_rows.append({"skill_id": sid, "step": step, "period_year": y, "period_quarter": q,
                            "predicted_demand": res.path.mean[i], "lower_bound": res.path.lower[i],
                            "upper_bound": res.path.upper[i], "confidence": res.path.confidence[i],
                            "model_name": res.model_name, "model_version": version})
        for name, sc in res.scores.items():
            mm_rows.append({"skill_id": sid, "model_name": name, "mae": sc.mae, "rmse": sc.rmse, "mape": sc.mape,
                            "r2": sc.r2, "n_folds": sc.n_folds, "selected": name == res.model_name,
                            "model_version": version})
    db.bulk_insert_mappings(Forecast, fc_rows)
    db.bulk_insert_mappings(ModelMetric, mm_rows)
    db.commit()
    bundle = save_bundle(results, version)
    chosen: dict[str, int] = {}
    for _, res in results.values():
        if res.model_name:
            chosen[res.model_name] = chosen.get(res.model_name, 0) + 1
    return {"forecasts_generated": ok, "insufficient_data": insufficient, "model_version": version,
            "models_selected": chosen, "bundle": bundle.name}


def _top_roles(db: Session, as_of) -> dict[int, list[dict]]:
    jobs, mentions = role_skill_shares(db, as_of - timedelta(days=365), as_of)
    out: dict[int, list[dict]] = {}
    for (role, sid), n in mentions.items():
        if jobs.get(role, 0) >= 30:
            out.setdefault(sid, []).append({"role": role, "share": n / jobs[role]})
    return {sid: sorted(v, key=lambda r: -r["share"])[:3] for sid, v in out.items()}


def stage_predict(db: Session) -> dict:
    """Classify trends, compute obsolescence scores and write explanations."""
    data = load_frequency_data(db, None, "quarter")
    if data.is_empty():
        raise BadRequestError("No data to predict from. Run the analysis first.")
    metrics = compute_all_metrics(data)
    skills = {s.id: s for s in db.scalars(select(Skill))}
    as_of = db.scalar(select(func.max(JobPosting.posted_date)).where(*job_conditions(None)))
    top_roles = _top_roles(db, as_of)

    fc_by_skill: dict[int, list[Forecast]] = {}
    for f in db.scalars(select(Forecast).order_by(Forecast.skill_id, Forecast.step)):
        fc_by_skill.setdefault(f.skill_id, []).append(f)
    selected = {m.skill_id: m for m in db.scalars(select(ModelMetric).where(ModelMetric.selected.is_(True)))}
    relations = db.scalars(select(SkillRelation).where(SkillRelation.kind == "replacement")).all()
    pressure = repl.replacement_pressure([{"skill_id": r.skill_id, "score": r.score} for r in relations])
    repl_by_skill: dict[int, list[dict]] = {}
    for r in sorted(relations, key=lambda r: -r.score):
        details = r.details or {}
        repl_by_skill.setdefault(r.skill_id, []).append(
            {"skill_id": r.related_skill_id, "name": skills[r.related_skill_id].name, "score": r.score,
             "grower_change": details.get("grower_change", 0.0)})

    version = next((f[0].model_version for f in fc_by_skill.values()), "none")
    rows: list[dict] = []
    for sid, m in metrics.items():
        skill = skills.get(sid)
        if skill is None:
            continue
        fcs = fc_by_skill.get(sid)
        forecast_summary, change_2y, mape = None, None, None
        if fcs and m is not None:
            y1, y2, y3 = (fcs[FORECAST_STEPS[h] - 1].predicted_demand for h in (1, 2, 3))
            change_2y = (y2 - m.current_demand) / max(m.current_demand, 0.01)
            sel = selected.get(sid)
            mape = sel.mape if sel else None
            forecast_summary = {"status": "ok", "model": fcs[0].model_name, "y1": y1, "y2": y2, "y3": y3,
                                "change_2y": change_2y, "change_1y": (y1 - m.current_demand) / max(m.current_demand, 0.01),
                                "change_3y": (y3 - m.current_demand) / max(m.current_demand, 0.01)}
        cls = classify_trend(m, change_2y)
        score = score_skill(m, change_2y, pressure.get(sid, 0.0), mape, cls.status) if m is not None else None
        explanation = build_explanation(
            name=skill.name, category=skill.category, status=cls.status, rules=cls.rules,
            metrics=m.as_dict() if m else None, forecast=forecast_summary, score=score,
            top_roles=top_roles.get(sid, []), replacements=repl_by_skill.get(sid, []),
            as_of=as_of.isoformat() if as_of else None)
        if m is None:
            idx = data.index_of(sid)
            total = float(data.mentions[:, idx].sum()) if idx is not None else 0.0
            rows.append({"skill_id": sid, "current_demand": total / max(float(data.jobs.sum()), 1.0),
                         "trend_status": "insufficient_data", "model_version": version, "forecast_status": "insufficient_data",
                         "explanation": explanation, "metrics": None, "components": None})
            continue
        rows.append({
            "skill_id": sid, "current_demand": m.current_demand, "growth_rate": m.long_term_growth, "momentum": m.momentum,
            "cagr": m.cagr, "yoy_growth": m.yoy_growth,
            "future_demand": forecast_summary["y2"] if forecast_summary else None, "forecast_horizon": HEADLINE_HORIZON,
            "forecast_status": "ok" if forecast_summary else "insufficient_data",
            "trend_status": cls.status, "obsolescence_score": score.score, "risk_level": score.risk_level,
            "confidence": score.confidence, "confidence_label": score.confidence_label,
            "model_version": version, "forecast_model": forecast_summary["model"] if forecast_summary else None,
            "components": score.components,
            "metrics": {**m.as_dict(), "forecast": forecast_summary, "top_roles": top_roles.get(sid, []),
                        "replacement_pressure": pressure.get(sid, 0.0)},
            "explanation": explanation,
        })
    db.execute(delete(Prediction))
    db.bulk_insert_mappings(Prediction, rows)
    db.commit()
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["trend_status"]] = by_status.get(r["trend_status"], 0) + 1
    return {"predictions_generated": len(rows), "by_status": by_status,
            "scored": sum(1 for r in rows if r.get("obsolescence_score") is not None)}


# --------------------------------------------------------------------------- orchestration
def stale_runs_cleanup(db: Session) -> None:
    """Mark runs left 'running' by a crashed/restarted process as failed."""
    for run in db.scalars(select(PipelineRun).where(PipelineRun.status == "running")):
        run.status, run.error, run.finished_at = "failed", "Interrupted by a server restart", datetime.now(timezone.utc)
    db.commit()


def acquire() -> None:
    if not _run_lock.acquire(blocking=False):
        raise ConflictError("A pipeline run is already in progress. Wait for it to finish.")


def release() -> None:
    if _run_lock.locked():
        _run_lock.release()


def new_run(db: Session, kind: str) -> PipelineRun:
    run = PipelineRun(kind=kind, status="running", step="Starting...", progress=0, log=[])
    db.add(run)
    db.commit()
    return run


def execute(db: Session, run: PipelineRun, kind: str, reextract: bool = False) -> dict:
    """Run the stages for ``kind`` inside an already-acquired lock, finalising the run row."""
    started = time.time()
    plan = {
        "run-all": RUN_ALL_STAGES,
        "clean": [("clean", 100)], "extract-skills": [("extract", 100)], "analyze": [("analyze", 100)],
        "forecast": [("forecast", 100)], "predict": [("predict", 100)],
    }[kind]
    rep = Reporter(db, run, plan)
    result: dict = {}
    try:
        for stage, _ in plan:
            rep.start(stage)
            if stage == "validate":
                result["validation"] = stage_validate(db)
            elif stage == "clean":
                result["cleaning"] = stage_clean(db)
            elif stage == "extract":
                result["extraction"] = stage_extract(db, lambda d, t: rep.tick("extract", d / max(t, 1), f"({d}/{t} postings)"),
                                                     reextract)
            elif stage == "analyze":
                result["analysis"] = stage_analyze(db)
            elif stage == "forecast":
                result["forecast"] = stage_forecast(db)
            elif stage == "predict":
                result["prediction"] = stage_predict(db)
        summary = summarize(db, result, time.time() - started)
        run.status, run.progress, run.step, run.result = "completed", 100, STEP_MESSAGES["done"], summary
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        analysis_cache.clear()
        return summary
    except BadRequestError as exc:
        db.rollback()
        _fail(db, run, exc.message)
        raise
    except Exception as exc:  # noqa: BLE001 - recorded, logged and re-raised as an API error
        db.rollback()
        logger.error("Pipeline '%s' failed: %s\n%s", kind, exc, traceback.format_exc())
        _fail(db, run, f"{type(exc).__name__}: {exc}")
        raise PipelineError(f"Analysis pipeline failed: {exc}") from exc


def _fail(db: Session, run: PipelineRun, message: str) -> None:
    run = db.merge(run)
    run.status, run.error, run.finished_at = "failed", message, datetime.now(timezone.utc)
    db.commit()


def summarize(db: Session, result: dict, seconds: float) -> dict:
    """Headline numbers in the shape described by the API contract."""
    jobs = db.scalar(select(func.count()).select_from(JobPosting).where(*job_conditions(None))) or 0
    skills = db.scalar(select(func.count(func.distinct(JobSkill.skill_id)))) or 0
    trends = db.scalar(select(func.count()).select_from(Prediction).where(Prediction.trend_status != "insufficient_data")) or 0
    preds = db.scalar(select(func.count()).select_from(Prediction)) or 0
    return {"status": "completed", "jobs_processed": jobs, "skills_detected": skills, "trends_calculated": trends,
            "predictions_generated": preds, "duration_seconds": round(seconds, 1), "details": result}


def run_sync(db: Session, kind: str, reextract: bool = False) -> dict:
    """Run a pipeline kind synchronously (CLI, scripts, tests, blocking API calls)."""
    acquire()
    try:
        run = new_run(db, kind)
        return execute(db, run, kind, reextract)
    finally:
        release()


def start_background(kind: str, reextract: bool = False) -> int:
    """Start a pipeline run in a worker thread and return the run id immediately."""
    from app.core.database import SessionLocal  # local import keeps tests able to rebind the engine

    acquire()
    try:
        with SessionLocal() as db:
            run_id = new_run(db, kind).id
    except Exception:
        release()
        raise

    def worker() -> None:
        try:
            with SessionLocal() as db:
                execute(db, db.get(PipelineRun, run_id), kind, reextract)
        except Exception as exc:  # noqa: BLE001 - already recorded on the run row
            logger.warning("Background pipeline run %s ended with an error: %s", run_id, exc)
        finally:
            release()

    threading.Thread(target=worker, name=f"pipeline-{run_id}", daemon=True).start()
    return run_id
