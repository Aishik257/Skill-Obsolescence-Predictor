"""Skill demand and trend broken down by role, industry, region or country."""
from __future__ import annotations

from dataclasses import replace

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ml.feature_engineering import compute_metrics
from app.models.job import JobPosting
from app.services.analysis_data import Filters, job_conditions, load_frequency_data
from app.services.trend_analysis import STATUS_LABELS, classify_trend, scoped_min_jobs, usable_series
from app.utils.cache import analysis_cache
from app.utils.roles import ROLES

DIMENSIONS = {"role": JobPosting.role, "industry": JobPosting.industry, "region": JobPosting.region,
              "country": JobPosting.country}
MIN_GROUP_JOBS = 150


def relevance_label(share: float) -> str:
    if share >= 0.25:
        return "High relevance"
    if share >= 0.10:
        return "Moderate relevance"
    if share >= 0.03:
        return "Low relevance"
    return "Minimal relevance"


def growth_label(rel: float) -> str:
    if rel >= 1.0:
        return "Very strong growth"
    if rel >= 0.4:
        return "Strong growth"
    if rel >= 0.15:
        return "Moderate growth"
    if rel > -0.15:
        return "Stable"
    if rel > -0.4:
        return "Moderate decline"
    return "Strong decline"


def group_values(db: Session, dimension: str, base: Filters) -> list[tuple[str, int]]:
    """Distinct values of a dimension with posting counts (``Other`` role and empty values excluded)."""
    col = DIMENSIONS[dimension]
    conds = job_conditions(replace(base, **{dimension: None})) + [col.is_not(None)]
    rows = db.execute(select(col, func.count()).where(*conds).group_by(col).order_by(func.count().desc())).all()
    out = [(v, int(n)) for v, n in rows if not (dimension == "role" and v == "Other")]
    if dimension == "role":
        out.sort(key=lambda r: ROLES.index(r[0]) if r[0] in ROLES else 99)
    return out


def breakdown(db: Session, skill_id: int, dimension: str, base: Filters | None = None) -> dict:
    """Per-group relevance and trend of one skill. Groups with too little data are flagged, not guessed."""
    base = base or Filters()

    def build() -> dict:
        groups = []
        for value, n_jobs in group_values(db, dimension, base):
            if n_jobs < MIN_GROUP_JOBS:
                groups.append({"group": value, "jobs": n_jobs, "sufficient": False,
                               "note": f"Only {n_jobs} postings; at least {MIN_GROUP_JOBS} are needed"})
                continue
            f = replace(base, **{dimension: value})
            data = load_frequency_data(db, f, "quarter", skill_ids=[skill_id])
            labels, mentions, jobs = usable_series(data, 0, scoped_min_jobs(f))
            overall = float(data.mentions[:, 0].sum() / max(data.jobs.sum(), 1))
            row = {"group": value, "jobs": n_jobs, "mentions": int(data.mentions[:, 0].sum()), "overall_share": overall}
            m = compute_metrics(labels, mentions, jobs) if len(labels) else None
            if m is None:
                recent = float(mentions[-4:].sum() / max(jobs[-4:].sum(), 1)) if len(labels) else overall
                row.update(sufficient=bool(len(labels) >= 4), current_demand=recent, relevance=relevance_label(recent),
                           trend_status="insufficient_data", status_label=STATUS_LABELS["insufficient_data"],
                           growth_label="Insufficient data", note="Too little history or too few mentions for a trend")
            else:
                cls = classify_trend(m, None)
                row.update(sufficient=True, current_demand=m.current_demand, relevance=relevance_label(m.current_demand),
                           growth=m.long_term_growth, yoy_growth=m.yoy_growth, momentum=m.momentum,
                           pp_change=m.pp_change, trend_status=cls.status, status_label=STATUS_LABELS[cls.status],
                           growth_label=growth_label(m.long_term_growth), p_value=m.p_long)
            groups.append(row)
        return {"skill_id": skill_id, "dimension": dimension, "filters": base.describe(), "groups": groups}

    from app.services.views import data_version
    return analysis_cache.get_or_set(("breakdown", data_version(db), skill_id, dimension, base.cache_key()), build)
