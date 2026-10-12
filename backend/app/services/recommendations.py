"""Personal skill-gap analysis and ranked learning recommendations.

Every number comes from the analysed postings: role demand and growth over the last two
years, the stored forecast, the obsolescence score and co-occurrence with the user's skills.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BadRequestError, UnprocessableError
from app.models.job import JobPosting
from app.models.prediction import Prediction
from app.models.skill import Skill
from app.services import replacement as repl
from app.services.analysis_data import job_conditions, role_skill_shares
from app.services.normalization import get_taxonomy
from app.services.views import data_version, prediction_row, relations
from app.utils.cache import analysis_cache
from app.utils.roles import ROLES

WEIGHTS = {"demand": 0.40, "growth": 0.20, "forecast": 0.15, "safety": 0.10, "synergy": 0.15}
EXCLUDED_STATUSES = {"declining", "at_risk", "insufficient_data"}
HIGH, MEDIUM = 0.62, 0.48


def resolve_skills(db: Session, names: list[str]) -> tuple[list[Skill], list[str]]:
    """Map user-entered names (aliases, typos) to taxonomy skills; return (matched, unrecognised)."""
    tax = get_taxonomy()
    by_slug = {s.canonical_name: s for s in db.scalars(select(Skill))}
    matched: dict[int, Skill] = {}
    unknown: list[str] = []
    for raw in names:
        name = (raw or "").strip()
        if not name:
            continue
        entry = tax.resolve(name)
        skill = by_slug.get(entry.slug) if entry else None
        if skill:
            matched[skill.id] = skill
        else:
            unknown.append(name)
    return list(matched.values()), unknown


def _context(db: Session, role: str | None) -> dict:
    """Demand context for a role (or the whole market): shares now and a year earlier."""
    def build() -> dict:
        as_of = db.scalar(select(func.max(JobPosting.posted_date)).where(*job_conditions(None)))
        if as_of is None:
            raise BadRequestError("No analysed job postings yet. Run the pipeline first.")
        cur_from, prev_from = as_of - timedelta(days=365), as_of - timedelta(days=730)
        jobs_c, ment_c = role_skill_shares(db, cur_from, as_of)
        jobs_p, ment_p = role_skill_shares(db, prev_from, cur_from)
        def share(jobs, ment, sid):
            if role:
                n = jobs.get(role, 0)
                return ment.get((role, sid), 0) / n if n else 0.0
            n = sum(jobs.values())
            return sum(v for (g, s), v in ment.items() if s == sid) / n if n else 0.0
        sids = {s for (_, s) in ment_c}
        return {"as_of": as_of, "role_jobs": jobs_c.get(role, 0) if role else sum(jobs_c.values()),
                "cur": {s: share(jobs_c, ment_c, s) for s in sids}, "prev": {s: share(jobs_p, ment_p, s) for s in sids}}
    return analysis_cache.get_or_set(("reco-ctx", data_version(db), role), build)


def _validate_role(role: str | None) -> None:
    if role and role not in ROLES:
        raise UnprocessableError(f"Unknown role '{role}'. Valid roles: {', '.join(ROLES)}.")


def _rank(db: Session, owned: list[Skill], role: str | None) -> tuple[list[dict], dict]:
    ctx = _context(db, role)
    skills = {s.id: s for s in db.scalars(select(Skill))}
    preds = {p.skill_id: p for p in db.scalars(select(Prediction))}
    co = repl.build_cooccurrence(db)
    owned_idx = [co.index(s.id) for s in owned if s.id in co.skill_ids]
    scope = role or "all"
    out: list[dict] = []
    for sid, share in ctx["cur"].items():
        if sid not in skills or sid in {s.id for s in owned} or sid not in preds:
            continue
        p = preds[sid]
        if p.trend_status in EXCLUDED_STATUSES or share < 0.02:
            continue
        prev = ctx["prev"].get(sid, 0.0)
        growth = (share - prev) / max(prev, 0.02)
        fchg = None
        if p.future_demand is not None and p.current_demand:
            fchg = (p.future_demand - p.current_demand) / max(p.current_demand, 0.01)
        synergy, paired = 0.5, []
        if owned_idx and sid in co.skill_ids:
            j = co.index(sid)
            conds = [(co.counts[i, j] / co.support(i) if co.support(i) else 0.0, co.skill_ids[i]) for i in owned_idx]
            synergy = float(np.clip(np.mean([c for c, _ in conds]) / 0.5, 0, 1))
            paired = [skills[s].name for c, s in sorted(conds, reverse=True)[:3] if c >= 0.2]
        parts = {"demand": min(1.0, share / 0.5), "growth": float(np.clip(0.5 + growth, 0, 1)),
                 "forecast": 0.5 if fchg is None else float(np.clip(0.5 + fchg, 0, 1)),
                 "safety": 1 - (p.obsolescence_score or 30) / 100, "synergy": synergy}
        priority = sum(WEIGHTS[k] * v for k, v in parts.items())
        reasons = [f"Appears in {share * 100:.0f}% of {scope if role else 'all'} postings "
                   f"({growth * 100:+.0f}% vs the previous 12 months)"]
        if fchg is not None:
            reasons.append(f"Forecast demand {fchg * 100:+.0f}% over two years")
        if paired:
            reasons.append("Often requested together with your " + ", ".join(paired))
        out.append({"skill_id": sid, "name": skills[sid].name, "category": skills[sid].category,
                    "trend_status": p.trend_status, "priority_score": round(priority, 3),
                    "priority": "HIGH" if priority >= HIGH else "MEDIUM" if priority >= MEDIUM else "LOW",
                    "role_demand": share, "role_growth": growth, "forecast_change": fchg,
                    "obsolescence_score": p.obsolescence_score, "reasons": reasons,
                    "components": {k: round(v, 3) for k, v in parts.items()}})
    out.sort(key=lambda r: -r["priority_score"])
    return out, ctx


def learning_path(db: Session, role: str | None, names: list[str], limit: int = 12) -> dict:
    """Ranked 'what should I learn' list for a role and current skills."""
    _validate_role(role)
    owned, unknown = resolve_skills(db, names)
    ranked, ctx = _rank(db, owned, role)
    return {"role": role, "as_of": ctx["as_of"].isoformat(), "role_postings": ctx["role_jobs"],
            "current_skills": [s.name for s in owned], "unrecognized": unknown,
            "recommendations": [{"rank": i + 1, **r} for i, r in enumerate(ranked[:limit])],
            "method": "priority = 40% demand + 20% growth + 15% forecast + 10% safety (1 - obsolescence/100) + 15% co-occurrence with your skills"}


def skill_gap(db: Session, role: str | None, names: list[str]) -> dict:
    """Strong skills, skills to strengthen, emerging skills to consider and at-risk skills you hold."""
    _validate_role(role)
    owned, unknown = resolve_skills(db, names)
    if not owned:
        raise BadRequestError("None of the entered skills were recognised. Try names like Python, SQL or Docker.")
    ranked, ctx = _rank(db, owned, role)
    preds = {p.skill_id: p for p in db.scalars(select(Prediction))}
    skills = {s.id: s for s in db.scalars(select(Skill))}
    strong, at_risk = [], []
    for s in owned:
        p = preds.get(s.id)
        row = prediction_row(s, p)
        row["role_demand"] = ctx["cur"].get(s.id, 0.0)
        if p is None or p.trend_status == "insufficient_data":
            row["note"] = "Too little data to assess"
            strong.append(row) if row["role_demand"] >= 0.05 else None
        elif p.trend_status in ("declining", "at_risk") or p.risk_level in ("HIGH", "CRITICAL"):
            row["alternatives"] = [{"skill_id": r["skill_id"], "name": r["name"], "score": r["score"]}
                                   for r in relations(db, s.id, "replacement", 3)]
            at_risk.append(row)
        else:
            strong.append(row)
    strong.sort(key=lambda r: -r["role_demand"])
    strengthen = [r for r in ranked if r["trend_status"] in ("growing", "stable")][:6]
    emerging = [r for r in ranked if r["trend_status"] == "emerging"][:5]
    top = sorted(((s, v) for s, v in ctx["cur"].items() if s in skills), key=lambda x: -x[1])[:15]
    owned_ids = {s.id for s in owned}
    total = sum(v for _, v in top)
    coverage = sum(v for s, v in top if s in owned_ids) / total if total else 0.0
    return {"role": role, "as_of": ctx["as_of"].isoformat(), "unrecognized": unknown,
            "strong_skills": strong, "skills_to_strengthen": strengthen, "emerging_to_consider": emerging,
            "at_risk_skills": at_risk, "coverage_of_top_skills": coverage,
            "top_skills_in_demand": [{"skill_id": s, "name": skills[s].name, "share": v, "owned": s in owned_ids} for s, v in top]}
