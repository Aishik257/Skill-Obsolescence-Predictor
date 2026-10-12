"""Optional LLM layer (extraction layer 5): suggest names/categories for unknown skill candidates.

Entirely optional. With ``LLM_API_KEY`` or ``LLM_PROVIDER`` empty this module does nothing, and a
failing API call is logged and ignored - the pipeline never depends on an external LLM. The model
only *suggests*; suggestions are stored for human review and never change the taxonomy or any
number on the dashboard.
"""
from __future__ import annotations

import json
import logging
import re

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.prediction import SkillCandidate

logger = logging.getLogger(__name__)

MAX_PHRASES = 40
PROMPT = (
    "You review phrases extracted from tech job postings. For each phrase decide if it is a concrete "
    "technology, tool, framework, language or professional skill. Reply with ONLY a JSON array of objects "
    '{"phrase": str, "is_skill": bool, "name": str, "category": str}. Phrases: '
)


def _call_llm(prompt: str) -> str:
    provider = settings.LLM_PROVIDER.lower()
    with httpx.Client(timeout=30) as client:
        if provider == "anthropic":
            r = client.post("https://api.anthropic.com/v1/messages",
                            headers={"x-api-key": settings.LLM_API_KEY, "anthropic-version": "2023-06-01"},
                            json={"model": settings.LLM_MODEL or "claude-haiku-4-5-20251001", "max_tokens": 2000,
                                  "messages": [{"role": "user", "content": prompt}]})
            r.raise_for_status()
            return r.json()["content"][0]["text"]
        if provider == "openai":
            r = client.post("https://api.openai.com/v1/chat/completions",
                            headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
                            json={"model": settings.LLM_MODEL or "gpt-4o-mini",
                                  "messages": [{"role": "user", "content": prompt}]})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
    raise ValueError(f"Unsupported LLM_PROVIDER '{settings.LLM_PROVIDER}' (use 'anthropic' or 'openai')")


def enhance_candidates(db: Session) -> int:
    """Ask the configured LLM to label top unlabeled candidates. Returns the number of suggestions stored."""
    if not settings.llm_enabled:
        return 0
    rows = db.scalars(select(SkillCandidate).where(SkillCandidate.suggested_name.is_(None))
                      .order_by(SkillCandidate.mentions.desc()).limit(MAX_PHRASES)).all()
    if not rows:
        return 0
    try:
        text = _call_llm(PROMPT + json.dumps([r.phrase for r in rows]))
        match = re.search(r"\[.*\]", text, re.S)
        answers = json.loads(match.group(0)) if match else []
    except Exception as exc:  # noqa: BLE001 - optional layer: log and continue
        logger.warning("LLM enhancement skipped: %s", exc)
        return 0
    by_phrase = {r.phrase.lower(): r for r in rows}
    stored = 0
    for a in answers:
        row = by_phrase.get(str(a.get("phrase", "")).lower())
        if row and a.get("is_skill") and a.get("name"):
            row.suggested_name, row.suggested_category, row.source = str(a["name"])[:120], str(a.get("category", ""))[:80], "llm"
            stored += 1
    db.commit()
    return stored
