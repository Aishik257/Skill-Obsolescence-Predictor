"""Prediction endpoints (stored obsolescence predictions)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Pagination, get_filters, get_pagination, paginate
from app.api.routes.skills import filter_rows, sort_rows
from app.core.database import get_db
from app.core.errors import NotFoundError
from app.models.prediction import Prediction
from app.services.analysis_data import Filters
from app.services.skill_detail import get_skill
from app.services.views import prediction_row, relations, rows_for

router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.get("", summary="Predictions for all skills")
def list_predictions(q: str | None = None, category: str | None = None, status: str | None = None,
                     risk: str | None = Query(None, description="Comma separated LOW,MEDIUM,HIGH,CRITICAL"),
                     sort: str = "obsolescence_score", order: Literal["asc", "desc"] = "desc",
                     filters: Filters = Depends(get_filters), p: Pagination = Depends(get_pagination),
                     db: Session = Depends(get_db)) -> dict:
    rows = [r for r in rows_for(db, filters) if r["trend_status"] != "insufficient_data"] if (status is None) else rows_for(db, filters)
    rows = sort_rows(filter_rows(rows, q, category, status, risk), sort, order)
    out = paginate(rows, p)
    out["scope"] = "filtered" if filters.is_scoped else "global"
    return out


@router.get("/high-risk", summary="Skills with HIGH or CRITICAL obsolescence risk")
def high_risk(limit: int = Query(20, ge=1, le=100), filters: Filters = Depends(get_filters),
              db: Session = Depends(get_db)) -> dict:
    rows = [r for r in rows_for(db, filters) if r.get("risk_level") in ("HIGH", "CRITICAL")]
    rows = sort_rows(rows, "obsolescence_score", "desc")[:limit]
    return {"items": rows, "total": len(rows), "scope": "filtered" if filters.is_scoped else "global"}


@router.get("/{skill_id}", summary="Full prediction for one skill with explanation")
def prediction_detail(skill_id: int, db: Session = Depends(get_db)) -> dict:
    skill = get_skill(db, skill_id)
    pred = db.scalar(select(Prediction).where(Prediction.skill_id == skill_id))
    if pred is None:
        raise NotFoundError(f"No prediction exists for '{skill.name}'. Run the pipeline, or the skill has no mentions yet.")
    return {**prediction_row(skill, pred), "components": pred.components, "metrics": pred.metrics,
            "explanation": pred.explanation, "replacements": relations(db, skill_id, "replacement", 5)}
