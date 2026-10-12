"""Trend features computed from a quarterly demand series.

All demand values are *shares of postings* (mentions / postings in the same period).
Relative changes use a baseline floor (``BASELINE_FLOOR``) so that a skill moving from
0.0% to 0.4% is not reported as "+infinity %": tiny absolute movements stay small.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats

BASELINE_FLOOR = 0.01  # shares below 1% of postings are treated as 1% when forming ratios
WINDOW = 4  # quarters per comparison window (one year)
MOMENTUM_QUARTERS = 6
MIN_QUARTERS_FOR_METRICS = 8
MIN_TOTAL_MENTIONS = 20


def wilson_interval(successes: float, n: float, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion."""
    if n <= 0:
        return 0.0, 0.0
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def two_proportion_pvalue(x1: float, n1: float, x2: float, n2: float) -> float:
    """Two-sided p-value of a pooled two-proportion z-test (1.0 when undefined)."""
    if n1 <= 0 or n2 <= 0:
        return 1.0
    p1, p2 = x1 / n1, x2 / n2
    pooled = (x1 + x2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = (p2 - p1) / se
    return float(2 * (1 - stats.norm.cdf(abs(z))))


def relative_change(new: float, old: float, floor: float = BASELINE_FLOOR) -> float:
    """(new - old) / max(old, floor)."""
    return (new - old) / max(old, floor)


@dataclass
class TrendMetrics:
    """Everything the classifier, scorer and explanation engine need about one skill."""

    n_quarters: int
    total_mentions: float
    total_jobs: float
    first_period: str
    last_period: str
    first_seen: str | None
    window_first: str
    window_last: str
    first_demand: float
    prev_demand: float
    current_demand: float
    current_ci: tuple[float, float]
    peak_demand: float
    peak_period: str
    pp_change: float  # current - first, in share points (0.05 = 5 pp)
    long_term_growth: float  # relative change first-year -> trailing year (floored baseline)
    yoy_growth: float  # trailing year vs the year before
    cagr: float
    momentum: float  # annualised relative slope of the last six quarters
    persistence: float  # current / peak rolling-year demand
    p_long: float
    p_recent: float
    kendall_tau: float
    kendall_p: float
    years_span: float

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["current_ci"] = list(self.current_ci)
        return {k: (None if isinstance(v, float) and (math.isnan(v) or math.isinf(v)) else v) for k, v in d.items()}


def rolling_share(mentions: np.ndarray, jobs: np.ndarray, window: int = WINDOW) -> np.ndarray:
    """Pooled share over a trailing window (NaN until the window is full)."""
    out = np.full(len(mentions), np.nan)
    for i in range(window - 1, len(mentions)):
        j = jobs[i - window + 1:i + 1].sum()
        out[i] = mentions[i - window + 1:i + 1].sum() / j if j > 0 else np.nan
    return out


def moving_average(freq: np.ndarray, window: int = WINDOW) -> np.ndarray:
    """Trailing simple moving average (partial windows at the start)."""
    out = np.full(len(freq), np.nan)
    for i in range(len(freq)):
        chunk = freq[max(0, i - window + 1):i + 1]
        chunk = chunk[~np.isnan(chunk)]
        if len(chunk):
            out[i] = chunk.mean()
    return out


def compute_metrics(labels: list[str], mentions: np.ndarray, jobs: np.ndarray) -> TrendMetrics | None:
    """Compute trend metrics for one skill from usable quarters (oldest first).

    Returns ``None`` when there is too little history or too few mentions to say anything.
    """
    n = len(labels)
    if n < MIN_QUARTERS_FOR_METRICS or mentions.sum() < MIN_TOTAL_MENTIONS:
        return None
    freq = mentions / jobs

    def pooled(sl: slice) -> tuple[float, float, float]:
        m, j = float(mentions[sl].sum()), float(jobs[sl].sum())
        return (m / j if j else 0.0), m, j

    first, m_first, j_first = pooled(slice(0, WINDOW))
    cur, m_cur, j_cur = pooled(slice(n - WINDOW, n))
    prev, m_prev, j_prev = pooled(slice(n - 2 * WINDOW, n - WINDOW))

    years_span = (n - WINDOW) / 4.0
    long_term = relative_change(cur, first)
    yoy = relative_change(cur, prev)
    cur_f, first_f = max(cur, BASELINE_FLOOR), max(first, BASELINE_FLOOR)
    cagr = (cur_f / first_f) ** (1 / years_span) - 1 if years_span > 0 else 0.0

    k = min(MOMENTUM_QUARTERS, n)
    tail = freq[-k:]
    slope = float(np.polyfit(np.arange(k), tail, 1)[0]) if k >= 3 else 0.0
    momentum = float(np.clip(slope * 4 / max(float(tail.mean()), BASELINE_FLOOR), -1.0, 3.0))

    roll = rolling_share(mentions, jobs)
    peak_idx = int(np.nanargmax(roll))
    peak = float(roll[peak_idx])
    persistence = cur / peak if peak > 0 else 1.0

    nz = np.nonzero(mentions)[0]
    first_seen = labels[int(nz[0])] if len(nz) else None
    tau, tau_p = stats.kendalltau(np.arange(n), freq)
    tau = 0.0 if np.isnan(tau) else float(tau)
    tau_p = 1.0 if np.isnan(tau_p) else float(tau_p)

    return TrendMetrics(
        n_quarters=n, total_mentions=float(mentions.sum()), total_jobs=float(jobs.sum()),
        first_period=labels[0], last_period=labels[-1], first_seen=first_seen,
        window_first=f"{labels[0]} to {labels[WINDOW - 1]}", window_last=f"{labels[n - WINDOW]} to {labels[-1]}",
        first_demand=first, prev_demand=prev, current_demand=cur, current_ci=wilson_interval(m_cur, j_cur),
        peak_demand=peak, peak_period=labels[peak_idx], pp_change=cur - first,
        long_term_growth=float(long_term), yoy_growth=float(yoy), cagr=float(cagr), momentum=float(momentum),
        persistence=float(min(1.0, persistence)),
        p_long=two_proportion_pvalue(m_first, j_first, m_cur, j_cur),
        p_recent=two_proportion_pvalue(m_prev, j_prev, m_cur, j_cur),
        kendall_tau=tau, kendall_p=tau_p, years_span=years_span,
    )


def lag_matrix(y: np.ndarray, lags: int) -> tuple[np.ndarray, np.ndarray]:
    """Autoregressive design matrix: rows [y[t-1..t-lags], t] -> target y[t]."""
    rows, targets = [], []
    for t in range(lags, len(y)):
        rows.append(list(y[t - lags:t][::-1]) + [t])
        targets.append(y[t])
    return np.array(rows, dtype=float), np.array(targets, dtype=float)
