"""Application configuration, loaded from environment variables / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> repository root is three levels above "core"
REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime settings. Every value can be overridden with an environment variable."""

    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), ".env"),
        extra="ignore",
        case_sensitive=True,
    )

    # --- infrastructure -------------------------------------------------
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/skillpulse"
    CORS_ORIGINS: str = "http://localhost:5173"
    MODEL_DIR: str = "./app/ml/models"
    MAX_UPLOAD_SIZE_MB: int = 20
    DATA_DIR: str = ""  # defaults to <repo>/data
    LOG_LEVEL: str = "INFO"

    # --- optional LLM enhancement (never required) ----------------------
    LLM_API_KEY: str = ""
    LLM_PROVIDER: str = ""  # "anthropic" or "openai"
    LLM_MODEL: str = ""

    # --- NLP ------------------------------------------------------------
    EMBEDDING_BACKEND: str = "auto"  # auto | tfidf | sentence-transformers
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    SEMANTIC_THRESHOLD_TFIDF: float = 0.36
    SEMANTIC_THRESHOLD_NEURAL: float = 0.58
    SEMANTIC_MARGIN: float = 0.05
    FUZZY_THRESHOLD: int = 90
    MIN_EXTRACTION_CONFIDENCE: float = 0.55

    # --- analytics ------------------------------------------------------
    MIN_JOBS_PER_PERIOD: int = 30  # quarters with fewer postings are ignored (global)
    MIN_JOBS_PER_PERIOD_SCOPED: int = 8  # same, for role/industry/location slices
    MIN_FORECAST_QUARTERS: int = 12
    MIN_FORECAST_MENTIONS: int = 40

    # --- bootstrap ------------------------------------------------------
    AUTO_SEED: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def data_dir(self) -> Path:
        return Path(self.DATA_DIR).resolve() if self.DATA_DIR else REPO_ROOT / "data"

    @property
    def taxonomy_path(self) -> Path:
        return self.data_dir / "skill_taxonomy.csv"

    @property
    def sample_data_path(self) -> Path:
        return self.data_dir / "sample" / "job_postings.csv"

    @property
    def model_dir(self) -> Path:
        path = Path(self.MODEL_DIR)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def llm_enabled(self) -> bool:
        return bool(self.LLM_API_KEY and self.LLM_PROVIDER)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
