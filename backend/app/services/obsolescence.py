"""Explainable obsolescence score (0 = very safe / growing, 100 = very high market-demand risk).

The score is a weighted sum of six components, each mapped to a 0-1 *risk* value by a
documented piecewise-linear curve:

    historical decline          25%   long-term relative change of demand
    recent momentum             20%   annualised slope of the last six quarters
    forecasted decline          25%   forecast two-year change vs today
    current demand              10%   low share of postings = more fragile
    market persistence          10%   how far demand sits below its own peak
    emerging replacement risk   10%   strongest growing look-alike (replacement.py)

If no forecast exists the forecast component is dropped and the remaining weights are
re-normalised; confidence is reduced accordingly. This is a *market-demand* risk indicator,
not a statement about a technology's technical merit.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.ml.feature_engineering import TrendMetrics

WEIGHTS = {"historical_decline": 0.25, "recent_momentum": 0.20, "forecasted_decline": 0.25,
           "current_demand": 0.10, "market_persistence": 0.10, "replacement_risk": 0.10}

# (input value, risk 0..1) anchors; values between anchors are linearly interpolated
CURVES: dict[str, list[tuple[float, float]]] = {
    "historical_decline": [(-0.8, 1.0), (-0.4, 0.8), (0.0, 0.3), (0.3, 0.05), (0.6, 0.0)],
    "recent_momentum": [(-0.4, 1.0), (-0.15, 0.8), (0.0, 0.3), (0.15, 0.08), (0.4, 0.0)],
    "forecasted_decline": [(-0.5, 1.0), (-0.2, 0.8), (0.0, 0.3), (0.2, 0.08), (0.5, 0.0)],
    "current_demand": [(0.0, 1.0), (0.01, 0.9), (0.03, 0.7), (0.08, 0.45), (0.15, 0.2), (0.30, 0.05), (0.5, 0.0)],
}
REPLACEMENT_FLOOR, REPLACEMENT_SPAN = 0.45, 0.35
STABLE_SCORE_CAP = 49.0  # consistency guard: a "stable" skill is never rated HIGH or CRITICAL
RISK_BANDS = [(70.0, "CRITICAL"), (50.0, "HIGH"), (30.0, "MEDIUM"), (0.0, "LOW")]
SIGN_DEADBAND = 0.02

COMPONENT_LABELS = {
    "historical_decline": "Historical decline", "recent_momentum": "Recent momentum",
    "forecasted_decline": "Forecasted decline", "current_demand": "Current demand",
    "market_persistence": "Market persistence", "replacement_risk": "Emerging replacement risk",
}


def interp(x: float, anchors: list[tuple[float, float]]) -> float:
    xs, ys = zip(*anchors)
    return float(np.interp(x, xs, ys))


def risk_level(score: float) -> str:
    for threshold, name in RISK_BANDS:
        if score >= threshold:
            return name
    return "LOW"


@dataclass
class ScoreResult:
    score: float
    risk_level: str
    components: dict[str, dict]
    confidence: float
    confidence_label: str
    confidence_reasons: list[str]
    notes: list[str] = field(default_factory=list)


def _sign(x: float) -> int:
    return 0 if abs(x) < SIGN_DEADBAND else (1 if x > 0 else -1)


def confidence_for(m: TrendMetrics, forecast_change: float | None, forecast_mape: float | None,
                   has_forecast: bool) -> tuple[float, str, list[str]]:
    """Confidence in [0, 1] from data volume, statistical significance, forecast skill and signal agreement."""
    reasons: list[str] = []
    volume = float(np.clip(np.log10(max(m.total_mentions, 1)) / 3.0, 0, 1))
    if m.total_mentions < 100:
        reasons.append(f"Limited evidence: only {int(m.total_mentions)} postings mention this skill")
    significance = float(np.clip(-np.log10(max(m.kendall_p, 1e-12)) / 3.0, 0, 1))
    if m.kendall_p > 0.05:
        reasons.append(f"The trend is not statistically significant (Kendall p={m.kendall_p:.2f})")
    if not has_forecast:
        model_quality = 0.3
        reasons.append("No forecast available (insufficient history)")
    elif forecast_mape is None:
        model_quality = 0.5
    else:
        model_quality = float(np.clip(1 - forecast_mape / 0.5, 0, 1))
        if forecast_mape > 0.25:
            reasons.append(f"Forecast backtests are noisy (MAPE {forecast_mape * 100:.0f}%)")
    signals = [_sign(m.long_term_growth), _sign(m.momentum)] + ([_sign(forecast_change)] if forecast_change is not None else [])
    dominant = np.sign(sum(signals))
    agree = sum(1.0 if s == dominant and s != 0 else 0.5 if s == 0 else 0.0 for s in signals) / len(signals)
    if dominant != 0 and agree < 0.99:
        reasons.append("Long-term trend, momentum and forecast do not all point the same way")
    if m.n_quarters < 12:
        reasons.append(f"Limited history: {m.n_quarters} quarters")
    conf = float(np.clip(0.30 * volume + 0.25 * significance + 0.20 * model_quality + 0.25 * agree, 0.0, 1.0))
    label = "High" if conf >= 0.75 else "Medium" if conf >= 0.5 else "Low"
    if not reasons:
        reasons.append("Ample data, a significant trend and consistent signals")
    return conf, label, reasons


def score_skill(m: TrendMetrics, forecast_change_2y: float | None, replacement_top: float = 0.0,
                forecast_mape: float | None = None, status: str | None = None) -> ScoreResult:
    """Compute the 0-100 obsolescence score with a per-component breakdown.

    ``status`` is the trend classification. When it is "stable" the decline is either not
    statistically supported or contradicted by recent momentum, so the score is capped at
    ``STABLE_SCORE_CAP`` and the cap is reported in ``notes`` (never applied silently).
    """
    raw = {
        "historical_decline": m.long_term_growth,
        "recent_momentum": m.momentum,
        "forecasted_decline": forecast_change_2y,
        "current_demand": m.current_demand,
        "market_persistence": m.persistence,
        "replacement_risk": replacement_top,
    }
    risk = {
        "historical_decline": interp(m.long_term_growth, CURVES["historical_decline"]),
        "recent_momentum": interp(m.momentum, CURVES["recent_momentum"]),
        "forecasted_decline": None if forecast_change_2y is None else interp(forecast_change_2y, CURVES["forecasted_decline"]),
        "current_demand": interp(m.current_demand, CURVES["current_demand"]),
        "market_persistence": float(np.clip((1 - m.persistence) / 0.8, 0, 1)),
        "replacement_risk": float(np.clip((replacement_top - REPLACEMENT_FLOOR) / REPLACEMENT_SPAN, 0, 1)) if replacement_top else 0.0,
    }
    active = {k: w for k, w in WEIGHTS.items() if risk[k] is not None}
    total_w = sum(active.values())
    components: dict[str, dict] = {}
    score = 0.0
    for name, weight in WEIGHTS.items():
        if risk[name] is None:
            components[name] = {"label": COMPONENT_LABELS[name], "value": raw[name], "risk": None,
                                "weight": 0.0, "points": 0.0, "note": "unavailable - weight redistributed"}
            continue
        eff_w = weight / total_w
        points = 100 * eff_w * risk[name]
        score += points
        components[name] = {"label": COMPONENT_LABELS[name], "value": raw[name], "risk": float(risk[name]),
                            "weight": float(eff_w), "points": float(points)}
    score = float(np.clip(score, 0.0, 100.0))
    notes: list[str] = []
    if status == "stable" and score > STABLE_SCORE_CAP:
        notes.append(f"Raw score {score:.0f} capped at {STABLE_SCORE_CAP:.0f}: the trend status is Stable, meaning the "
                     "decline is not statistically supported or is contradicted by recent momentum.")
        score = STABLE_SCORE_CAP
    conf, label, reasons = confidence_for(m, forecast_change_2y, forecast_mape, forecast_change_2y is not None)
    return ScoreResult(round(score, 1), risk_level(score), components, round(conf, 3), label, reasons, notes)
