# SkillPulse - Skill Obsolescence Predictor

SkillPulse analyzes technology skills mentioned in job postings. It tracks relative demand over time, classifies market trends, forecasts future demand and explains an obsolescence-risk score. The dashboard also includes market breakdowns, skill-gap recommendations and CSV ingestion.

> **Interpretation:** job-posting trends are a proxy for market demand. A high obsolescence score does not mean a technology is technically obsolete, and forecasts are estimates rather than guarantees.

## Features

- FastAPI service with 40 REST endpoints and interactive API documentation.
- PostgreSQL persistence, Alembic migrations, taxonomy synchronization and repeatable sample-data scripts.
- CSV validation and import with duplicate detection and row-level error reports.
- Job-description cleaning, deduplication, skill extraction and taxonomy normalization.
- Trend analysis, four time-series forecasting candidates with rolling-origin validation, and explainable risk scores.
- React, TypeScript and Vite single-page app with URL-based filters, global skill search, charts and responsive navigation.
- Background pipeline execution with progress polling.
- Backend pytest suite (122 tests, reported passing on SQLite and PostgreSQL) and frontend Vitest tests.

## Technology

| Area | Stack |
| --- | --- |
| API | Python 3.12+, FastAPI, Pydantic, SQLAlchemy, Alembic |
| Storage | PostgreSQL 16+ |
| Analysis | pandas, NumPy, SciPy, scikit-learn, statsmodels, spaCy, RapidFuzz |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Recharts |
| Tests | pytest, Vitest, Testing Library |
| Containers | Docker Compose, PostgreSQL, nginx |

## Repository layout

```text
backend/                 FastAPI application, migrations and tests
  app/api/routes/        jobs, skills, trends, forecasts, predictions,
                         analytics, pipeline and recommendations
  app/ml/                feature engineering, forecasting and prediction
  app/services/          ingestion, extraction, analysis and pipeline logic
frontend/                React application
  src/api/               API client and endpoint functions
  src/components/        shared layout, charts, tables and UI
  src/pages/             dashboard and analysis pages
data/
  skill_taxonomy.csv     normalized skill names, aliases and categories
  sample/                sample job postings and upload demonstration CSV
scripts/                 sample generation, seeding, ingestion and training
notebooks/               data exploration and model evaluation notebooks
docs/PROGRESS.md         implementation status and local setup notes
docker-compose.yml       PostgreSQL + API + nginx frontend
```

## Requirements

- Python 3.12 or newer
- Node.js 20 or newer and npm
- PostgreSQL 16 or newer for a local database, or Docker Desktop with Compose
- The repository root must be opened as the VS Code workspace. The backend resolves `data/` relative to this root.

## Local setup

### 1. Configure PostgreSQL and environment

Create a PostgreSQL database named `skillpulse`. With PostgreSQL command-line tools available:

```powershell
createdb skillpulse
```

Copy `.env.example` to `.env` in the repository root. For a local PostgreSQL server using the example credentials, set:

```dotenv
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/skillpulse
```

Change the connection string if your local PostgreSQL user, password, host or database differs. Never commit real credentials.

### 2. Install backend dependencies and populate sample data

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
python scripts/seed_database.py
```

The seed script applies migrations, synchronizes the skill taxonomy, imports the included sample postings and runs the analysis pipeline. The first run can take about a minute. To load postings without running analysis, use `python scripts/seed_database.py --no-pipeline`.

To execute the notebooks in VS Code, install their kernel and plotting dependencies as well:

```powershell
python -m pip install -r notebooks/requirements.txt
```

### 3. Start the API

In a terminal with the environment activated:

```powershell
Set-Location backend
python -m uvicorn app.main:app --reload
```

The API is available at <http://localhost:8000>; Swagger UI is at <http://localhost:8000/api/docs> and ReDoc is at <http://localhost:8000/api/redoc>.

### 4. Start the frontend

In a second terminal from the repository root:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` requests to `http://localhost:8000`. If the API runs elsewhere, set `VITE_PROXY_TARGET` before starting Vite.

## CSV format

CSV uploads require these columns:

| Column | Required | Description |
| --- | --- | --- |
| `job_id` | Yes | Stable source identifier for a posting |
| `title` | Yes | Job title |
| `description` | Yes | Posting text used for skill extraction |
| `posted_date` | Yes | Date accepted by the ingestion date parser |
| `company` | No | Employer |
| `location` | No | Free-text location |
| `industry` | No | Industry label |
| `employment_type` | No | Employment type |
| `source` | No | Source label |

Rows missing a usable description are not imported. The upload page validates the selected CSV first; review the report before choosing to import its valid rows. After an import, run the full pipeline to refresh trends and forecasts.

Example CSV: [`data/sample/upload_demo.csv`](./data/sample/upload_demo.csv).

## Using the application

