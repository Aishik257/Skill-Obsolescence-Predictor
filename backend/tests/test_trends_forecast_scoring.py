import numpy as np
import pytest

from app.ml.feature_engineering import compute_metrics, relative_change
from app.ml.forecasting import MODEL_ORDER, _fold_origins, forecast_series
from app.services.obsolescence import STABLE_SCORE_CAP, score_skill
from app.services.trend_analysis import classify_trend

LABELS = [f"{2019 + i // 4}-Q{i % 4 + 1}" for i in range(28)]
JOBS = np.full(28, 400.0)


def metrics_for(shares, jobs=JOBS):
    return compute_metrics(LABELS[:len(shares)], np.round(np.array(shares) * jobs[:len(shares)]), jobs[:len(shares)])


def series(a, b, noise=0.004, seed=0, n=28):
    rng = np.random.default_rng(seed)
    return np.clip(np.linspace(a, b, n) + rng.normal(0, noise, n), 0, 1)


# ---- trend calculation -----------------------------------------------------------------
def test_increasing_skill_metrics_and_status():
    m = metrics_for(series(0.10, 0.40))
    assert m.long_term_growth > 1.5 and m.yoy_growth > 0 and m.momentum > 0 and m.cagr > 0.1 and m.p_long < 0.001
    assert classify_trend(m, 0.1).status == "growing"


def test_decreasing_skill_metrics_and_status():
    m = metrics_for(series(0.30, 0.05))
    assert m.long_term_growth < -0.6 and m.momentum < 0 and m.persistence < 0.4
    assert classify_trend(m, -0.3).status == "at_risk"
    assert classify_trend(m, None).status in {"at_risk", "declining"}


def test_moderate_decline_is_declining_not_at_risk():
    assert classify_trend(metrics_for(series(0.30, 0.21)), -0.05).status == "declining"


def test_stable_skill():
    m = metrics_for(series(0.25, 0.25))
    assert abs(m.long_term_growth) < 0.15 and classify_trend(m, 0.0).status == "stable"


def test_emerging_skill_low_base_rapid_growth():
    shares = np.concatenate([np.zeros(14), np.linspace(0.01, 0.40, 14)])
    m = metrics_for(shares)
    assert m.first_demand < 0.02 and classify_trend(m, 0.3).status == "emerging"


def test_relative_frequency_not_raw_counts():
    """1,000 -> 2,000 mentions while postings double (10% -> 10%) must read as stable (spec section 36)."""
    jobs = np.linspace(1000, 2000, 28)
    m = compute_metrics(LABELS, np.round(jobs * 0.10), jobs)
    assert abs(m.long_term_growth) < 0.05 and classify_trend(m, 0.0).status == "stable"
    assert m.total_mentions > 3000  # raw counts did grow a lot


def test_tiny_changes_are_not_significant():
    m = metrics_for(series(0.10, 0.102, noise=0.01, seed=3))
    assert classify_trend(m, 0.0).status == "stable"


def test_too_little_history_or_mentions_is_insufficient():
    assert compute_metrics(LABELS[:6], np.ones(6) * 20, np.ones(6) * 100) is None
    assert compute_metrics(LABELS, np.zeros(28), JOBS) is None
    assert classify_trend(None).status == "insufficient_data"


def test_baseline_floor_prevents_infinite_growth():
    assert relative_change(0.004, 0.0) == pytest.approx(0.4)


# ---- forecasting -----------------------------------------------------------------------
def test_forecast_with_sufficient_data():
    y = series(0.10, 0.40, noise=0.005)
    r = forecast_series(y, 400, float(y.sum() * 400))
    assert r.status == "ok" and r.model_name in MODEL_ORDER
    p = r.path
    assert len(p.mean) == 12 and p.steps == list(range(1, 13))
    assert all(0 <= lo <= m <= hi <= 1 for lo, m, hi in zip(p.lower, p.mean, p.upper))
    assert p.mean[-1] > y[-4:].mean() * 0.95  # a rising series keeps rising (or at least does not collapse)
    assert (np.array(p.upper) - np.array(p.lower))[-1] >= (np.array(p.upper) - np.array(p.lower))[0]  # uncertainty widens
    assert all(0 < c < 1 for c in p.confidence)
    assert set(r.scores) == set(MODEL_ORDER)
    s = r.scores[r.model_name]
    assert s.n_folds >= 3 and s.mae is not None and s.rmse >= s.mae and s.mape is not None


