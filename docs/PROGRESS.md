# SkillPulse – Build Progress & VS Code Guide

Updated at the end of every working session. Open this file first when you resume.

## 1. How to open the project in VS Code

1. Unzip the archive so you get a single folder: `skill-obsolescence-predictor/`.
2. In VS Code: **File → Open Folder…** and choose that folder (the one containing `backend/`, `frontend/`, `data/`).
   Do **not** open `backend/` on its own – the scripts and config look for `data/` one level above it.
3. Recommended extensions: *Python*, *Pylance*, *ESLint*, *Tailwind CSS IntelliSense*, *Docker*.
4. Create the Python environment (VS Code terminal, repo root):
   ```bash
   python -m venv .venv
   source .venv/bin/activate            # Windows: .venv\Scripts\activate
   pip install -r backend/requirements.txt
   ```
   Then **Ctrl+Shift+P → "Python: Select Interpreter" → `.venv`**.
5. Copy `.env.example` to `.env` (repo root) and adjust `DATABASE_URL` if needed.

Tip: add a `.vscode/settings.json` containing
`{ "python.analysis.extraPaths": ["backend"], "python.testing.pytestArgs": ["backend/tests"], "python.testing.pytestEnabled": true }`
so imports such as `from app.core.config import settings` resolve.

## 2. Folder layout (what lives where)

```
skill-obsolescence-predictor/
├── backend/                     FastAPI service (run commands from here)
│   ├── app/
│   │   ├── main.py              app factory, CORS, error handlers      [session 2]
│   │   ├── core/                config.py, database.py, errors.py
│   │   ├── models/              SQLAlchemy tables (job, skill, job_skill, skill_trend, prediction…)
│   │   ├── schemas/             Pydantic response/request models        [session 2]
│   │   ├── api/routes/          jobs, skills, trends, forecasts, predictions, analytics, pipeline [session 2]
│   │   ├── services/            business logic: ingestion, cleaning, skill_extraction,
│   │   │                        semantic, normalization, analysis_data, trend_analysis,
│   │   │                        replacement, obsolescence, insights, recommendations, pipeline
│   │   ├── ml/                  feature_engineering.py, forecasting.py, train.py, predict.py
│   │   └── utils/               text.py, roles.py, geo.py
│   ├── alembic/                 migrations                              [session 2]
│   ├── tests/                   pytest suite                            [session 3]
│   ├── requirements.txt         core deps  (+ requirements-nlp.txt optional neural embeddings)
│   └── Dockerfile               [session 3]
├── frontend/                    React + TS + Vite + Tailwind + Recharts [session 3]
│   └── src/ api/ components/ pages/ hooks/ types/ utils/
├── data/
│   ├── skill_taxonomy.csv       176 skills, aliases, categories (single source of truth)
│   └── sample/                  job_postings.csv (10.6k rows), upload_demo.csv, ground-truth file
├── scripts/                     generate_sample_data.py, seed_database.py, ingest_data.py, train_models.py
├── notebooks/                   exploration + model evaluation
├── docs/PROGRESS.md             this file
├── docker-compose.yml           [session 3]
├── .env.example  .gitignore  README.md
```

## 3. Status (current)

| Area | State |
|------|-------|
| Config, DB layer, ORM models, Alembic migration | done |
| Skill taxonomy (176 skills) + sample data generator (10.6k postings) | done |
| Ingestion, validation, cleaning, near-duplicate detection | done |
| Skill extraction (dictionary, context rules, spaCy, fuzzy, TF-IDF semantic, optional LLM) | done (F1 0.98 vs ground truth) |
| Trends + classification, forecasting (4 models, rolling-origin CV), obsolescence score, replacement + co-occurrence, recommendations | done |
| Pipeline orchestration, 40 API endpoints, error handling | done |
| Backend tests | **122 passing** on SQLite and on PostgreSQL |
| Scripts: generate_sample_data, seed_database, ingest_data, train_models | done |
| Dockerfiles, docker-compose.yml, entrypoint, .env.example | written - not executable-verified; Docker CLI/daemon unavailable in this environment |
| Frontend scaffold: Vite/React/TS/Tailwind, API client, types, hooks, URL-based filters, layout, global search | done; `tsc` clean, `vite build` OK |
| Frontend pages: Dashboard, Skills, Predictions, Trends, Skill detail, Forecasts, Analytics, My skills, Job data, About | implemented; all routes opened in a browser against the local API |
| Frontend tests (Vitest) | 7 passing: dashboard loading/error/sparse-filter explanation, URL filters, search, skill detail, CSV validate/import |
| README | written |
| Notebooks | both written; all code cells executed against the sample data and running API |

## 4. Remaining steps to completion (in order)

1. **Docker verification** on a machine with Docker (`docker compose up --build`); Docker is not installed in the current environment.
2. Final pass: `pytest`, `npm test`, `npm run build`, end-to-end upload -> pipeline -> dashboard.

## 5. Running it locally (what works today)

```bash
createdb skillpulse                                   # PostgreSQL 16; default user/password postgres/postgres
cp .env.example .env
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
python scripts/seed_database.py                       # migrate + sample data + pipeline (~1 min)
cd backend && uvicorn app.main:app --reload           # API http://localhost:8000/api/docs
cd ../frontend && npm install && npm run dev          # UI  http://localhost:5173
cd backend && pytest -q                               # 122 tests (SQLite by default)
```

## 6. Notes
- Browser validation: all ten app routes loaded against the local API with no page errors. The dashboard displayed data after the pipeline.
- End-to-end upload check: the upload demo CSV reported 320 valid rows, 2 invalid rows and 9 duplicates; 320 rows imported, then the full pipeline completed successfully in 81.7 seconds (10,695 postings processed, 176 skills detected and 176 predictions generated).
- Final test/build check: backend 122 passed; frontend build passed; frontend Vitest 7 passed. Vite reports the existing >500 kB bundle-size advisory.
- Docker verification remains open because neither Docker CLI nor a Docker daemon is available in this environment.
- Regenerate sample data: `python scripts/generate_sample_data.py`.
