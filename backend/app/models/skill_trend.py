"""Monthly aggregated skill demand (global scope)."""
from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SkillTrend(Base):
    """Monthly skill demand: mentions relative to all (non-duplicate) postings."""

    __tablename__ = "skill_trends"
    __table_args__ = (UniqueConstraint("skill_id", "year", "month", name="uq_trend_period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    month: Mapped[int] = mapped_column(Integer)
    job_count: Mapped[int] = mapped_column(Integer)  # all postings in the month
    skill_mentions: Mapped[int] = mapped_column(Integer)  # postings mentioning the skill
    skill_frequency: Mapped[float] = mapped_column(Float)  # mentions / job_count
    growth_rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # YoY change in frequency
