"""Time-series demand forecasting with honest model selection.

Candidates (all univariate, on quarterly demand shares):

* ``naive_mean``   - mean of the last four quarters, held flat (the baseline to beat)
* ``linear_trend`` - OLS line through the last 16 quarters, extrapolated
* ``damped_holt``  - Holt exponential smoothing with a damped additive trend (statsmodels)
* ``ar_ridge``     - ridge regression on four lagged quarters + time, forecast recursively

The best model per skill is chosen by **rolling-origin (expanding-window) cross-validation**:
each fold trains on all quarters before an origin and predicts the following four quarters.
Data are never shuffled. Reported metrics are MAE, RMSE, MAPE and R^2 on the pooled
out-of-sample predictions. Prediction intervals come from the selected model's own
out-of-sample errors at each horizon (floored by binomial sampling noise).

Series that are too short or too sparse return ``status="insufficient_data"`` instead of a
misleading forecast.
"""
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from app.core.config import settings
from app.ml.feature_engineering import lag_matrix

logger = logging.getLogger(__name__)

HORIZON = 12  # quarters forecast (three years)
CV_HORIZON = 4
CV_STEP = 2
MAX_FOLDS = 8
MIN_TRAIN = 8
MODEL_ORDER = ["naive_mean", "linear_trend", "damped_holt", "ar_ridge"]
Z95 = 1.96
MAPE_MIN_ACTUAL = 0.01  # MAPE ignores actual shares below 1% (division by ~0)


# ----------------------------------------------------------------------------- models
def _naive_mean(y: np.ndarray, h: int) -> np.ndarray:
    return np.full(h, float(np.mean(y[-4:])))


def _linear_trend(y: np.ndarray, h: int) -> np.ndarray:
    tail = y[-16:]
    x = np.arange(len(tail))
    slope, intercept = np.polyfit(x, tail, 1)
    return intercept + slope * (len(tail) - 1 + np.arange(1, h + 1))


def _damped_holt(y: np.ndarray, h: int) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = ExponentialSmoothing(y, trend="add", damped_trend=True, initialization_method="estimated").fit()
        return np.asarray(fit.forecast(h), dtype=float)


def _ar_ridge(y: np.ndarray, h: int, lags: int = 4) -> np.ndarray:
    X, t = lag_matrix(y, lags)
    model = Ridge(alpha=1e-2, random_state=0).fit(X, t)
    hist = list(y)
    out = []
    for _ in range(h):
        feats = list(hist[-lags:][::-1]) + [len(hist)]
        nxt = float(model.predict(np.array([feats]))[0])
        out.append(nxt)
        hist.append(nxt)
    return np.array(out)


_MODELS = {"naive_mean": _naive_mean, "linear_trend": _linear_trend, "damped_holt": _damped_holt, "ar_ridge": _ar_ridge}


def predict_with(name: str, y: np.ndarray, h: int) -> np.ndarray:
    """Forecast ``h`` steps with a named model; falls back to the naive mean if fitting fails."""
    try:
        pred = _MODELS[name](np.asarray(y, dtype=float), h)
        if not np.all(np.isfinite(pred)):
            raise ValueError("non-finite forecast")
    except Exception as exc:  # noqa: BLE001 - one bad fit must not abort a whole run
        logger.debug("Model %s failed (%s); using naive mean for this fit", name, exc)
        pred = _naive_mean(np.asarray(y, dtype=float), h)
    return np.clip(pred, 0.0, 1.0)


# ----------------------------------------------------------------------------- evaluation
@dataclass
class ModelScore:
    name: str
    mae: float | None
    rmse: float | None
    mape: float | None
    r2: float | None
    n_folds: int
    step_rmse: list[float] = field(default_factory=list)  # RMSE by forecast step 1..CV_HORIZON

    def as_dict(self) -> dict:
        return {"name": self.name, "mae": self.mae, "rmse": self.rmse, "mape": self.mape, "r2": self.r2,
                "n_folds": self.n_folds}


def _fold_origins(n: int) -> list[int]:
    origins = list(range(n - CV_HORIZON, MIN_TRAIN - 1, -CV_STEP))[:MAX_FOLDS]
    return sorted(origins)


