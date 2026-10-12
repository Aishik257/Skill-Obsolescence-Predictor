"""Trend classification and persistence of monthly aggregates.

Classification is a transparent rule cascade over the metrics from
``ml.feature_engineering``. Every rule returns the numbers it looked at, so the dashboard
can show *why* a skill carries its label.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ml.feature_engineering import BASELINE_FLOOR, TrendMetrics, compute_metrics
from app.models.skill_trend import SkillTrend
from app.services.analysis_data import FrequencyData, Filters, load_frequency_data

logger = logging.getLogger(__name__)

# --- thresholds (documented in the README) ------------------------------------------------
GROW_REL = 0.15            # long-term relative growth needed for "growing"
DECLINE_REL = -0.20        # long-term relative decline needed for "declining"
MOMENTUM_EPS = 0.02        # |momentum| below this counts as flat
ALPHA = 0.05               # significance level for long-term change
EMERGE_BASE = 0.02         # first-year share below this = "low historical presence"
EMERGE_CURRENT_MIN = 0.02  # must have reached a meaningful share
EMERGE_REL = 1.0           # at least doubled
EMERGE_YOY = 0.15          # and still growing quickly
EMERGE_ALPHA = 0.01
ATRISK_REL = -0.40         # strong long-term decline
ATRISK_FORECAST = -0.20    # forecast two-year change vs today
ATRISK_MOMENTUM_FALLBACK = -0.15  # used when no forecast is available
COLLAPSE_REL = -0.60       # a decline this deep with no forecast recovery also counts as at risk
NO_RECOVERY = 0.05         # forecast change at or below this means "no recovery"

STATUSES = ["growing", "stable", "declining", "emerging", "at_risk", "insufficient_data"]
STATUS_LABELS = {"growing": "Growing", "stable": "Stable", "declining": "Declining", "emerging": "Emerging",
                 "at_risk": "At Risk", "insufficient_data": "Insufficient data"}


@dataclass
class Classification:
    status: str
    rules: list[dict]

    def as_dict(self) -> dict:
        return {"status": self.status, "rules": self.rules}


def _rule(name: str, passed: bool, detail: str) -> dict:
    return {"rule": name, "passed": bool(passed), "detail": detail}


def classify_trend(m: TrendMetrics | None, forecast_change_2y: float | None = None) -> Classification:
    """Assign a trend status and return the rule trace that led to it.

    ``forecast_change_2y`` is the forecast two-year relative change vs current demand, or
    ``None`` when no forecast exists (then at-risk falls back to recent momentum).
    """
    if m is None:
        return Classification("insufficient_data", [_rule("history", False, "too little history or too few mentions")])
    pct = lambda x: f"{x * 100:+.1f}%"  # noqa: E731
    rules: list[dict] = []

    significant_long = m.p_long < ALPHA
    # A recent uptick only blocks a "declining" label when it is statistically real; on shares of a
    # few percent, quarter-to-quarter noise would otherwise hide a long-term collapse.
    rebound = m.yoy_growth > MOMENTUM_EPS and m.p_recent < ALPHA
    recent_positive = m.momentum > MOMENTUM_EPS or (m.momentum > -MOMENTUM_EPS and m.yoy_growth > 0)
    declining = m.long_term_growth <= DECLINE_REL and significant_long and not rebound
    growing = m.long_term_growth >= GROW_REL and significant_long and recent_positive

    emerging = (
        m.first_demand < EMERGE_BASE and m.current_demand >= EMERGE_CURRENT_MIN
        and m.long_term_growth >= EMERGE_REL and m.yoy_growth >= EMERGE_YOY and m.p_long < EMERGE_ALPHA
    )
    rules.append(_rule(
        "emerging", emerging,
        f"first-year share {m.first_demand * 100:.1f}% (<{EMERGE_BASE * 100:.0f}%), current {m.current_demand * 100:.1f}%, "
        f"long-term {pct(m.long_term_growth)} (>= {pct(EMERGE_REL)}), YoY {pct(m.yoy_growth)} (>= {pct(EMERGE_YOY)}), p={m.p_long:.3g}"))
    if emerging:
        return Classification("emerging", rules)

    if forecast_change_2y is not None:
        # forecast predicts a further decline, or - for skills that already collapsed - no recovery
        forecast_bad = forecast_change_2y <= ATRISK_FORECAST or (
            m.long_term_growth <= COLLAPSE_REL and forecast_change_2y <= NO_RECOVERY)
        fdetail = (f"forecast 2-year change {pct(forecast_change_2y)} (<= {pct(ATRISK_FORECAST)}, or "
                   f"<= {pct(NO_RECOVERY)} after a {pct(COLLAPSE_REL)} collapse)")
    else:
        forecast_bad = m.momentum <= ATRISK_MOMENTUM_FALLBACK
        fdetail = f"no forecast; momentum {pct(m.momentum)} (<= {pct(ATRISK_MOMENTUM_FALLBACK)})"
    at_risk = declining and m.long_term_growth <= ATRISK_REL and forecast_bad
    rules.append(_rule("at_risk", at_risk,
                       f"long-term {pct(m.long_term_growth)} (<= {pct(ATRISK_REL)}), declining={declining}, {fdetail}"))
    if at_risk:
        return Classification("at_risk", rules)

    rules.append(_rule("declining", declining,
                       f"long-term {pct(m.long_term_growth)} (<= {pct(DECLINE_REL)}), p={m.p_long:.3g}; no significant recent rebound (YoY {pct(m.yoy_growth)}, p={m.p_recent:.2g})"))
    if declining:
        return Classification("declining", rules)

    rules.append(_rule("growing", growing,
                       f"long-term {pct(m.long_term_growth)} (>= {pct(GROW_REL)}), momentum {pct(m.momentum)} / YoY {pct(m.yoy_growth)} (rising or holding), p={m.p_long:.3g}"))
    if growing:
        return Classification("growing", rules)

    rules.append(_rule("stable", True, "no rule for growth, decline or emergence was satisfied"))
    return Classification("stable", rules)


# --------------------------------------------------------------------------- series helpers
def usable_series(data: FrequencyData, idx: int, min_jobs: int) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Quarterly (labels, mentions, jobs) for one skill column, keeping only well-populated quarters."""
    mask = data.jobs >= min_jobs
    labels = [lab for lab, ok in zip(data.labels, mask) if ok]
    return labels, data.mentions[mask, idx], data.jobs[mask]


