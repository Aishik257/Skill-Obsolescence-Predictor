"""Skill endpoints: list/search, detail, history, forecast, relations, breakdowns."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Pagination, get_filters, get_pagination, paginate
from app.core.database import get_db
from app.core.errors import UnprocessableError
from app.models.prediction import Prediction
from app.models.skill import Skill
from app.services import breakdown as breakdown_svc
from app.services.analysis_data import Filters
from app.services.skill_detail import forecast_view, get_skill, history_view
from app.services.views import metrics_row, prediction_row, relations, rows_for
from app.services.analysis_data import load_frequency_data
from app.services.trend_analysis import scoped_min_jobs, usable_series
from app.ml.feature_engineering import compute_metrics

router = APIRouter(prefix="/skills", tags=["skills"])

SORTABLE = {"name", "current_demand", "growth_rate", "yoy_growth", "momentum", "cagr", "obsolescence_score",
            "confidence", "category"}


def sort_rows(rows: list[dict], sort: str, order: str) -> list[dict]:
    if sort not in SORTABLE:
        raise UnprocessableError(f"Cannot sort by '{sort}'. Choose one of: {', '.join(sorted(SORTABLE))}.")
    reverse = order == "desc"
    present = [r for r in rows if r.get(sort) is not None]
    missing = [r for r in rows if r.get(sort) is None]
    present.sort(key=lambda r: (r[sort].lower() if isinstance(r[sort], str) else r[sort]), reverse=reverse)
    return present + missing


def filter_rows(rows: list[dict], q: str | None, category: str | None, status: str | None, risk: str | None) -> list[dict]:
    if q:
        needle = q.strip().lower()
        rows = [r for r in rows if needle in r["name"].lower() or any(needle in a.lower() for a in r.get("aliases", []))]
    if category:
        rows = [r for r in rows if r["category"] == category]
    if status:
        wanted = {s.strip() for s in status.split(",")}
        rows = [r for r in rows if r["trend_status"] in wanted]
    if risk:
        wanted = {s.strip().upper() for s in risk.split(",")}
        rows = [r for r in rows if r.get("risk_level") in wanted]
    return rows


@router.get("", summary="List skills with trend status, demand and risk")
def list_skills(q: str | None = Query(None, max_length=80), category: str | None = None,
                status: str | None = Query(None, description="Comma separated: growing,stable,declining,emerging,at_risk"),
                risk: str | None = Query(None, description="Comma separated: LOW,MEDIUM,HIGH,CRITICAL"),
                sort: str = "current_demand", order: Literal["asc", "desc"] = "desc",
                filters: Filters = Depends(get_filters), p: Pagination = Depends(get_pagination),
                db: Session = Depends(get_db)) -> dict:
    rows = sort_rows(filter_rows(rows_for(db, filters), q, category, status, risk), sort, order)
    out = paginate(rows, p)
    out["scope"] = "filtered" if filters.is_scoped else "global"
    out["filters"] = filters.describe()
    return out


@router.get("/search", summary="Global skill search (skills and role views)")
def search_skills(q: str = Query(..., min_length=1, max_length=80), limit: int = Query(8, ge=1, le=25),
                  db: Session = Depends(get_db)) -> dict:
    needle = q.strip().lower()
    skills = list(db.scalars(select(Skill)))
    preds = {p.skill_id: p for p in db.scalars(select(Prediction))}
    scored = []
    for s in skills:
        names = [s.name.lower()] + [a.lower() for a in (s.aliases or [])]
        if needle in names:
            score = 100
        elif any(n.startswith(needle) for n in names):
            score = 90
        elif any(needle in n for n in names):
            score = 75
        else:
            score = max(fuzz.WRatio(needle, n) for n in names)
            score = score if score >= 86 else 0
        if score:
            scored.append((score, s))
    scored.sort(key=lambda t: (-t[0], -(preds[t[1].id].current_demand if t[1].id in preds else 0)))
    top = scored[:limit]
    results = [prediction_row(s, preds.get(s.id)) | {"match_score": sc} for sc, s in top]
    role_views = []
    for sc, s in top[:3]:
        p = preds.get(s.id)
        for r in ((p.metrics or {}).get("top_roles", []) if p else []):
            role_views.append({"skill_id": s.id, "name": f"{s.name} for {r['role']}", "skill": s.name,
                               "role": r["role"], "share": r["share"]})
    return {"query": q, "results": results, "role_views": role_views[:6]}


@router.get("/{skill_id}", summary="Skill detail with prediction, explanation and relations")
def skill_detail(skill_id: int, filters: Filters = Depends(get_filters), db: Session = Depends(get_db)) -> dict:
    skill = get_skill(db, skill_id)
    pred = db.scalar(select(Prediction).where(Prediction.skill_id == skill_id))
    row = prediction_row(skill, pred)
    out = {**row, "description": skill.description, "explanation": pred.explanation if pred else None,
           "components": pred.components if pred else None, "metrics": pred.metrics if pred else None,
           "top_roles": ((pred.metrics or {}).get("top_roles", []) if pred else []),
           "related_skills": relations(db, skill_id, "cooccurrence", 8),
           "replacements": relations(db, skill_id, "replacement", 5)}
    if filters.is_scoped:
        data = load_frequency_data(db, filters, "quarter", skill_ids=[skill_id])
        labels, mentions, jobs = (usable_series(data, 0, scoped_min_jobs(filters)) if not data.is_empty() else ([], [], []))
        m = compute_metrics(labels, mentions, jobs) if len(labels) else None
        out["filtered"] = metrics_row(skill, m, filters.describe())
        out["filtered"]["metrics"] = m.as_dict() if m else None
    return out


@router.get("/{skill_id}/history", summary="Demand over time (share of postings)")
def skill_history(skill_id: int, granularity: Literal["month", "quarter", "year"] = "quarter",
                  filters: Filters = Depends(get_filters), db: Session = Depends(get_db)) -> dict:
    return history_view(db, get_skill(db, skill_id), filters, granularity)


@router.get("/{skill_id}/forecast", summary="Historical + forecast demand with prediction intervals")
def skill_forecast(skill_id: int, filters: Filters = Depends(get_filters), db: Session = Depends(get_db)) -> dict:
    return forecast_view(db, get_skill(db, skill_id), filters)


@router.get("/{skill_id}/related", summary="Skills that commonly appear with this one")
def related(skill_id: int, limit: int = Query(10, ge=1, le=30), db: Session = Depends(get_db)) -> dict:
    get_skill(db, skill_id)
    return {"skill_id": skill_id, "related": relations(db, skill_id, "cooccurrence", limit)}


@router.get("/{skill_id}/replacements", summary="Potential replacement technologies (hypotheses, not causation)")
def replacements(skill_id: int, limit: int = Query(5, ge=1, le=10), db: Session = Depends(get_db)) -> dict:
    get_skill(db, skill_id)
    return {"skill_id": skill_id, "replacements": relations(db, skill_id, "replacement", limit),
            "disclaimer": "These are potential market transitions inferred from correlation, overlap and similarity. "
                          "They do not establish direct causation."}


@router.get("/{skill_id}/breakdown", summary="Relevance and trend of this skill per role, industry, region or country")
def skill_breakdown(skill_id: int, dimension: Literal["role", "industry", "region", "country"] = "role",
                    filters: Filters = Depends(get_filters), db: Session = Depends(get_db)) -> dict:
    get_skill(db, skill_id)
    return breakdown_svc.breakdown(db, skill_id, dimension, filters)
