"""History and forecast views for one skill, for the global data set or any filtered slice."""
from __future__ import annotations

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.ml.feature_engineering import compute_metrics, moving_average, wilson_interval
from app.ml.forecasting import next_quarters
from app.ml.predict import forecast_filtered_series
from app.models.prediction import Prediction
from app.models.skill import Skill
from app.services.analysis_data import Filters, FrequencyData, load_frequency_data, period_label
from app.services.trend_analysis import scoped_min_jobs, usable_series
from app.services.views import forecast_path, model_scores

MA_WINDOW = {"quarter": 4, "month": 12, "year": 2}
RELIABLE_SCALE = {"month": 1 / 3, "quarter": 1.0, "year": 4.0}
HORIZONS = {1: 4, 2: 8, 3: 12}


def get_skill(db: Session, skill_id: int) -> Skill:
    skill = db.get(Skill, skill_id)
    if skill is None:
        raise NotFoundError(f"Skill {skill_id} does not exist")
    return skill


def history_view(db: Session, skill: Skill, filters: Filters, granularity: str) -> dict:
    """Per-period demand (share of postings) with Wilson interval and moving average."""
    data = load_frequency_data(db, filters, granularity, skill_ids=[skill.id])
    if data.is_empty():
        return {"skill_id": skill.id, "name": skill.name, "granularity": granularity, "filters": filters.describe(),
                "empty": True, "points": [], "message": "No job postings match these filters."}
    mentions, jobs = data.mentions[:, 0], data.jobs
    with np.errstate(divide="ignore", invalid="ignore"):
        freq = np.where(jobs > 0, mentions / jobs, np.nan)
    ma = moving_average(freq, MA_WINDOW[granularity])
    # a period is "reliable" when it holds enough postings; thresholds scale with period length
    min_jobs = max(1, round(scoped_min_jobs(filters) * RELIABLE_SCALE[granularity]))
    points = []
    for i, label in enumerate(data.labels):
        lo, hi = wilson_interval(mentions[i], jobs[i]) if jobs[i] > 0 else (None, None)
        points.append({"period": label, "jobs": int(jobs[i]), "mentions": int(mentions[i]),
                       "frequency": None if np.isnan(freq[i]) else float(freq[i]),
                       "moving_average": None if np.isnan(ma[i]) else float(ma[i]),
                       "ci_low": lo, "ci_high": hi, "reliable": bool(jobs[i] >= min_jobs)})
    q = data if granularity == "quarter" else load_frequency_data(db, filters, "quarter", skill_ids=[skill.id])
    labels, qm, qj = usable_series(q, 0, scoped_min_jobs(filters))
    metrics = compute_metrics(labels, qm, qj) if len(labels) else None
    return {"skill_id": skill.id, "name": skill.name, "granularity": granularity, "filters": filters.describe(),
            "empty": bool(mentions.sum() == 0), "points": points, "total_jobs": int(jobs.sum()),
            "total_mentions": int(mentions.sum()), "metrics": metrics.as_dict() if metrics else None,
            "ma_window": MA_WINDOW[granularity]}


def _history_points(data: FrequencyData, min_jobs: int) -> list[dict]:
    out = []
    for i, label in enumerate(data.labels):
        if data.jobs[i] >= min_jobs:
            out.append({"period": label, "jobs": int(data.jobs[i]), "mentions": int(data.mentions[i, 0]),
                        "frequency": float(data.mentions[i, 0] / data.jobs[i])})
    return out


def forecast_view(db: Session, skill: Skill, filters: Filters) -> dict:
    """Historical + forecast demand. Global: read stored forecast. Filtered: fit models live."""
    data = load_frequency_data(db, filters, "quarter", skill_ids=[skill.id])
    min_jobs = scoped_min_jobs(filters)
    base = {"skill_id": skill.id, "name": skill.name, "filters": filters.describe(),
            "scope": "filtered" if filters.is_scoped else "global", "history": _history_points(data, min_jobs)
            if not data.is_empty() else []}
    if data.is_empty():
        return {**base, "status": "insufficient_data", "message": "Insufficient historical data",
                "reason": "No job postings match these filters.", "forecast": [], "horizons": {}}

    if not filters.is_scoped:
        rows = forecast_path(db, skill.id)
        pred = db.scalar(select(Prediction).where(Prediction.skill_id == skill.id))
        if not rows:
            return {**base, "status": "insufficient_data", "message": "Insufficient historical data",
                    "reason": "Fewer than the required quarters or mentions to validate a forecast model.",
                    "forecast": [], "horizons": {}, "models": model_scores(db, skill.id)}
        current = pred.current_demand if pred else None
        fc = [{"step": r.step, "period": f"{r.period_year}-Q{r.period_quarter}", "predicted": r.predicted_demand,
               "lower": r.lower_bound, "upper": r.upper_bound, "confidence": r.confidence} for r in rows]
        return {**base, "status": "ok", "model": rows[0].model_name, "model_version": rows[0].model_version,
                "models": model_scores(db, skill.id), "forecast": fc, "current_demand": current,
                "horizons": _horizons(fc, current)}

    labels, mentions, jobs = usable_series(data, 0, min_jobs)
    if len(labels) == 0:
        return {**base, "status": "insufficient_data", "message": "Insufficient historical data",
                "reason": "No quarter has enough postings under these filters.", "forecast": [], "horizons": {}}
    share = mentions / jobs
    res = forecast_filtered_series(share, jobs, mentions)
    if res.status != "ok" or res.path is None:
        return {**base, "status": "insufficient_data", "message": "Insufficient historical data",
                "reason": res.reason, "forecast": [], "horizons": {}}
    keys = [k for k, ok in zip(data.periods, data.jobs >= min_jobs) if ok]
    fc = [{"step": s, "period": period_label(y * 10 + q, "quarter"), "predicted": res.path.mean[s - 1],
           "lower": res.path.lower[s - 1], "upper": res.path.upper[s - 1], "confidence": res.path.confidence[s - 1]}
          for s, (y, q) in enumerate(next_quarters(keys[-1], len(res.path.steps)), start=1)]
    current = float(mentions[-4:].sum() / jobs[-4:].sum())
    return {**base, "status": "ok", "model": res.model_name, "model_version": "live-filtered",
            "models": [{"model": n, "mae": s.mae, "rmse": s.rmse, "mape": s.mape, "r2": s.r2, "folds": s.n_folds,
                        "selected": n == res.model_name} for n, s in res.scores.items()],
            "forecast": fc, "current_demand": current, "horizons": _horizons(fc, current)}


def _horizons(fc: list[dict], current: float | None) -> dict:
    out = {}
    for years, step in HORIZONS.items():
        p = fc[step - 1]
        out[f"{years}y"] = {"period": p["period"], "predicted": p["predicted"], "lower": p["lower"],
                            "upper": p["upper"], "confidence": p["confidence"],
                            "change": None if not current else (p["predicted"] - current) / max(current, 0.01)}
    return out
