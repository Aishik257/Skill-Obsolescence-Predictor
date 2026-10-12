"""Filtered aggregation of job postings into period x skill frequency tables.

Everything analytic in SkillPulse starts here. Frequencies are always
``postings mentioning the skill / all postings in the same period`` under the same
filters - never raw counts - so growth in dataset size cannot masquerade as demand.
Duplicates (flagged by the cleaning stage) are always excluded.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.job import JobPosting
from app.models.job_skill import JobSkill

GRANULARITIES = ("month", "quarter", "year")


@dataclass(frozen=True)
class Filters:
    """Slice of the postings an analysis is computed over."""

    role: str | None = None
    industry: str | None = None
    country: str | None = None
    region: str | None = None
    city: str | None = None
    date_from: date | None = None
    date_to: date | None = None

    @property
    def is_scoped(self) -> bool:
        return any([self.role, self.industry, self.country, self.region, self.city, self.date_from, self.date_to])

    def describe(self) -> dict:
        return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in self.__dict__.items() if v}

    def cache_key(self) -> tuple:
        return tuple(sorted(self.describe().items()))


def job_conditions(f: Filters | None) -> list:
    """SQLAlchemy conditions selecting cleaned, non-duplicate postings that match the filters."""
    conds = [JobPosting.is_duplicate.is_(False), JobPosting.cleaned_at.is_not(None)]
    if f is None:
        return conds
    if f.role:
        conds.append(JobPosting.role == f.role)
    if f.industry:
        conds.append(JobPosting.industry == f.industry)
    if f.country:
        conds.append(JobPosting.country == f.country)
    if f.region:
        conds.append(JobPosting.region == f.region)
    if f.city:
        conds.append(JobPosting.city == f.city)
    if f.date_from:
        conds.append(JobPosting.posted_date >= f.date_from)
    if f.date_to:
        conds.append(JobPosting.posted_date <= f.date_to)
    return conds


def period_key(year: int, quarter: int, month: int, granularity: str) -> int:
    if granularity == "quarter":
        return year * 10 + quarter
    if granularity == "month":
        return year * 100 + month
    return year


def period_label(key: int, granularity: str) -> str:
    if granularity == "quarter":
        return f"{key // 10}-Q{key % 10}"
    if granularity == "month":
        return f"{key // 100}-{key % 100:02d}"
    return str(key)


def _period_columns(granularity: str):
    if granularity == "quarter":
        return [JobPosting.year, JobPosting.quarter]
    if granularity == "month":
        return [JobPosting.year, JobPosting.month]
    return [JobPosting.year]


def _full_range(first: int, last: int, granularity: str) -> list[int]:
    keys: list[int] = []
    if granularity == "year":
        return list(range(first, last + 1))
    if granularity == "quarter":
        y, q = divmod(first, 10)
        while y * 10 + q <= last:
            keys.append(y * 10 + q)
            q += 1
            if q > 4:
                y, q = y + 1, 1
        return keys
    y, m = divmod(first, 100)
    while y * 100 + m <= last:
        keys.append(y * 100 + m)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return keys


@dataclass
class FrequencyData:
    """Aggregated counts for one granularity: ``mentions[period, skill]`` and ``jobs[period]``."""

    granularity: str
    periods: list[int]
    jobs: np.ndarray  # shape (P,)
    skill_ids: list[int]
    mentions: np.ndarray  # shape (P, S)
    filters: Filters = field(default_factory=Filters)

    @property
    def labels(self) -> list[str]:
        return [period_label(p, self.granularity) for p in self.periods]

    @property
    def total_jobs(self) -> int:
        return int(self.jobs.sum())

    def is_empty(self) -> bool:
        return len(self.periods) == 0

    def usable_mask(self, min_jobs: int) -> np.ndarray:
        return self.jobs >= min_jobs

    def column(self, skill_id: int) -> np.ndarray:
        return self.mentions[:, self.skill_ids.index(skill_id)]

    def index_of(self, skill_id: int) -> int | None:
        try:
            return self.skill_ids.index(skill_id)
        except ValueError:
            return None


def load_frequency_data(db: Session, filters: Filters | None = None, granularity: str = "quarter",
                        skill_ids: list[int] | None = None) -> FrequencyData:
    """Aggregate postings and skill mentions per period for the given filters."""
    if granularity not in GRANULARITIES:
        raise ValueError(f"granularity must be one of {GRANULARITIES}")
    filters = filters or Filters()
    conds = job_conditions(filters)
    cols = _period_columns(granularity)

    job_rows = db.execute(select(*cols, func.count()).where(*conds).group_by(*cols)).all()
    if not job_rows:
        return FrequencyData(granularity, [], np.zeros(0), skill_ids or [], np.zeros((0, len(skill_ids or []))), filters)

    def key_of(row) -> int:
        if granularity == "quarter":
            return row[0] * 10 + row[1]
        if granularity == "month":
            return row[0] * 100 + row[1]
        return row[0]

    jobs_by_key = {key_of(r): r[-1] for r in job_rows}
    periods = _full_range(min(jobs_by_key), max(jobs_by_key), granularity)
    pos = {k: i for i, k in enumerate(periods)}
    jobs = np.array([jobs_by_key.get(k, 0) for k in periods], dtype=float)

    stmt = (
        select(*cols, JobSkill.skill_id, func.count())
        .select_from(JobSkill)
        .join(JobPosting, JobPosting.id == JobSkill.job_id)
        .where(*conds)
        .group_by(*cols, JobSkill.skill_id)
    )
    if skill_ids is not None:
        stmt = stmt.where(JobSkill.skill_id.in_(skill_ids))
    rows = db.execute(stmt).all()
    ids = sorted({r[-2] for r in rows}) if skill_ids is None else list(skill_ids)
    col_pos = {sid: i for i, sid in enumerate(ids)}
    mentions = np.zeros((len(periods), len(ids)))
    for r in rows:
        mentions[pos[key_of(r)], col_pos[r[-2]]] = r[-1]
    return FrequencyData(granularity, periods, jobs, ids, mentions, filters)


def frequency_frame(data: FrequencyData, skill_id: int) -> pd.DataFrame:
    """Per-period frame for one skill: jobs, mentions, frequency (NaN where no postings)."""
    idx = data.index_of(skill_id)
    mentions = data.mentions[:, idx] if idx is not None else np.zeros(len(data.periods))
    with np.errstate(divide="ignore", invalid="ignore"):
        freq = np.where(data.jobs > 0, mentions / data.jobs, np.nan)
    return pd.DataFrame({"period": data.labels, "key": data.periods, "jobs": data.jobs,
                         "mentions": mentions, "frequency": freq})


def dataset_overview(db: Session, filters: Filters | None = None) -> dict:
    """Counts used by KPI cards: postings, date range, duplicates."""
    conds = job_conditions(filters)
    total, dmin, dmax = db.execute(
        select(func.count(), func.min(JobPosting.posted_date), func.max(JobPosting.posted_date)).where(*conds)
    ).one()
    return {"total_jobs": int(total), "date_min": dmin.isoformat() if dmin else None,
            "date_max": dmax.isoformat() if dmax else None}


def role_share_table(db: Session, since: date | None = None, filters: Filters | None = None) -> dict[str, tuple[int, dict[int, float]]]:
    """Per role: (postings, {skill_id: share of that role's postings}) since a start date."""
    base = filters or Filters()
    f = Filters(**{**base.__dict__, "date_from": since or base.date_from})
    conds = job_conditions(f)
    jobs = dict(db.execute(select(JobPosting.role, func.count()).where(*conds).group_by(JobPosting.role)).all())
    rows = db.execute(
        select(JobPosting.role, JobSkill.skill_id, func.count())
        .select_from(JobSkill).join(JobPosting, JobPosting.id == JobSkill.job_id)
        .where(*conds).group_by(JobPosting.role, JobSkill.skill_id)
    ).all()
    out: dict[str, tuple[int, dict[int, float]]] = {r: (int(n), {}) for r, n in jobs.items() if r}
    for role, sid, cnt in rows:
        if role in out:
            out[role][1][sid] = cnt / out[role][0]
    return out


def trailing_year_start(data: FrequencyData, min_jobs: int) -> date | None:
    """First day of the oldest of the last four usable quarters."""
    keys = [p for p, j in zip(data.periods, data.jobs) if j >= min_jobs][-4:]
    if len(keys) < 1 or data.granularity != "quarter":
        return None
    year, q = divmod(keys[0], 10)
    return date(year, 3 * (q - 1) + 1, 1)


def role_skill_shares(db: Session, date_from: date | None, date_to: date | None,
                      dimension: str = "role") -> tuple[dict[str, int], dict[tuple[str, int], int]]:
    """Postings per group and mentions per (group, skill) in a date window.

    ``dimension`` is one of ``role``, ``industry``, ``region``, ``country``. Postings without a
    value for the dimension are excluded rather than guessed.
    """
    col = {"role": JobPosting.role, "industry": JobPosting.industry,
           "region": JobPosting.region, "country": JobPosting.country}[dimension]
    conds = job_conditions(Filters(date_from=date_from, date_to=date_to)) + [col.is_not(None)]
    if dimension == "role":
        conds.append(col != "Other")
    jobs = {g: int(n) for g, n in db.execute(select(col, func.count()).where(*conds).group_by(col)).all()}
    rows = db.execute(
        select(col, JobSkill.skill_id, func.count()).select_from(JobSkill)
        .join(JobPosting, JobPosting.id == JobSkill.job_id).where(*conds).group_by(col, JobSkill.skill_id)
    ).all()
    return jobs, {(g, sid): int(n) for g, sid, n in rows}