1. Start from the Dashboard to see dataset coverage, market outlook and top trend/risk groups.
2. Use the URL-backed role, industry, country and year filters to scope supported analysis pages.
3. Search skills globally or open a skill detail page for demand history, forecasts, score explanation and breakdowns.
4. Compare forecast summaries and model backtests under Forecasts; use Analytics for risk, category and market-segment views.
5. Enter a target role and current skills under My skills for skill-gap and learning-path recommendations.
6. Use Job data to upload a CSV, inspect its validation report and start the monitored full pipeline.

The three limitations shown in the application are intentional:

- Job-posting trends are a proxy for market demand and do not perfectly represent the entire technology labor market.
- A declining mention rate does not necessarily mean that a technology is technically obsolete.
- Predictions are estimates based on historical data and should not be interpreted as guaranteed future outcomes.

## Obsolescence score

The score is a weighted sum of normalized component risks. Each component is mapped onto a 0-1 risk scale before its weight is applied.

| Component | Weight | Signal |
| --- | ---: | --- |
| Historical decline | 25% | Long-term relative change in demand |
| Recent momentum | 20% | Annualized slope over recent quarters |
| Forecasted decline | 25% | Projected two-year demand change |
| Current demand | 10% | Low demand contributes more risk |
| Market persistence | 10% | Demand relative to the skill's historical peak |
| Emerging replacement risk | 10% | Related growing skills that may indicate market transition |

When a forecast component is unavailable, the remaining weights are re-normalized and confidence is reduced. Stable skills are capped below the high-risk band. The score is a market-demand indicator, not a measure of technical merit.

Forecast model selection uses expanding-window rolling-origin cross-validation; time-series observations are not shuffled. The four candidates are a naive mean, linear trend, damped Holt and ridge autoregression. The selected model minimizes mean validation RMSE, with a preference for a simpler model within the configured tie margin.

## API overview

The API has 40 endpoints under `/api`:

| Route group | Purpose |
| --- | --- |
| `/jobs` | List and inspect postings, report dataset statistics, validate/import CSV |
| `/skills` | Skill catalogue, search, detail, history, forecasts and market breakdowns |
| `/trends` | Ranked growing/declining/emerging skills and multi-skill time series |
| `/forecasts` | Paginated forecast summaries and per-skill forecast detail |
| `/predictions` | Obsolescence scores and high-risk skills |
| `/analytics` | Overview, filters, model performance, categories, risk map, demand matrix and candidates |
| `/pipeline` | Run a pipeline stage or full run and poll progress/history |
| `/recommendations` | Skill gap and learning path |

For exact request/response schemas, use Swagger at `/api/docs`.

## Scripts

Run scripts from the repository root with the configured virtual environment activated:

```powershell
python scripts/generate_sample_data.py
python scripts/seed_database.py
python scripts/seed_database.py --reset
python scripts/ingest_data.py data/sample/upload_demo.csv --dry-run
python scripts/ingest_data.py data/sample/upload_demo.csv
python scripts/train_models.py
python scripts/train_models.py --full
```

`--reset` deletes existing postings and derived analytics before reseeding. Use it only when you intend to replace the current dataset.

## Tests and production build

Backend tests default to an isolated, temporary SQLite database:

```powershell
python -m pytest -q backend/tests
```

To run the same backend suite against PostgreSQL, point `TEST_DATABASE_URL` at a **disposable test database**. The test fixtures clear tables:

```powershell
$env:TEST_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/skillpulse_test"
python -m pytest -q backend/tests
Remove-Item Env:TEST_DATABASE_URL
```

Frontend type-check, production build and tests:

```powershell
Set-Location frontend
npm ci
npm run typecheck
npm test
npm run build
```

## Docker Compose

Docker Compose starts PostgreSQL, the API and the nginx-served frontend:

```powershell
Copy-Item .env.example .env
# Set AUTO_SEED=true in .env if the sample data should be loaded on first startup.
docker compose up --build
```

Open <http://localhost:5173> for the UI and <http://localhost:8000/api/docs> for API docs. Compose persists PostgreSQL data in the `pgdata` volume and model artifacts in the `models` volume. To stop the services, run `docker compose down`; adding `-v` also removes persisted data.

## Configuration

Settings are read from environment variables and the repository-root `.env` file. Common settings:

| Setting | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Local PostgreSQL `skillpulse` | SQLAlchemy database connection |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed browser origins |
| `MAX_UPLOAD_SIZE_MB` | `20` | API upload size limit |
| `MODEL_DIR` | `./app/ml/models` | Forecast-model artifact directory |
| `AUTO_SEED` | `false` in local settings | Seed an empty database during API startup |
| `EMBEDDING_BACKEND` | `auto` | Skill extraction semantic backend selection |
| `LLM_API_KEY`, `LLM_PROVIDER`, `LLM_MODEL` | Empty | Optional LLM enhancement; the application runs without it |

See [`.env.example`](./.env.example) and [`docs/PROGRESS.md`](./docs/PROGRESS.md) for the full configuration and current project status.