def evaluate_model(name: str, y: np.ndarray) -> ModelScore:
    """Rolling-origin cross-validation of one model."""
    actual, pred, steps = [], [], []
    for origin in _fold_origins(len(y)):
        test = y[origin:origin + CV_HORIZON]
        fc = predict_with(name, y[:origin], len(test))
        actual.extend(test)
        pred.extend(fc)
        steps.extend(range(len(test)))
    if not actual:
        return ModelScore(name, None, None, None, None, 0)
    a, p, s = np.array(actual), np.array(pred), np.array(steps)
    err = p - a
    mask = a >= MAPE_MIN_ACTUAL
    mape = float(np.mean(np.abs(err[mask] / a[mask]))) if mask.any() else None
    r2 = float(r2_score(a, p)) if len(a) > 1 and np.var(a) > 0 else None
    step_rmse = [float(np.sqrt(np.mean(err[s == k] ** 2))) if (s == k).any() else float("nan") for k in range(CV_HORIZON)]
    return ModelScore(name, float(np.mean(np.abs(err))), float(np.sqrt(np.mean(err ** 2))), mape, r2,
                      len(_fold_origins(len(y))), step_rmse)


# ----------------------------------------------------------------------------- public API
@dataclass
class ForecastPath:
    steps: list[int]
    mean: list[float]
    lower: list[float]
    upper: list[float]
    confidence: list[float]


@dataclass
class ForecastResult:
    status: str  # "ok" | "insufficient_data"
    reason: str | None = None
    model_name: str | None = None
    scores: dict[str, ModelScore] = field(default_factory=dict)
    path: ForecastPath | None = None
    baseline_rmse_ratio: float | None = None  # selected RMSE / naive RMSE (<1 means better than naive)


def insufficient(reason: str) -> ForecastResult:
    return ForecastResult(status="insufficient_data", reason=reason)


def forecast_series(y: np.ndarray, mean_jobs: float, total_mentions: float, horizon: int = HORIZON) -> ForecastResult:
    """Select the best model by time-series CV and forecast ``horizon`` quarters.

    ``y`` is the quarterly demand share (oldest first); ``mean_jobs`` is the typical number of
    postings per quarter (used for the sampling-noise floor of the intervals).
    """
    y = np.asarray(y, dtype=float)
    if len(y) < settings.MIN_FORECAST_QUARTERS:
        return insufficient(f"Insufficient historical data: {len(y)} usable quarters, "
                            f"at least {settings.MIN_FORECAST_QUARTERS} are required.")
    if total_mentions < settings.MIN_FORECAST_MENTIONS:
        return insufficient(f"Insufficient historical data: only {int(total_mentions)} mentions, "
                            f"at least {settings.MIN_FORECAST_MENTIONS} are required.")
    if not np.all(np.isfinite(y)):
        return insufficient("Insufficient historical data: the series has gaps.")

    scores = {name: evaluate_model(name, y) for name in MODEL_ORDER}
    valid = {k: v for k, v in scores.items() if v.rmse is not None}
    if not valid:
        return insufficient("Insufficient historical data: not enough history for validation folds.")
    best_rmse = min(v.rmse for v in valid.values())
    # lowest cross-validated RMSE wins; exact ties go to the simpler model (MODEL_ORDER)
    chosen = next(n for n in MODEL_ORDER if n in valid and valid[n].rmse <= best_rmse + 1e-12)
    sel = valid[chosen]

    mean = predict_with(chosen, y, horizon)
    base = valid.get("naive_mean")
    p_last = float(np.clip(np.mean(y[-4:]), 1e-6, 1 - 1e-6))
    sampling_se = float(np.sqrt(p_last * (1 - p_last) / max(mean_jobs, 1.0)))
    sig = []
    for h in range(1, horizon + 1):
        if h <= CV_HORIZON and np.isfinite(sel.step_rmse[h - 1]):
            s = sel.step_rmse[h - 1]
        else:
            last = sel.step_rmse[CV_HORIZON - 1] if np.isfinite(sel.step_rmse[-1]) else sel.rmse
            s = last * np.sqrt(h / CV_HORIZON)
        sig.append(max(s, sampling_se))
    sig_a = np.array(sig)
    lower = np.clip(mean - Z95 * sig_a, 0.0, 1.0)
    upper = np.clip(mean + Z95 * sig_a, 0.0, 1.0)
    rel_width = (upper - lower) / (mean + 0.05)
    conf = np.clip(1.0 - rel_width, 0.05, 0.99)
    path = ForecastPath(list(range(1, horizon + 1)), mean.tolist(), lower.tolist(), upper.tolist(), conf.tolist())
    ratio = sel.rmse / base.rmse if base and base.rmse else None
    return ForecastResult("ok", None, chosen, scores, path, ratio)


def next_quarters(last_key: int, n: int) -> list[tuple[int, int]]:
    """The ``n`` (year, quarter) pairs following a quarter key such as 20263."""
    y, q = divmod(last_key, 10)
    out = []
    for _ in range(n):
        q += 1
        if q > 4:
            y, q = y + 1, 1
        out.append((y, q))
    return out
