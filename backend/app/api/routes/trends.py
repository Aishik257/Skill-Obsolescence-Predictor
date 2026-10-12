"""Trend endpoints: ranked growth/decline lists and multi-skill demand series."""
from __future__ import annotations

from typing import Literal

import numpy as np
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Pagination, get_filters, get_pagination, paginate
from app.core.database import get_db
from app.core.errors import NotFoundError, UnprocessableError
from app.models.skill import Skill
from app.api.routes.skills import filter_rows, sort_rows
from app.services.analysis_data import Filters, load_frequency_data
from app.services.views import rows_for

router = APIRouter(prefix="/trends", tags=["trends"])


def _ranked(db: Session, filters: Filters, statuses: set[str], sort: str, order: str, limit: int,
            min_demand: float, category: str | None) -> dict:
    rows = [r for r in rows_for(db, filters) if r["trend_status"] in statuses and r.get("current_demand", 0) >= min_demand]
    if category:
        rows = [r for r in rows if r["category"] == category]
    rows = sort_rows(rows, sort, order)[:limit]
    return {"items": rows, "total": len(rows), "scope": "filtered" if filters.is_scoped else "global",
            "filters": filters.describe()}


@router.get("", summary="All skills with trend metrics")
def trends(q: str | None = None, category: str | None = None, status: str | None = None,
           sort: str = "growth_rate", order: Literal["asc", "desc"] = "desc",
           filters: Filters = Depends(get_filters), p: Pagination = Depends(get_pagination),
           db: Session = Depends(get_db)) -> dict:
    rows = sort_rows(filter_rows(rows_for(db, filters), q, category, status, None), sort, order)
    out = paginate(rows, p)
    out["scope"] = "filtered" if filters.is_scoped else "global"
    return out


@router.get("/growing", summary="Fastest-growing skills (growing + emerging) by relative growth")
def growing(limit: int = Query(15, ge=1, le=100), min_demand: float = Query(0.01, ge=0, le=1),
            include_emerging: bool = True, category: str | None = None,
            filters: Filters = Depends(get_filters), db: Session = Depends(get_db)) -> dict:
    statuses = {"growing", "emerging"} if include_emerging else {"growing"}
    return _ranked(db, filters, statuses, "growth_rate", "desc", limit, min_demand, category)


@router.get("/declining", summary="Declining and at-risk skills by relative decline")
def declining(limit: int = Query(15, ge=1, le=100), min_demand: float = Query(0.0, ge=0, le=1),
              category: str | None = None, filters: Filters = Depends(get_filters), db: Session = Depends(get_db)) -> dict:
    return _ranked(db, filters, {"declining", "at_risk"}, "growth_rate", "asc", limit, min_demand, category)


@router.get("/emerging", summary="Emerging skills: low historical presence, rapid recent growth")
def emerging(limit: int = Query(15, ge=1, le=100), category: str | None = None,
             filters: Filters = Depends(get_filters), db: Session = Depends(get_db)) -> dict:
    return _ranked(db, filters, {"emerging"}, "yoy_growth", "desc", limit, 0.0, category)


@router.get("/series", summary="Demand over time for several skills (line chart data)")
def series(skill_ids: str = Query(..., description="Comma separated skill ids, max 10"),
           granularity: Literal["month", "quarter", "year"] = "quarter",
           filters: Filters = Depends(get_filters), db: Session = Depends(get_db)) -> dict:
    try:
        ids = list(dict.fromkeys(int(s) for s in skill_ids.split(",") if s.strip()))
    except ValueError as exc:
        raise UnprocessableError("skill_ids must be a comma separated list of integers.") from exc
    if not ids or len(ids) > 10:
        raise UnprocessableError("Provide between 1 and 10 skill ids.")
    skills = {s.id: s for s in db.scalars(select(Skill).where(Skill.id.in_(ids)))}
    missing = [i for i in ids if i not in skills]
    if missing:
        raise NotFoundError(f"Skill(s) do not exist: {missing}")
    data = load_frequency_data(db, filters, granularity, skill_ids=ids)
    if data.is_empty():
        return {"granularity": granularity, "periods": [], "jobs": [], "series": [], "empty": True,
                "message": "No job postings match these filters."}
    with np.errstate(divide="ignore", invalid="ignore"):
        out = []
        for i, sid in enumerate(ids):
            freq = np.where(data.jobs > 0, data.mentions[:, i] / data.jobs, np.nan)
            out.append({"skill_id": sid, "name": skills[sid].name, "category": skills[sid].category,
                        "frequency": [None if np.isnan(v) else float(v) for v in freq],
                        "mentions": [int(v) for v in data.mentions[:, i]]})
    return {"granularity": granularity, "periods": data.labels, "jobs": [int(j) for j in data.jobs],
            "series": out, "empty": False, "filters": filters.describe()}
