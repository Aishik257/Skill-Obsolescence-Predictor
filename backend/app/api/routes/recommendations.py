"""Personal skill-gap and 'what should I learn' endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.common import SkillGapRequest, SkillListRequest
from app.services import recommendations as reco

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.post("/skill-gap", summary="Compare your skills with growing, emerging and at-risk skills")
def skill_gap(body: SkillGapRequest, db: Session = Depends(get_db)) -> dict:
    return reco.skill_gap(db, body.role, body.skills)


@router.post("/learning-path", summary="Ranked learning recommendations for a role and current skills")
def learning_path(body: SkillListRequest, db: Session = Depends(get_db)) -> dict:
    return reco.learning_path(db, body.role, body.skills, body.limit)
