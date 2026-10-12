"""Forecast endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Pagination, get_filters, get_pagination, paginate
from app.core.database import get_db
from app.models.prediction import Forecast, Prediction
from app.models.skill import Skill
from app.services.analysis_data import Filters
from app.services.skill_detail import forecast_view, get_skill

router = APIRouter(prefix="/forecasts", tags=["forecasts"])


@router.get("", summary="Forecast summary (1, 2 and 3 years) for every skill")
def list_forecasts(q: str | None = None, category: str | None = None,
                   model: str | None = Query(None, description="naive_mean, linear_trend, damped_holt, ar_ridge"),
                   sort: str = "change_2y", order: str = "desc", p: Pagination = Depends(get_pagination),
                   db: Session = Depends(get_db)) -> dict:
    skills = {s.id: s for s in db.scalars(select(Skill))}
    preds = {x.skill_id: x for x in db.scalars(select(Prediction))}
    points: dict[int, dict[int, Forecast]] = {}
    for f in db.scalars(select(Forecast).where(Forecast.step.in_([4, 8, 12]))):
        points.setdefault(f.skill_id, {})[f.step] = f
    rows = []
    for sid, pred in preds.items():
        s = skills.get(sid)
        if not s:
            continue
        pts = points.get(sid)
        row = {"skill_id": sid, "name": s.name, "category": s.category, "current_demand": pred.current_demand,
               "trend_status": pred.trend_status, "risk_level": pred.risk_level}
        if pts and len(pts) == 3:
            cur = max(pred.current_demand, 0.01)
            row.update(status="ok", model=pts[4].model_name,
                       y1=pts[4].predicted_demand, y2=pts[8].predicted_demand, y3=pts[12].predicted_demand,
                       change_1y=(pts[4].predicted_demand - pred.current_demand) / cur,
                       change_2y=(pts[8].predicted_demand - pred.current_demand) / cur,
                       change_3y=(pts[12].predicted_demand - pred.current_demand) / cur,
                       confidence_2y=pts[8].confidence, lower_2y=pts[8].lower_bound, upper_2y=pts[8].upper_bound)
        else:
            row.update(status="insufficient_data", message="Insufficient historical data")
        rows.append(row)
    if q:
        rows = [r for r in rows if q.lower() in r["name"].lower()]
    if category:
        rows = [r for r in rows if r["category"] == category]
    if model:
        rows = [r for r in rows if r.get("model") == model]
    key = sort if sort in {"change_1y", "change_2y", "change_3y", "current_demand", "y2", "name", "confidence_2y"} else "change_2y"
    present = sorted([r for r in rows if r.get(key) is not None], key=lambda r: r[key], reverse=order == "desc")
    return paginate(present + [r for r in rows if r.get(key) is None], p)


@router.get("/{skill_id}", summary="Forecast for one skill: history, path, intervals, model comparison")
def get_forecast(skill_id: int, filters: Filters = Depends(get_filters), db: Session = Depends(get_db)) -> dict:
    return forecast_view(db, get_skill(db, skill_id), filters)
