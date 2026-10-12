"""Inference helpers: load persisted bundles and forecast arbitrary (e.g. filtered) series."""
from __future__ import annotations

import joblib
import numpy as np

from app.core.config import settings
from app.ml.forecasting import ForecastResult, forecast_series


def load_latest_bundle() -> dict | None:
    """Return the most recently trained bundle, or ``None`` if training has not run yet."""
    path = settings.model_dir / "forecast_models_latest.joblib"
    return joblib.load(path) if path.exists() else None


def forecast_filtered_series(share: np.ndarray, jobs: np.ndarray, mentions: np.ndarray) -> ForecastResult:
    """Forecast a role/industry/region slice on demand with the same model-selection procedure."""
    return forecast_series(share, float(np.mean(jobs)) if len(jobs) else 0.0, float(np.sum(mentions)))
