#!/usr/bin/env python
"""Initialise the database and load a populated dashboard.

    python scripts/seed_database.py            # migrate, load taxonomy + sample jobs, run the pipeline
    python scripts/seed_database.py --reset    # wipe postings/analytics first
    python scripts/seed_database.py --file path/to/jobs.csv

Steps: (1) create/upgrade tables with Alembic, (2) load the skill taxonomy, (3) import postings,
(4) clean + de-duplicate, (5) extract skills, (6) trends, (7) forecasts, (8) predictions.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.database import SessionLocal  # noqa: E402
from app.services.bootstrap import seed, upgrade_schema  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, default=None, help="CSV to import (default: data/sample/job_postings.csv)")
    ap.add_argument("--reset", action="store_true", help="delete existing postings and analytics first")
    ap.add_argument("--no-pipeline", action="store_true", help="import only; skip the analysis pipeline")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    upgrade_schema()
    with SessionLocal() as db:
        out = seed(db, args.file, reset=args.reset, run_pipeline=not args.no_pipeline)
    summary = out["pipeline"] or {}
    print(json.dumps({k: summary.get(k) for k in ("status", "jobs_processed", "skills_detected", "trends_calculated",
                                                   "predictions_generated", "duration_seconds")}, indent=2))


if __name__ == "__main__":
    main()
