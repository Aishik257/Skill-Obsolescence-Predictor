"""Read-side helpers shared by the API routes.

``skill_rows`` returns one uniform dict per skill. With no filters it reads the stored
predictions (fast, includes forecasts). With role/industry/location/date filters it
recomputes trend metrics, classification and a forecast-free risk score on the filtered slice,
so every chart and KPI responds to filters.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.prediction import Prediction
from app.models.skill import Skill
from app.services.analysis_data import Filters, FrequencyData, frequency_frame
from app.services.obsolescence import score_skill
from app.services.trend_analysis import classify_trend, compute_scoped_trends

PAGE_SIZE_MAX = 200
SORTABLE = {
    "name": lambda r: r["name"].lower(),
    "demand": lambda r: r["current_demand"],
    "growth": lambda r: r["growth_rate"] if r["growth_rate"] is not None else -math.inf,
    "yoy": lambda r: r["yoy_growth"] if r["yoy_growth"] is not None else -math.inf,
    "momentum": lambda r: r["momentum"] if r["momentum"] is not None else -math.inf,
    "score": lambda r: r["obsolescence_score"] if r["obsolescence_score"] is not None else -math.inf,
    "confidence": lambda r: r["confidence"] if r["confidence"] is not None else -math.inf,
    "pp_change": lambda r: r["pp_change"] if r["pp_change"] is not None else -math.inf,
}


def clean_float(x: float | None, ndigits: int = 5) -> float | None:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), ndigits)


def stored_rows(db: Session) -> list[dict]:
    """Rows from the stored predictions (global scope)."""
    q = select(Skill, Prediction).join(Prediction, Prediction.skill_id == Skill.id)
    rows = []
    for skill, p in db.execute(q):
        m = p.metrics or {}
        rows.append({
            "id": skill.id, "name": skill.name, "slug": skill.canonical_name, "category": skill.category,
            "current_demand": clean_float(p.current_demand), "growth_rate": clean_float(p.growth_rate),
            "yoy_growth": clean_float(p.yoy_growth), "cagr": clean_float(p.cagr), "momentum": clean_float(p.momentum),
            "pp_change": clean_float(m.get("pp_change")), "first_demand": clean_float(m.get("first_demand")),
            "future_demand": clean_float(p.future_demand), "forecast_status": p.forecast_status,
            "trend_status": p.trend_status, "obsolescence_score": p.obsolescence_score, "risk_level": p.risk_level,
            "confidence": p.confidence, "confidence_label": p.confidence_label,
            "forecast_change_2y": (clean_float(p.future_demand / max(p.current_demand, 0.01) - 1)
                                   if p.future_demand is not None else None),
            "scope": "global",
        })
    return rows


def scoped_rows(db: Session, filters: Filters) -> tuple[list[dict], FrequencyData]:
    """Rows recomputed on the filtered slice (no stored forecast, so the score omits that component)."""
    data, metrics = compute_scoped_trends(db, filters)
    names = {s.id: s for s in db.scalars(select(Skill).where(Skill.id.in_(data.skill_ids or [0])))}
    rows = []
    for sid, m in metrics.items():
        skill = names.get(sid)
        if skill is None:
            continue
        cls = classify_trend(m, None)
        score = score_skill(m, None, None, None) if m else None
        if m is None:  # not enough data under this filter
            idx = data.skill_ids.index(sid)
            total_jobs = float(data.jobs[-4:].sum()) or 1.0
            cur = float(data.mentions[-4:, idx].sum() / total_jobs)
        rows.append({
            "id": sid, "name": skill.name, "slug": skill.canonical_name, "category": skill.category,
            "current_demand": clean_float(m.current_demand if m else cur),
            "growth_rate": clean_float(m.long_term_growth if m else None), "yoy_growth": clean_float(m.yoy_growth if m else None),
            "cagr": clean_float(m.cagr if m else None), "momentum": clean_float(m.momentum if m else None),
            "pp_change": clean_float(m.pp_change if m else None), "first_demand": clean_float(m.first_demand if m else None),
            "future_demand": None, "forecast_status": "not_applied_to_filters", "trend_status": cls.status,
            "obsolescence_score": score.score if score else None, "risk_level": score.risk_level if score else None,
            "confidence": score.confidence if score else None, "confidence_label": score.confidence_label if score else None,
            "forecast_change_2y": None, "scope": "filtered",
        })
    return rows, data


def skill_rows(db: Session, filters: Filters | None = None) -> list[dict]:
    """Uniform skill rows for the given scope (stored predictions when unfiltered)."""
    if filters is not None and filters.is_scoped:
        return scoped_rows(db, filters)[0]
    return stored_rows(db)


def filter_rows(rows: list[dict], q: str | None = None, category: str | None = None, status: str | None = None,
                risk: str | None = None, min_demand: float | None = None) -> list[dict]:
    out = rows
    if q:
        ql = q.lower().strip()
        out = [r for r in out if ql in r["name"].lower() or ql in r["slug"]]
    if category:
        cats = {c.strip().lower() for c in category.split(",")}
        out = [r for r in out if r["category"].lower() in cats]
    if status:
        sts = {s.strip().lower() for s in status.split(",")}
        out = [r for r in out if r["trend_status"] in sts]
    if risk:
        rks = {s.strip().upper() for s in risk.split(",")}
        out = [r for r in out if (r["risk_level"] or "") in rks]
    if min_demand:
        out = [r for r in out if (r["current_demand"] or 0) >= min_demand]
    return out


def sort_rows(rows: list[dict], sort: str = "demand", order: str = "desc") -> list[dict]:
    key = SORTABLE.get(sort, SORTABLE["demand"])
    return sorted(rows, key=key, reverse=(order != "asc"))


def paginate(rows: list[dict], page: int = 1, page_size: int = 25) -> dict:
    page_size = max(1, min(PAGE_SIZE_MAX, page_size))
    page = max(1, page)
    total = len(rows)
    pages = max(1, math.ceil(total / page_size))
    start = (page - 1) * page_size
    return {"items": rows[start:start + page_size], "total": total, "page": page, "page_size": page_size, "pages": pages}


def history_points(data: FrequencyData, skill_id: int, min_jobs: int) -> list[dict]:
    """Per-period demand with a Wilson CI, a trailing moving average and a low-sample flag."""
    from app.ml.feature_engineering import moving_average, wilson_interval

    frame = frequency_frame(data, skill_id)
    if frame.empty:
        return []
    freq = frame["frequency"].to_numpy()
    window = {"month": 6, "quarter": 4, "year": 2}.get(data.granularity, 4)
    ma = moving_average(freq, window)
    pts = []
    for i, row in frame.iterrows():
        jobs, ments = float(row["jobs"]), float(row["mentions"])
        lo, hi = wilson_interval(ments, jobs) if jobs > 0 else (None, None)
        pts.append({"period": row["period"], "jobs": int(jobs), "mentions": int(ments),
                    "frequency": clean_float(None if jobs <= 0 else ments / jobs),
                    "ci_low": clean_float(lo), "ci_high": clean_float(hi), "moving_average": clean_float(ma[i]),
                    "low_sample": bool(jobs < min_jobs)})
    return pts


def year_to_range(year: int | None, date_from: date | None, date_to: date | None) -> tuple[date | None, date | None]:
    """A single ``year`` filter overrides explicit dates."""
    if year:
        return date(year, 1, 1), date(year, 12, 31)
    return date_from, date_to


def relevance_label(share: float) -> str:
    if share >= 0.40:
        return "Core requirement"
    if share >= 0.20:
        return "High relevance"
    if share >= 0.08:
        return "Moderate relevance"
    return "Low relevance"


__all__ = ["np"]
