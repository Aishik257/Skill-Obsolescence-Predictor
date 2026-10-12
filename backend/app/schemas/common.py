"""Request/response models shared by several routers."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SkillListRequest(BaseModel):
    role: str | None = Field(None, description="Target role, e.g. 'Data Scientist'")
    skills: list[str] = Field(..., min_length=1, max_length=60, description="Skills the user already has")
    limit: int = Field(12, ge=1, le=40)


class SkillGapRequest(BaseModel):
    role: str | None = None
    skills: list[str] = Field(..., min_length=1, max_length=60)


class PipelineStarted(BaseModel):
    run_id: int
    status: str = "running"
    message: str = "Pipeline started. Poll GET /api/pipeline/status?run_id=<id> for progress."


class Page(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
    pages: int
