"""Runs skill extraction over stored postings and persists the results."""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models.job import JobPosting
from app.models.job_skill import JobSkill
from app.models.prediction import SkillCandidate
from app.models.skill import Skill
from app.services.llm_enhancer import enhance_candidates
from app.services.normalization import get_taxonomy, sync_taxonomy
from app.services.skill_extraction import ExtractionResult, SkillExtractor, count_candidates

logger = logging.getLogger(__name__)

BATCH = 400
MIN_CANDIDATE_MENTIONS = 3


def reset_extraction(db: Session) -> None:
    """Forget all extracted skills so every posting is re-processed (e.g. after a taxonomy change)."""
    db.execute(delete(JobSkill))
    db.execute(update(JobPosting).values(skills_extracted_at=None))
    db.commit()


def posting_text(title: str | None, description: str | None) -> str:
    """Text analysed for skills: the title (often names the stack) plus the cleaned description."""
    return f"{title or ''}\n{description or ''}".strip()


def run_extraction(db: Session, extractor: SkillExtractor | None = None,
                   progress: Callable[[int, int], None] | None = None) -> dict:
    """Extract skills for every cleaned, non-duplicate posting that has not been processed yet."""
    taxonomy = get_taxonomy()
    sync_taxonomy(db, taxonomy)
    slug_to_id = {s.canonical_name: s.id for s in db.scalars(select(Skill))}
    extractor = extractor or SkillExtractor(taxonomy)

    pending_filter = (JobPosting.cleaned_at.is_not(None), JobPosting.is_duplicate.is_(False),
                      JobPosting.skills_extracted_at.is_(None))
    total = db.scalar(select(func.count()).select_from(JobPosting).where(*pending_filter)) or 0
    done = links = 0
    methods: dict[str, int] = {}
    cand_results: list[tuple[int, ExtractionResult]] = []
    now = datetime.now(timezone.utc)

    while True:
        batch = db.execute(
            select(JobPosting.id, JobPosting.title, JobPosting.clean_description, JobPosting.year)
            .where(*pending_filter).order_by(JobPosting.id).limit(BATCH)
        ).all()
        if not batch:
            break
        link_rows: list[dict] = []
        for job_id, title, desc, year in batch:
            res = extractor.extract(posting_text(title, desc))
            cand_results.append((year or 0, res))
            for slug, (conf, method) in res.skills.items():
                sid = slug_to_id.get(slug)
                if sid is None:
                    continue
                link_rows.append({"job_id": job_id, "skill_id": sid, "confidence_score": conf, "extraction_method": method})
                methods[method] = methods.get(method, 0) + 1
        if link_rows:
            db.bulk_insert_mappings(JobSkill, link_rows)
        db.execute(update(JobPosting).where(JobPosting.id.in_([b[0] for b in batch])).values(skills_extracted_at=now))
        db.commit()
        done += len(batch)
        links += len(link_rows)
        if progress:
            progress(done, total)

    new_candidates = _store_candidates(db, cand_results)
    llm = enhance_candidates(db)
    logger.info("Extracted %d skill mentions from %d postings (%s)", links, done, methods)
    return {"jobs_processed": done, "skill_mentions": links, "methods": methods,
            "candidate_phrases": new_candidates, "llm_suggestions": llm,
            "semantic_backend": extractor.semantic.backend if extractor.semantic else None}


def _store_candidates(db: Session, results: list[tuple[int, ExtractionResult]]) -> int:
    """Accumulate unknown technology-looking phrases for taxonomy review."""
    stats = count_candidates(results)
    if not stats:
        return 0
    taxonomy = get_taxonomy()
    existing = {c.phrase: c for c in db.scalars(select(SkillCandidate))}
    for phrase, s in stats.items():
        if taxonomy.lookup(phrase) is not None:
            continue
        row = existing.get(phrase)
        if row:
            row.mentions += s["mentions"]
            row.first_year = min(filter(None, [row.first_year, s["first_year"]]), default=None)
            row.last_year = max(filter(None, [row.last_year, s["last_year"]]), default=None)
        elif s["mentions"] >= 1:
            db.add(SkillCandidate(phrase=phrase[:200], mentions=s["mentions"], first_year=s["first_year"] or None,
                                  last_year=s["last_year"] or None))
    db.commit()
    return db.scalar(select(func.count()).select_from(SkillCandidate).where(SkillCandidate.mentions >= MIN_CANDIDATE_MENTIONS)) or 0