def test_selected_model_beats_naive_on_trending_series():
    y = series(0.05, 0.50, noise=0.003)
    r = forecast_series(y, 400, 5000)
    assert r.baseline_rmse_ratio is not None and r.baseline_rmse_ratio <= 1.0
    assert r.model_name != "naive_mean"


def test_insufficient_history_returns_message_not_forecast():
    r = forecast_series(np.linspace(0.1, 0.2, 8), 400, 500)
    assert r.status == "insufficient_data" and "Insufficient historical data" in r.reason and r.path is None


def test_insufficient_mentions():
    r = forecast_series(np.full(28, 0.001), 400, 10)
    assert r.status == "insufficient_data" and "Insufficient historical data" in r.reason


def test_validation_folds_are_time_ordered_and_never_shuffled():
    origins = _fold_origins(28)
    assert origins == sorted(origins) and len(origins) >= 3
    assert all(8 <= o <= 24 for o in origins)  # train on >= 8 quarters, test window fully inside the series


def test_forecast_is_deterministic():
    y = series(0.1, 0.3, seed=5)
    a, b = forecast_series(y, 400, 3000), forecast_series(y, 400, 3000)
    assert a.model_name == b.model_name and a.path.mean == b.path.mean


# ---- obsolescence score ----------------------------------------------------------------
def test_high_decline_gives_high_score_and_growth_gives_low_score():
    dec = score_skill(metrics_for(series(0.30, 0.03)), -0.6, 0.8, 0.1, "at_risk")
    grow = score_skill(metrics_for(series(0.10, 0.45)), 0.4, 0.0, 0.1, "growing")
    assert dec.score >= 70 and dec.risk_level == "CRITICAL"
    assert grow.score <= 15 and grow.risk_level == "LOW"
    assert dec.score > grow.score + 55


def test_components_are_explainable_and_sum_to_score():
    r = score_skill(metrics_for(series(0.30, 0.10)), -0.2, 0.5, 0.15, "declining")
    assert set(r.components) == {"historical_decline", "recent_momentum", "forecasted_decline", "current_demand",
                                 "market_persistence", "replacement_risk"}
    assert sum(c["points"] for c in r.components.values()) == pytest.approx(r.score, abs=0.2)
    assert sum(c["weight"] for c in r.components.values()) == pytest.approx(1.0)
    assert r.confidence_reasons


def test_missing_forecast_redistributes_weight_and_lowers_confidence():
    m = metrics_for(series(0.30, 0.10))
    with_f = score_skill(m, -0.2, 0.0, 0.1, "declining")
    without = score_skill(m, None, 0.0, None, "declining")
    assert without.components["forecasted_decline"]["weight"] == 0
    assert sum(c["weight"] for c in without.components.values()) == pytest.approx(1.0)
    assert without.confidence < with_f.confidence


def test_stable_status_caps_score_and_reports_it():
    m = metrics_for(series(0.30, 0.04))
    raw = score_skill(m, -0.6, 0.9, 0.1, "declining")
    capped = score_skill(m, -0.6, 0.9, 0.1, "stable")
    assert raw.score > STABLE_SCORE_CAP and capped.score == STABLE_SCORE_CAP and capped.notes


def test_small_samples_get_low_confidence_with_reason():
    m = metrics_for(np.full(10, 0.05), jobs=np.full(10, 100.0))
    r = score_skill(m, None, 0.0, None, "stable")
    assert r.confidence_label in {"Low", "Medium"} and any("Limited" in x or "No forecast" in x for x in r.confidence_reasons)
