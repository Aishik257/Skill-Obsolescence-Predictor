"""Train (select + fit) forecasting models for every skill and persist a reproducible bundle."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np

from app.core.config import settings
from app.ml.forecasting import ForecastResult, forecast_series
from app.services.analysis_data import FrequencyData

logger = logging.getLogger(__name__)
BASE_VERSION = "1.0"


def series_for(data: FrequencyData, idx: int, min_jobs: int) -> tuple[list[int], np.ndarray, np.ndarray, np.ndarray]:
    """Usable quarters of one skill: (period keys, share, mentions, jobs)."""
    mask = data.jobs >= min_jobs
    keys = [k for k, ok in zip(data.periods, mask) if ok]
    jobs, mentions = data.jobs[mask], data.mentions[mask, idx]
    return keys, mentions / jobs, mentions, jobs


def data_version(data: FrequencyData) -> str:
    """Model version = base version + short hash of the training data (reproducibility)."""
    h = hashlib.sha1(data.mentions.tobytes() + data.jobs.tobytes()).hexdigest()[:8]
    return f"{BASE_VERSION}+{h}"


def train_all(data: FrequencyData, min_jobs: int | None = None) -> tuple[dict[int, tuple[list[int], ForecastResult]], str]:
    """Run model selection and forecasting for every skill. Returns ``{skill_id: (period_keys, result)}``."""
    min_jobs = settings.MIN_JOBS_PER_PERIOD if min_jobs is None else min_jobs
    version = data_version(data)
    results: dict[int, tuple[list[int], ForecastResult]] = {}
    for idx, sid in enumerate(data.skill_ids):
        keys, share, mentions, jobs = series_for(data, idx, min_jobs)
        if len(keys) == 0:
            continue
        results[sid] = (keys, forecast_series(share, float(jobs.mean()), float(mentions.sum())))
    ok = sum(1 for _, r in results.values() if r.status == "ok")
    logger.info("Trained forecasts: %d ok, %d insufficient data (version %s)", ok, len(results) - ok, version)
    return results, version


def save_bundle(results: dict[int, tuple[list[int], ForecastResult]], version: str) -> Path:
    """Persist selected models, CV metrics and forecast paths with joblib."""
    payload = {
        "version": version,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "skills": {
            sid: {"status": r.status, "reason": r.reason, "model": r.model_name,
                  "scores": {k: v.as_dict() for k, v in r.scores.items()},
                  "path": r.path.__dict__ if r.path else None, "last_period": keys[-1] if keys else None}
            for sid, (keys, r) in results.items()
        },
    }
    path = settings.model_dir / f"forecast_models_{version}.joblib"
    joblib.dump(payload, path)
    joblib.dump(payload, settings.model_dir / "forecast_models_latest.joblib")
    return path
