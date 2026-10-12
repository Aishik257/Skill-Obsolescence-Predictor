"""Analytics endpoints: dashboard overview, model performance, categories, filter options, comparisons."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Literal

import numpy as np
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_filters
from app.core.database import get_db
from app.ml.predict import load_latest_bundle
from app.models.job import JobPosting
from app.models.job_skill import JobSkill
from app.models.prediction import ModelMetric, Prediction, SkillCandidate
from app.models.skill import Skill
from app.services.analysis_data import Filters, dataset_overview, job_conditions, role_skill_shares
from app.services.insights import LIMITATIONS, market_outlook
from app.services.trend_analysis import STATUSES
from app.services.views import rows_for
from app.utils.geo import REGIONS
from app.utils.roles import ROLES

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _top(rows: list[dict], key: str, n: int, reverse: bool, statuses: set[str] | None = None, min_demand: float = 0.0) -> list[dict]:
    pool = [r for r in rows if r.get(key) is not None and (statuses is None or r["trend_status"] in statuses)
            and r.get("current_demand", 0) >= min_demand]
    return sorted(pool, key=lambda r: r[key], reverse=reverse)[:n]


@router.get("/overview", summary="Dashboard KPIs, rankings and market outlook (respects filters)")
def overview(filters: Filters = Depends(get_filters), db: Session = Depends(get_db)) -> dict:
    ov = dataset_overview(db, filters)
    rows = rows_for(db, filters)
    counts = {s: 0 for s in STATUSES}
    for r in rows:
        counts[r["trend_status"]] = counts.get(r["trend_status"], 0) + 1
    year_rows = db.execute(select(JobPosting.year, func.count()).where(*job_conditions(filters))
                           .group_by(JobPosting.year).order_by(JobPosting.year)).all()
    kpis = {"total_jobs": ov["total_jobs"], "unique_skills": sum(1 for r in rows if r.get("current_demand", 0) > 0),
            "growing": counts["growing"], "declining": counts["declining"], "at_risk": counts["at_risk"],
            "emerging": counts["emerging"], "stable": counts["stable"], "insufficient_data": counts["insufficient_data"]}
    return {
        "scope": "filtered" if filters.is_scoped else "global", "filters": filters.describe(), "kpis": kpis,
        "date_range": {"min": ov["date_min"], "max": ov["date_max"]},
        "postings_by_year": [{"year": y, "postings": n} for y, n in year_rows],
        "top_growing": _top(rows, "growth_rate", 8, True, {"growing", "emerging"}, 0.01),
        "top_declining": _top(rows, "growth_rate", 8, False, {"declining", "at_risk"}),
        "highest_risk": _top(rows, "obsolescence_score", 8, True),
        "emerging": _top(rows, "current_demand", 8, True, {"emerging"}),
        "market_outlook": market_outlook(rows, ov["total_jobs"], ov["date_min"], ov["date_max"]),
        "limitations": LIMITATIONS,
        "has_data": ov["total_jobs"] > 0, "has_predictions": any(r["trend_status"] != "insufficient_data" for r in rows),
    }


@router.get("/model-performance", summary="Forecast model comparison from rolling-origin validation")
def model_performance(db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(ModelMetric)).all()
    if not rows:
        return {"available": False, "message": "No forecast models have been trained yet. Run the pipeline."}
    skills = {s.id: s for s in db.scalars(select(Skill))}
    preds = {p.skill_id: p for p in db.scalars(select(Prediction))}
    by_model: dict[str, list[ModelMetric]] = defaultdict(list)
    per_skill: dict[int, dict[str, ModelMetric]] = defaultdict(dict)
    for r in rows:
        by_model[r.model_name].append(r)
        per_skill[r.skill_id][r.model_name] = r

    def mean(vals):
        v = [x for x in vals if x is not None and np.isfinite(x)]
        return float(np.mean(v)) if v else None

    def median(vals):
        v = [x for x in vals if x is not None and np.isfinite(x)]
        return float(np.median(v)) if v else None

    models = []
    for name, ms in by_model.items():
        rel = []
        for sid, d in per_skill.items():
            naive = d.get("naive_mean")
            if name in d and naive and naive.rmse and d[name].rmse is not None:
                rel.append(d[name].rmse / naive.rmse)
        models.append({"model": name, "skills_evaluated": len(ms), "times_selected": sum(1 for m in ms if m.selected),
                       "mean_mae": mean(m.mae for m in ms), "mean_rmse": mean(m.rmse for m in ms),
                       "mean_mape": mean(m.mape for m in ms), "median_r2": median(m.r2 for m in ms),
                       "rmse_vs_naive": mean(rel)})
    models.sort(key=lambda m: -m["times_selected"])
    selected = [m for m in rows if m.selected]
    table = []
    for m in sorted(selected, key=lambda m: -(preds[m.skill_id].current_demand if m.skill_id in preds else 0))[:60]:
        s = skills.get(m.skill_id)
        if s:
            table.append({"skill_id": s.id, "name": s.name, "model": m.model_name, "mae": m.mae, "rmse": m.rmse,
                          "mape": m.mape, "r2": m.r2, "folds": m.n_folds})
    bundle = load_latest_bundle()
    return {"available": True, "model_version": rows[0].model_version, "trained_at": (bundle or {}).get("trained_at"),
            "validation": {"method": "Rolling-origin (expanding window) cross-validation, never shuffled",
                           "horizon_quarters": 4, "step_quarters": 2, "max_folds": 6, "min_train_quarters": 8,
                           "metrics": ["MAE", "RMSE", "MAPE (actual share >= 1%)", "R2 on pooled out-of-sample predictions"],
                           "selection": "lowest mean RMSE; the simplest model within 2% of the best wins ties"},
            "models": models, "selected_summary": {"skills_with_forecast": len(selected),
                                                    "mean_rmse": mean(m.rmse for m in selected), "mean_mape": mean(m.mape for m in selected),
                                                    "mean_mae": mean(m.mae for m in selected), "median_r2": median(m.r2 for m in selected)},
            "per_skill": table}


@router.get("/categories", summary="Demand and trend summary per skill category")
def categories(filters: Filters = Depends(get_filters), db: Session = Depends(get_db)) -> dict:
    rows = rows_for(db, filters)
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r["category"]].append(r)
    conds = job_conditions(filters)
    share_rows = db.execute(
        select(JobPosting.year, Skill.category, func.count(func.distinct(JobSkill.job_id)))
        .select_from(JobSkill).join(JobPosting, JobPosting.id == JobSkill.job_id).join(Skill, Skill.id == JobSkill.skill_id)
        .where(*conds).group_by(JobPosting.year, Skill.category)).all()
    jobs_by_year = dict(db.execute(select(JobPosting.year, func.count()).where(*conds).group_by(JobPosting.year)).all())
    items = []
    for cat, rs in sorted(groups.items()):
        counts = defaultdict(int)
        for r in rs:
            counts[r["trend_status"]] += 1
        scored = [r["obsolescence_score"] for r in rs if r.get("obsolescence_score") is not None]
        share = [{"year": y, "share": n / jobs_by_year[y]} for y, c, n in sorted(share_rows) if c == cat and jobs_by_year.get(y)]
        best = _top(rs, "growth_rate", 1, True, {"growing", "emerging"}, 0.01)
        worst = _top(rs, "obsolescence_score", 1, True)
        items.append({"category": cat, "skills": len(rs), "status_counts": dict(counts),
                      "avg_obsolescence_score": float(np.mean(scored)) if scored else None,
                      "avg_current_demand": float(np.mean([r.get("current_demand", 0) for r in rs])),
                      "top_growing": best[0]["name"] if best else None,
                      "highest_risk": worst[0]["name"] if worst and (worst[0]["obsolescence_score"] or 0) >= 50 else None,
                      "postings_share_by_year": share})
    return {"items": items, "scope": "filtered" if filters.is_scoped else "global"}


@router.get("/filters", summary="Available filter values")
def filter_options(db: Session = Depends(get_db)) -> dict:
    conds = job_conditions(None)

    def values(col, exclude=()):
        return [{"value": v, "postings": int(n)} for v, n in db.execute(
            select(col, func.count()).where(*conds, col.is_not(None)).group_by(col).order_by(func.count().desc())).all()
            if v not in exclude]

    ov = dataset_overview(db, None)
    cats = [c for (c,) in db.execute(select(Skill.category).distinct().order_by(Skill.category))]
    role_counts = {r["value"]: r["postings"] for r in values(JobPosting.role)}
    return {"roles": [{"value": r, "postings": role_counts.get(r, 0)} for r in ROLES],
            "industries": values(JobPosting.industry), "countries": values(JobPosting.country),
            "regions": [r for r in values(JobPosting.region) if r["value"] in REGIONS],
            "years": [int(y) for (y,) in db.execute(select(JobPosting.year).where(*conds, JobPosting.year.is_not(None))
                                                    .distinct().order_by(JobPosting.year))],
            "categories": cats, "statuses": STATUSES, "risk_levels": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
            "date_min": ov["date_min"], "date_max": ov["date_max"]}


@router.get("/risk-map", summary="Scatter data: demand vs growth, bubble = obsolescence score")
def risk_map(filters: Filters = Depends(get_filters), db: Session = Depends(get_db)) -> dict:
    rows = [r for r in rows_for(db, filters) if r.get("obsolescence_score") is not None]
    return {"items": [{"skill_id": r["skill_id"], "name": r["name"], "category": r["category"],
                       "current_demand": r["current_demand"], "growth_rate": r["growth_rate"],
                       "yoy_growth": r.get("yoy_growth"), "obsolescence_score": r["obsolescence_score"],
                       "risk_level": r["risk_level"], "trend_status": r["trend_status"]} for r in rows],
            "scope": "filtered" if filters.is_scoped else "global"}


@router.get("/demand-by", summary="Skill demand matrix by industry, role, region or country (last 12 months)")
def demand_by(dimension: Literal["industry", "role", "region", "country"] = "industry",
              skill_ids: str | None = Query(None, description="Comma separated ids; default = top skills by demand"),
              top: int = Query(12, ge=3, le=30), db: Session = Depends(get_db)) -> dict:
    as_of = db.scalar(select(func.max(JobPosting.posted_date)).where(*job_conditions(None)))
    if as_of is None:
        return {"groups": [], "skills": [], "cells": [], "empty": True, "message": "No job postings available"}
    jobs, mentions = role_skill_shares(db, as_of - timedelta(days=365), as_of, dimension)
    groups = [g for g, n in sorted(jobs.items(), key=lambda kv: -kv[1]) if n >= 30]
    skills = {s.id: s for s in db.scalars(select(Skill))}
    if skill_ids:
        ids = [int(x) for x in skill_ids.split(",") if x.strip().isdigit()][:30]
    else:
        total = sum(jobs.values())
        agg: dict[int, int] = defaultdict(int)
        for (_, sid), n in mentions.items():
            agg[sid] += n
        ids = [sid for sid, _ in sorted(agg.items(), key=lambda kv: -kv[1])[:top]]
    cells = [{"group": g, "skill_id": sid, "skill": skills[sid].name, "share": mentions.get((g, sid), 0) / jobs[g]}
             for g in groups for sid in ids if sid in skills]
    return {"dimension": dimension, "groups": [{"group": g, "postings": jobs[g]} for g in groups],
            "skills": [{"skill_id": sid, "name": skills[sid].name} for sid in ids if sid in skills], "cells": cells,
            "as_of": as_of.isoformat(), "empty": not groups}


@router.get("/candidates", summary="Technology-looking phrases not yet in the taxonomy (for review)")
def candidates(min_mentions: int = Query(3, ge=1), limit: int = Query(30, ge=1, le=200), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(SkillCandidate).where(SkillCandidate.mentions >= min_mentions)
                      .order_by(SkillCandidate.mentions.desc()).limit(limit)).all()
    return {"items": [{"phrase": r.phrase, "mentions": r.mentions, "first_year": r.first_year, "last_year": r.last_year,
                       "suggested_name": r.suggested_name, "suggested_category": r.suggested_category,
                       "source": r.source} for r in rows],
            "note": "Add confirmed skills to data/skill_taxonomy.csv, then re-run extraction."}
