"""Builders for the skill detail, forecast and breakdown responses (global or filtered scope)."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import NotFoundError
from app.ml.feature_engineering import compute_metrics
from app.ml.forecasting import HORIZON, next_quarters
from app.ml.predict import forecast_filtered_series
from app.models.job import JobPosting
from app.models.prediction import Forecast, ModelMetric, Prediction, SkillRelation
from app.models.skill import Skill
from app.services.analysis_data import Filters, load_frequency_data
from app.services.insights import LIMITATIONS, build_explanation, forecast_summary
from app.services.obsolescence import score_skill
from app.services.queries import clean_float, history_points, relevance_label
from app.services.trend_analysis import (
    classify_trend,
    compute_scoped_trends,
    scoped_min_jobs,
    usable_series,
)

MIN_BREAKDOWN_JOBS = 100
BREAKDOWN_DIMENSIONS = {"role": JobPosting.role, "industry": JobPosting.industry, "region": JobPosting.region,
                        "country": JobPosting.country}


def get_skill(db: Session, skill_id: int) -> Skill:
    skill = db.get(Skill, skill_id)
    if skill is None:
        raise NotFoundError("Skill does not exist")
    return skill


def _relations(db: Session, skill_id: int, kind: str, limit: int) -> list[dict]:
    rows = db.execute(
        select(SkillRelation, Skill).join(Skill, Skill.id == SkillRelation.related_skill_id)
        .where(SkillRelation.skill_id == skill_id, SkillRelation.kind == kind)
        .order_by(SkillRelation.score.desc()).limit(limit)
    ).all()
    preds = {p.skill_id: p for p in db.scalars(select(Prediction).where(Prediction.skill_id.in_([r[1].id for r in rows] or [0])))}
    out = []
    for rel, sk in rows:
        p = preds.get(sk.id)
        out.append({"id": sk.id, "name": sk.name, "category": sk.category, "score": clean_float(rel.score, 3),
                    "details": rel.details, "trend_status": p.trend_status if p else None,
                    "current_demand": clean_float(p.current_demand) if p else None,
                    "growth_rate": clean_float(p.growth_rate) if p else None})
    return out


def skill_detail(db: Session, skill_id: int, filters: Filters | None = None) -> dict:
    """Full detail for the skill page: metrics, score breakdown, explanation, related skills, replacements."""
    skill = get_skill(db, skill_id)
    base = {"skill": {"id": skill.id, "name": skill.name, "category": skill.category, "description": skill.description,
                      "aliases": skill.aliases or []}, "limitations": LIMITATIONS}
    if filters is not None and filters.is_scoped:
        return {**base, **_scoped_detail(db, skill, filters)}

    pred = db.scalars(select(Prediction).where(Prediction.skill_id == skill_id)).first()
    if pred is None:
        return {**base, "scope": "global", "filters": {}, "prediction": None, "explanation": None,
                "related": [], "replacements": [], "message": "No analysis available yet. Run the pipeline."}
    related = _relations(db, skill_id, "cooccurrence", 8)
    replacements = _relations(db, skill_id, "replacement", 5)
    m = pred.metrics or {}
    return {**base, "scope": "global", "filters": {},
            "prediction": {
                "current_demand": clean_float(pred.current_demand), "growth_rate": clean_float(pred.growth_rate),
                "cagr": clean_float(pred.cagr), "yoy_growth": clean_float(pred.yoy_growth),
                "momentum": clean_float(pred.momentum), "future_demand": clean_float(pred.future_demand),
                "forecast_horizon_years": pred.forecast_horizon, "forecast_status": pred.forecast_status,
                "forecast_model": pred.forecast_model, "trend_status": pred.trend_status,
                "obsolescence_score": pred.obsolescence_score, "risk_level": pred.risk_level,
                "confidence": pred.confidence, "confidence_label": pred.confidence_label,
                "components": pred.components, "metrics": m, "model_version": pred.model_version,
                "prediction_date": pred.prediction_date},
            "explanation": pred.explanation, "related": related, "replacements": replacements}


def _scoped_detail(db: Session, skill: Skill, filters: Filters) -> dict:
    data, metrics = compute_scoped_trends(db, filters)
    m = metrics.get(skill.id)
    cls = classify_trend(m, None)
    score = score_skill(m, None, None, None) if m else None
    expl = build_explanation(skill.name, skill.category, m, cls, score, "not_applied", None, None, [], [], [])
    expl["forecast"] = "Forecasts are generated for the whole market; open the Forecast chart to forecast this filtered slice."
    prediction = None
    if m is not None:
        prediction = {"current_demand": clean_float(m.current_demand), "growth_rate": clean_float(m.long_term_growth),
                      "cagr": clean_float(m.cagr), "yoy_growth": clean_float(m.yoy_growth), "momentum": clean_float(m.momentum),
                      "future_demand": None, "forecast_status": "not_applied", "trend_status": cls.status,
                      "obsolescence_score": score.score, "risk_level": score.risk_level, "confidence": score.confidence,
                      "confidence_label": score.confidence_label, "components": [c.as_dict() for c in score.components],
                      "metrics": m.as_dict()}
    return {"scope": "filtered", "filters": filters.describe(), "prediction": prediction, "explanation": expl,
            "related": [], "replacements": [],
            "message": None if m else "Insufficient historical data for the selected filters."}


def forecast_view(db: Session, skill_id: int, filters: Filters | None = None) -> dict:
    """Quarterly history plus forecast path with intervals and model comparison."""
    skill = get_skill(db, skill_id)
    scoped = filters is not None and filters.is_scoped
    data = load_frequency_data(db, filters if scoped else None, "quarter", skill_ids=[skill_id])
    min_jobs = scoped_min_jobs(filters if scoped else None)
    history = history_points(data, skill_id, min_jobs) if not data.is_empty() else []
    out = {"skill": {"id": skill.id, "name": skill.name, "category": skill.category},
           "scope": "filtered" if scoped else "global", "filters": filters.describe() if scoped else {},
           "history": history, "forecast": [], "status": "insufficient_data", "reason": None, "model": None,
           "model_scores": [], "horizon_points": None, "model_version": None}
    if data.is_empty():
        out["reason"] = "No postings match the selected filters."
        return out

    if scoped:
        labels, mentions, jobs = usable_series(data, 0, min_jobs)
        res = forecast_filtered_series(mentions, jobs)
        if res.status != "ok":
            out["reason"] = res.reason
            out["model_scores"] = [s.as_dict() for s in res.scores.values()]
            return out
        usable_keys = [p for p, j in zip(data.periods, data.jobs) if j >= min_jobs]
        future = next_quarters(usable_keys[-1], HORIZON)
        path = {"mean": res.path.mean, "lower": res.path.lower, "upper": res.path.upper, "confidence": res.path.confidence}
        out.update({"status": "ok", "model": res.model_name, "model_scores": [s.as_dict() for s in res.scores.values()],
                    "forecast": [{"period": f"{y}-Q{q}", "predicted": clean_float(path["mean"][i]),
                                  "lower": clean_float(path["lower"][i]), "upper": clean_float(path["upper"][i]),
                                  "confidence": clean_float(path["confidence"][i], 3)} for i, (y, q) in enumerate(future)]})
        cur = float(mentions[-4:].sum() / jobs[-4:].sum())
        out["horizon_points"] = forecast_summary("ok", cur, path)["points"]
        return out

    rows = db.scalars(select(Forecast).where(Forecast.skill_id == skill_id).order_by(Forecast.step)).all()
    metrics = db.scalars(select(ModelMetric).where(ModelMetric.skill_id == skill_id)).all()
    out["model_scores"] = [{"name": m.model_name, "mae": clean_float(m.mae), "rmse": clean_float(m.rmse),
                            "mape": clean_float(m.mape), "r2": clean_float(m.r2), "n_folds": m.n_folds,
                            "selected": m.selected} for m in metrics]
    if not rows:
        pred = db.scalars(select(Prediction).where(Prediction.skill_id == skill_id)).first()
        out["reason"] = ("Insufficient historical data" if pred else "No analysis available yet. Run the pipeline.")
        if pred is not None:
            out["reason"] += " (fewer than 12 usable quarters or too few mentions)."
        return out
    path = {"mean": [r.predicted_demand for r in rows], "lower": [r.lower_bound for r in rows],
            "upper": [r.upper_bound for r in rows], "confidence": [r.confidence for r in rows]}
    labels, mentions, jobs = usable_series(data, 0, min_jobs)
    cur = float(mentions[-4:].sum() / jobs[-4:].sum())
    out.update({"status": "ok", "model": rows[0].model_name, "model_version": rows[0].model_version,
                "forecast": [{"period": f"{r.period_year}-Q{r.period_quarter}", "predicted": clean_float(r.predicted_demand),
                              "lower": clean_float(r.lower_bound), "upper": clean_float(r.upper_bound),
                              "confidence": clean_float(r.confidence, 3)} for r in rows],
                "horizon_points": forecast_summary("ok", cur, path)["points"]})
    return out


def _growth_label(yoy: float | None, long_term: float | None) -> str:
    g = yoy if yoy is not None else (long_term or 0.0)
    if g >= 0.5:
        return "Very high growth"
    if g >= 0.2:
        return "High growth"
    if g >= 0.05:
        return "Moderate growth"
    if g > -0.05:
        return "Flat"
    if g > -0.2:
        return "Declining"
    return "Sharp decline"


def breakdown(db: Session, skill_id: int, by: str, base: Filters | None = None) -> dict:
    """Skill demand and trend for each role / industry / region / country."""
    skill = get_skill(db, skill_id)
    if by not in BREAKDOWN_DIMENSIONS:
        raise NotFoundError(f"Unknown breakdown dimension '{by}'. Use one of {sorted(BREAKDOWN_DIMENSIONS)}.")
    base = base or Filters()
    col = BREAKDOWN_DIMENSIONS[by]
    cleared = Filters(**{**base.__dict__, by: None})
    from app.services.analysis_data import job_conditions
    values = [v for (v,) in db.execute(select(col).where(*job_conditions(cleared), col.is_not(None)).distinct()) if v and v != "Other"]
    items = []
    for value in sorted(values):
        f = Filters(**{**cleared.__dict__, by: value})
        data = load_frequency_data(db, f, "quarter", skill_ids=[skill_id])
        if data.is_empty():
            continue
        mask = data.jobs >= settings.MIN_JOBS_PER_PERIOD_SCOPED
        labels = [l for l, ok in zip(data.labels, mask) if ok]
        jobs, mentions = data.jobs[mask], data.mentions[mask, 0]
        trailing_jobs = int(jobs[-4:].sum()) if len(jobs) else 0
        sufficient = len(labels) >= 8 and trailing_jobs >= MIN_BREAKDOWN_JOBS
        item = {"key": value, "jobs": trailing_jobs, "sufficient": sufficient}
        if not sufficient:
            item.update({"share": None, "prior_share": None, "growth_rate": None, "yoy_growth": None, "trend_status": None,
                         "relevance": None, "growth_label": None,
                         "message": "Insufficient data for a reliable estimate"})
            items.append(item)
            continue
        m = compute_metrics(labels, mentions, jobs)
        share = float(mentions[-4:].sum() / jobs[-4:].sum())
        if m is None:
            item.update({"share": clean_float(share), "prior_share": None, "growth_rate": None, "yoy_growth": None,
                         "trend_status": "insufficient_data", "relevance": relevance_label(share), "growth_label": None})
        else:
            status = classify_trend(m, None).status
            item.update({"share": clean_float(m.current_demand), "prior_share": clean_float(m.prev_demand),
                         "growth_rate": clean_float(m.long_term_growth), "yoy_growth": clean_float(m.yoy_growth),
                         "trend_status": status, "relevance": relevance_label(m.current_demand),
                         "growth_label": _growth_label(m.yoy_growth, m.long_term_growth), "p_value": clean_float(m.p_long, 4)})
        items.append(item)
    items.sort(key=lambda i: (i["share"] is None, -(i["share"] or 0)))
    return {"skill": {"id": skill.id, "name": skill.name}, "by": by, "items": items,
            "sufficient_count": sum(1 for i in items if i["sufficient"]),
            "note": f"Only segments with at least {MIN_BREAKDOWN_JOBS} postings in the last year and 8 usable quarters are shown with numbers."}


def latest_posted_date(db: Session) -> date | None:
    return db.scalar(select(func.max(JobPosting.posted_date)))


__all__ = ["timedelta", "np"]
