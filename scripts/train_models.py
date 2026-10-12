#!/usr/bin/env python
"""Re-train the forecasting models and print the cross-validated model comparison.

    python scripts/train_models.py              # forecast + predict stages on the data already in the database
    python scripts/train_models.py --full       # re-run the whole pipeline (clean -> extract -> ... -> predict)

For every skill the four candidate models (naive mean, linear trend, damped Holt, ridge autoregression) are
back-tested with rolling-origin cross-validation; the best model per skill is stored with its MAE/RMSE/MAPE/R^2.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import ModelMetric  # noqa: E402
from app.services import pipeline  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full", action="store_true", help="re-run the entire pipeline instead of forecast + predict")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with SessionLocal() as db:
        if args.full:
            out = pipeline.run_sync(db, "run-all")
        else:
            pipeline.run_sync(db, "forecast")
            out = pipeline.run_sync(db, "predict")
        print(json.dumps({k: out.get(k) for k in ("status", "trends_calculated", "predictions_generated",
                                                  "duration_seconds")}, indent=2))
        chosen = Counter(db.scalars(select(ModelMetric.model_name).where(ModelMetric.selected.is_(True))))
        metrics = db.scalars(select(ModelMetric)).all()
        print(f"\n{len(metrics)} model-metric rows stored.")
        by_model: dict[str, list] = {}
        for m in metrics:
            by_model.setdefault(m.model_name, []).append(m)
        for name, rows in sorted(by_model.items()):
            rmse = [r.rmse for r in rows if r.rmse is not None]
            print(f"  {name:<14} back-tested={len(rows):<4} selected={chosen.get(name, 0):<4} "
                  f"mean RMSE={sum(rmse) / max(len(rmse), 1):.5f}")


if __name__ == "__main__":
    main()