def compute_all_metrics(data: FrequencyData, min_jobs: int | None = None) -> dict[int, TrendMetrics | None]:
    """Trend metrics for every skill column of a quarterly FrequencyData."""
    min_jobs = settings.MIN_JOBS_PER_PERIOD if min_jobs is None else min_jobs
    out: dict[int, TrendMetrics | None] = {}
    for idx, sid in enumerate(data.skill_ids):
        labels, mentions, jobs = usable_series(data, idx, min_jobs)
        out[sid] = compute_metrics(labels, mentions, jobs)
    return out


def scoped_min_jobs(filters: Filters | None) -> int:
    return settings.MIN_JOBS_PER_PERIOD_SCOPED if filters and filters.is_scoped else settings.MIN_JOBS_PER_PERIOD


def compute_scoped_trends(db: Session, filters: Filters | None = None) -> tuple[FrequencyData, dict[int, TrendMetrics | None]]:
    """Quarterly metrics for every skill under the given filters (used when filters are active)."""
    data = load_frequency_data(db, filters, "quarter")
    return data, compute_all_metrics(data, scoped_min_jobs(filters))


# --------------------------------------------------------------------------- persistence
def persist_monthly_trends(db: Session) -> int:
    """Rebuild the ``skill_trends`` table (global monthly aggregates with YoY growth)."""
    data = load_frequency_data(db, None, "month")
    db.execute(delete(SkillTrend))
    if data.is_empty():
        db.commit()
        return 0
    rows: list[dict] = []
    pos = {p: i for i, p in enumerate(data.periods)}
    for idx, sid in enumerate(data.skill_ids):
        for p, i in pos.items():
            jobs, ments = float(data.jobs[i]), float(data.mentions[i, idx])
            if jobs <= 0:
                continue
            freq = ments / jobs
            prior = pos.get(p - 100)
            growth = None
            if prior is not None and data.jobs[prior] > 0:
                pf = data.mentions[prior, idx] / data.jobs[prior]
                growth = float((freq - pf) / max(pf, 0.01))
            rows.append({"skill_id": sid, "year": p // 100, "month": p % 100, "job_count": int(jobs),
                         "skill_mentions": int(ments), "skill_frequency": float(freq), "growth_rate": growth})
    for i in range(0, len(rows), 5000):
        db.bulk_insert_mappings(SkillTrend, rows[i:i + 5000])
    db.commit()
    logger.info("Stored %d monthly skill trend rows", len(rows))
    return len(rows)
