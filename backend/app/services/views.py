"""Read-side helpers that turn stored predictions (or live filtered metrics) into API rows."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ml.feature_engineering import TrendMetrics
from app.models.prediction import Forecast, ModelMetric, Prediction, SkillRelation
from app.models.skill import Skill
from app.services.analysis_data import Filters
from app.services.obsolescence import score_skill
from app.services.trend_analysis import STATUS_LABELS, classify_trend, compute_scoped_trends
from app.utils.cache import analysis_cache


def data_version(db: Session) -> tuple:
    """Changes whenever predictions are regenerated; part of every cache key."""
    return (db.scalar(select(func.max(Prediction.prediction_date))), db.scalar(select(func.count()).select_from(Prediction)))


def prediction_row(skill: Skill, p: Prediction | None) -> dict:
    """Flat API row for a skill with its (global) prediction."""
    base = {"skill_id": skill.id, "name": skill.name, "slug": skill.canonical_name, "category": skill.category,
            "aliases": skill.aliases or []}
    if p is None:
        return {**base, "trend_status": "insufficient_data", "status_label": STATUS_LABELS["insufficient_data"],
                "current_demand": 0.0, "scope": "global"}
    return {**base, "scope": "global", "trend_status": p.trend_status,
            "status_label": STATUS_LABELS.get(p.trend_status, p.trend_status), "current_demand": p.current_demand,
            "growth_rate": p.growth_rate, "yoy_growth": p.yoy_growth, "cagr": p.cagr, "momentum": p.momentum,
            "future_demand": p.future_demand, "forecast_horizon": p.forecast_horizon,
            "forecast_status": p.forecast_status, "forecast_model": p.forecast_model,
            "obsolescence_score": p.obsolescence_score, "risk_level": p.risk_level, "confidence": p.confidence,
            "confidence_label": p.confidence_label, "model_version": p.model_version,
            "prediction_date": p.prediction_date.isoformat() if p.prediction_date else None}


def global_rows(db: Session) -> list[dict]:
    skills = {s.id: s for s in db.scalars(select(Skill))}
    preds = {p.skill_id: p for p in db.scalars(select(Prediction))}
    return [prediction_row(skills[sid], p) for sid, p in preds.items() if sid in skills]


def metrics_row(skill: Skill, m: TrendMetrics | None, scope: dict) -> dict:
    """Row computed live from filtered data (no forecast, so the score redistributes that weight)."""
    cls = classify_trend(m, None)
    base = {"skill_id": skill.id, "name": skill.name, "slug": skill.canonical_name, "category": skill.category,
            "aliases": skill.aliases or [], "scope": "filtered", "filters": scope}
    if m is None:
        return {**base, "trend_status": "insufficient_data", "status_label": STATUS_LABELS["insufficient_data"],
                "current_demand": 0.0}
    sc = score_skill(m, None, 0.0, None, cls.status)
    return {**base, "trend_status": cls.status, "status_label": STATUS_LABELS[cls.status],
            "current_demand": m.current_demand, "growth_rate": m.long_term_growth, "yoy_growth": m.yoy_growth,
            "cagr": m.cagr, "momentum": m.momentum, "future_demand": None, "forecast_status": "not_applied",
            "obsolescence_score": sc.score, "risk_level": sc.risk_level, "confidence": sc.confidence,
            "confidence_label": sc.confidence_label}


def scoped_rows(db: Session, filters: Filters) -> list[dict]:
    """Rows for every skill under the filters (cached)."""
    def build() -> list[dict]:
        data, metrics = compute_scoped_trends(db, filters)
        skills = {s.id: s for s in db.scalars(select(Skill))}
        return [metrics_row(skills[sid], m, filters.describe()) for sid, m in metrics.items() if sid in skills]
    return analysis_cache.get_or_set(("rows", data_version(db), filters.cache_key()), build)


def rows_for(db: Session, filters: Filters) -> list[dict]:
    """Global rows from stored predictions, or live filtered rows when filters are active."""
    return scoped_rows(db, filters) if filters.is_scoped else global_rows(db)


def relations(db: Session, skill_id: int, kind: str, limit: int = 10) -> list[dict]:
    skills = {s.id: s for s in db.scalars(select(Skill))}
    rows = db.scalars(select(SkillRelation).where(SkillRelation.skill_id == skill_id, SkillRelation.kind == kind)
                      .order_by(SkillRelation.score.desc()).limit(limit)).all()
    out = []
    for r in rows:
        other = skills.get(r.related_skill_id)
        if other:
            out.append({"skill_id": other.id, "name": other.name, "category": other.category, "score": r.score,
                        "details": r.details or {}})
    return out


def forecast_path(db: Session, skill_id: int) -> list[Forecast]:
    return db.scalars(select(Forecast).where(Forecast.skill_id == skill_id).order_by(Forecast.step)).all()


def model_scores(db: Session, skill_id: int) -> list[dict]:
    return [{"model": m.model_name, "mae": m.mae, "rmse": m.rmse, "mape": m.mape, "r2": m.r2, "folds": m.n_folds,
             "selected": m.selected} for m in db.scalars(select(ModelMetric).where(ModelMetric.skill_id == skill_id))]
