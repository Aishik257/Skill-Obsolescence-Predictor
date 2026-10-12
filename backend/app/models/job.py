"""Job posting ORM model."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class JobPosting(Base):
    """A single job posting, plus fields derived by the cleaning stage."""

    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint("source_job_id", name="uq_job_source_job_id"),
        Index("ix_jobs_year_month", "year", "month"),
        Index("ix_jobs_active", "is_duplicate", "posted_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_job_id: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    posted_date: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(100), default="upload")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # --- derived by the cleaning stage ---------------------------------
    clean_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_title: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    normalized_company: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    role: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    region: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    quarter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_postings.id", ondelete="SET NULL"), nullable=True
    )
    cleaned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    skills_extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
