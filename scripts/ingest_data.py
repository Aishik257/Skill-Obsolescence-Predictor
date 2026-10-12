#!/usr/bin/env python
"""Import a job-postings CSV and (optionally) run the analysis pipeline on it.

    python scripts/ingest_data.py data/sample/upload_demo.csv            # import + run everything
    python scripts/ingest_data.py my_jobs.csv --dry-run                  # validate only, write nothing
    python scripts/ingest_data.py my_jobs.csv --no-pipeline              # import only

Uses exactly the same validation and cleaning code as the web upload (backend/app/services/ingestion.py).
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
from app.services import pipeline  # noqa: E402
from app.services.bootstrap import upgrade_schema  # noqa: E402
from app.services.ingestion import ingest_csv  # noqa: E402
from app.services.normalization import sync_taxonomy  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", type=Path, help="CSV file with job postings")
    ap.add_argument("--dry-run", action="store_true", help="validate and report; do not import")
    ap.add_argument("--no-pipeline", action="store_true", help="import only; do not run the analysis pipeline")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not args.csv.exists():
        sys.exit(f"File not found: {args.csv}")
    upgrade_schema()
    with SessionLocal() as db:
        sync_taxonomy(db)
        report = ingest_csv(db, args.csv.read_bytes(), args.csv.name, dry_run=args.dry_run)
        print(json.dumps(report.as_dict(), indent=2, default=str))
        if not args.dry_run and not args.no_pipeline and report.imported:
            out = pipeline.run_sync(db, "run-all")
            print(json.dumps({k: out.get(k) for k in ("status", "jobs_processed", "skills_detected", "trends_calculated",
                                                      "predictions_generated", "duration_seconds")}, indent=2))


if __name__ == "__main__":
    main()
