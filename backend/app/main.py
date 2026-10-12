"""SkillPulse API entry point."""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import analytics, forecasts, jobs, pipeline, predictions, recommendations, skills, trends
from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.core.errors import AppError
from app.services import pipeline as pipeline_svc

logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("skillpulse")


def _auto_seed() -> None:
    """Seed the sample data set on first start when AUTO_SEED=true and the database is empty."""
    from app.services.bootstrap import database_is_empty, seed
    try:
        with SessionLocal() as db:
            if database_is_empty(db):
                logger.info("AUTO_SEED: database is empty, loading the sample data set (about a minute)...")
                seed(db)
                logger.info("AUTO_SEED: finished")
    except Exception:  # noqa: BLE001 - never block API start-up
        logger.exception("AUTO_SEED failed; the API stays up, run scripts/seed_database.py manually")


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        with SessionLocal() as db:
            pipeline_svc.stale_runs_cleanup(db)
    except Exception:  # noqa: BLE001 - tables may not exist yet when running tests
        logger.warning("Could not check for interrupted pipeline runs", exc_info=True)
    if settings.AUTO_SEED:
        threading.Thread(target=_auto_seed, name="auto-seed", daemon=True).start()
    yield


app = FastAPI(
    title="SkillPulse - Skill Obsolescence Predictor API",
    description="Data-backed trends, forecasts and obsolescence risk for technology skills, computed from job postings. "
                "Job-posting trends are a proxy for market demand; predictions are estimates, not guarantees.",
    version="1.0.0", docs_url="/api/docs", redoc_url="/api/redoc", openapi_url="/api/openapi.json", lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False,
                   allow_methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "Accept"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "status": exc.status_code, **exc.details})


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    problems = [f"{'.'.join(str(p) for p in e['loc'] if p not in ('query', 'body', 'path'))}: {e['msg']}" for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": "Invalid request: " + "; ".join(problems), "status": 422,
                                                   "errors": jsonable(exc.errors())})


def jsonable(errors: list[dict]) -> list[dict]:
    return [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in errors]


@app.exception_handler(StarletteHTTPException)
async def http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc.detail), "status": exc.status_code})


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error. The failure was logged.", "status": 500})


@app.get("/api/health", tags=["system"], summary="Liveness and database connectivity")
def health() -> dict:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected", "llm_enabled": settings.llm_enabled}
    except Exception as exc:  # noqa: BLE001
        logger.error("Health check failed: %s", exc)
        return JSONResponse(status_code=503, content={"status": "degraded", "database": "unreachable"})


for module in (jobs, skills, trends, forecasts, predictions, analytics, pipeline, recommendations):
    app.include_router(module.router, prefix="/api")
