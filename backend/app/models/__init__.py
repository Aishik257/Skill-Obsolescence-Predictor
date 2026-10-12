"""Import all models so that Base.metadata knows every table."""
from app.models.job import JobPosting
from app.models.job_skill import JobSkill
from app.models.prediction import (
    Forecast,
    ModelMetric,
    PipelineRun,
    Prediction,
    SkillCandidate,
    SkillRelation,
)
from app.models.skill import Skill
from app.models.skill_trend import SkillTrend

__all__ = [
    "Forecast",
    "JobPosting",
    "JobSkill",
    "ModelMetric",
    "PipelineRun",
    "Prediction",
    "Skill",
    "SkillCandidate",
    "SkillRelation",
    "SkillTrend",
]
