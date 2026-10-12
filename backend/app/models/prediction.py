"""Predictions, forecasts, model metrics, skill relations and pipeline bookkeeping."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.skill import JSONType


class Prediction(Base):
    """Latest obsolescence prediction for a skill (one row per skill, replaced each run)."""

    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), unique=True)
    prediction_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    current_demand: Mapped[float] = mapped_column(Float)  # share of postings, trailing 12 months
    growth_rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # long-term relative change
    momentum: Mapped[float | None] = mapped_column(Float, nullable=True)
    cagr: Mapped[float | None] = mapped_column(Float, nullable=True)
    yoy_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    future_demand: Mapped[float | None] = mapped_column(Float, nullable=True)  # forecast at horizon
    forecast_horizon: Mapped[int] = mapped_column(Integer, default=1)  # years ahead for future_demand
    forecast_status: Mapped[str] = mapped_column(String(30), default="ok")  # ok | insufficient_data

    trend_status: Mapped[str] = mapped_column(String(20), index=True)
    obsolescence_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    risk_level: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_label: Mapped[str | None] = mapped_column(String(10), nullable=True)

    model_version: Mapped[str] = mapped_column(String(40))
    forecast_model: Mapped[str | None] = mapped_column(String(40), nullable=True)
    components: Mapped[dict | None] = mapped_column(JSONType, nullable=True)  # score breakdown
    metrics: Mapped[dict | None] = mapped_column(JSONType, nullable=True)  # raw trend metrics
    explanation: Mapped[dict | None] = mapped_column(JSONType, nullable=True)


class Forecast(Base):
    """Quarterly forecast path (12 quarters ahead) for a skill, from the selected model."""

    __tablename__ = "forecasts"
    __table_args__ = (UniqueConstraint("skill_id", "step", name="uq_forecast_step"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True)
    step: Mapped[int] = mapped_column(Integer)  # 1..12 quarters ahead
    period_year: Mapped[int] = mapped_column(Integer)
    period_quarter: Mapped[int] = mapped_column(Integer)
    predicted_demand: Mapped[float] = mapped_column(Float)
    lower_bound: Mapped[float] = mapped_column(Float)
    upper_bound: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    model_name: Mapped[str] = mapped_column(String(40))
    model_version: Mapped[str] = mapped_column(String(40))


class ModelMetric(Base):
    """Rolling-origin cross-validation metrics per skill and candidate model."""

    __tablename__ = "model_metrics"
    __table_args__ = (UniqueConstraint("skill_id", "model_name", name="uq_metric_skill_model"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True)
    model_name: Mapped[str] = mapped_column(String(40), index=True)
    mae: Mapped[float | None] = mapped_column(Float, nullable=True)
    rmse: Mapped[float | None] = mapped_column(Float, nullable=True)
    mape: Mapped[float | None] = mapped_column(Float, nullable=True)
    r2: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_folds: Mapped[int] = mapped_column(Integer, default=0)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    model_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SkillRelation(Base):
    """Related-skill (co-occurrence) and potential-replacement relationships."""

    __tablename__ = "skill_relations"
    __table_args__ = (UniqueConstraint("skill_id", "related_skill_id", "kind", name="uq_relation"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True)
    related_skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20), index=True)  # cooccurrence | replacement
    score: Mapped[float] = mapped_column(Float)
    details: Mapped[dict | None] = mapped_column(JSONType, nullable=True)


class SkillCandidate(Base):
    """Technology-looking phrases found in postings that are not in the taxonomy."""

    __tablename__ = "skill_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phrase: Mapped[str] = mapped_column(String(200), unique=True)
    mentions: Mapped[int] = mapped_column(Integer)
    first_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suggested_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    suggested_category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="rule")  # rule | llm
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PipelineRun(Base):
    """Execution record for the analysis pipeline (powers progress polling)."""

    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), default="run-all")
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    step: Mapped[str | None] = mapped_column(String(120), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    log: Mapped[list | None] = mapped_column(JSONType, nullable=True)
