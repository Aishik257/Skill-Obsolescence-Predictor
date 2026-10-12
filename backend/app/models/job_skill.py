"""Association between job postings and extracted skills."""
from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

EXTRACTION_METHODS = ("keyword", "taxonomy", "fuzzy", "embedding", "ner", "hybrid")


class JobSkill(Base):
    """A skill detected in a job posting, with confidence and detection method."""

    __tablename__ = "job_skills"
    __table_args__ = (
        UniqueConstraint("job_id", "skill_id", name="uq_job_skill"),
        Index("ix_job_skills_skill", "skill_id", "job_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_postings.id", ondelete="CASCADE"), index=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"))
    confidence_score: Mapped[float] = mapped_column(Float)
    extraction_method: Mapped[str] = mapped_column(String(20))
