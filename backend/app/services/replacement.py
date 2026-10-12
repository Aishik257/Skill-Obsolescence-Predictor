"""Co-occurrence and potential-replacement analysis.

Replacement candidates are *hypotheses about a market transition*, never causal claims. For a
declining skill D and a growing skill G the score blends five measurable signals:

* temporal overlap   - how often D lost share in the same years G gained it (+ negative
                       correlation of their year-over-year share changes)
* semantic similarity- TF-IDF cosine similarity of the skills' descriptions
* category match     - same taxonomy category
* exclusivity        - co-occurrence *lift* below 1 (the two rarely appear in the same posting)
* growth strength    - how many share points G gained
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ml.feature_engineering import TrendMetrics, rolling_share
from app.models.job import JobPosting
from app.models.job_skill import JobSkill
from app.models.skill import Skill
from app.services.analysis_data import FrequencyData, job_conditions

logger = logging.getLogger(__name__)

DECLINER_MAX_GROWTH = -0.20
GROWER_MIN_GROWTH = 0.25
GROWER_MIN_DEMAND = 0.03
MIN_SCORE = 0.45
MIN_EXCLUSIVITY = 0.25  # lift must be <= 0.75
MIN_SEMANTIC = 0.30  # normalised description similarity needed for a plausible substitute
TOP_REPLACEMENTS = 5
TOP_RELATED = 10
MIN_SUPPORT = 20  # postings in which a pair must co-occur to be listed as related
WEIGHTS = {"temporal": 0.30, "semantic": 0.20, "category": 0.20, "exclusivity": 0.20, "growth": 0.10}

CAUSATION_NOTE = (
    "{grower} shows strong growth during the period in which {decliner} declined. This indicates a potential "
    "market transition, but does not establish direct causation."
)


@dataclass
class CooccurrenceMatrix:
    skill_ids: list[int]
    counts: np.ndarray  # (S, S) number of postings containing both skills
    n_jobs: int

    def index(self, skill_id: int) -> int:
        return self.skill_ids.index(skill_id)

    def support(self, i: int) -> float:
        return float(self.counts[i, i])


def build_cooccurrence(db: Session) -> CooccurrenceMatrix:
    """Pairwise co-occurrence counts across all non-duplicate postings."""
    rows = db.execute(
        select(JobSkill.job_id, JobSkill.skill_id).join(JobPosting, JobPosting.id == JobSkill.job_id)
        .where(*job_conditions(None))
    ).all()
    n_jobs = db.scalar(select(func.count()).select_from(JobPosting).where(*job_conditions(None))) or 0
    if not rows:
        return CooccurrenceMatrix([], np.zeros((0, 0)), int(n_jobs))
    job_ids = {j: i for i, j in enumerate(sorted({r[0] for r in rows}))}
    skill_ids = sorted({r[1] for r in rows})
    s_idx = {s: i for i, s in enumerate(skill_ids)}
    X = sparse.csr_matrix(
        (np.ones(len(rows)), ([job_ids[r[0]] for r in rows], [s_idx[r[1]] for r in rows])),
        shape=(len(job_ids), len(skill_ids)),
    )
    X.data[:] = 1.0
    return CooccurrenceMatrix(skill_ids, (X.T @ X).toarray(), int(n_jobs))


def lift(co: CooccurrenceMatrix, i: int, j: int) -> float:
    pi, pj = co.support(i) / co.n_jobs, co.support(j) / co.n_jobs
    pij = co.counts[i, j] / co.n_jobs
    return float(pij / (pi * pj)) if pi > 0 and pj > 0 else 0.0


def npmi(co: CooccurrenceMatrix, i: int, j: int) -> float:
    """Normalized pointwise mutual information in [-1, 1]."""
    pij = co.counts[i, j] / co.n_jobs
    if pij <= 0:
        return -1.0
    pi, pj = co.support(i) / co.n_jobs, co.support(j) / co.n_jobs
    return float(np.log(pij / (pi * pj)) / -np.log(pij))


def related_skills(co: CooccurrenceMatrix, skill_id: int, top: int = TOP_RELATED) -> list[dict]:
    """Skills that most distinctively appear with ``skill_id`` (ranked by NPMI, support-filtered)."""
    if skill_id not in co.skill_ids:
        return []
    i = co.index(skill_id)
    out = []
    for j, sid in enumerate(co.skill_ids):
        if j == i or co.counts[i, j] < MIN_SUPPORT:
            continue
        lf = lift(co, i, j)
        if lf <= 1.1:
            continue
        out.append({"skill_id": sid, "score": npmi(co, i, j), "lift": lf, "together": int(co.counts[i, j]),
                    "share_with": float(co.counts[i, j] / co.support(i))})
    out.sort(key=lambda r: -r["score"])
    return out[:top]


# generic words that make unrelated skills look alike ("programming language", "open source tool")
DOMAIN_STOP_WORDS = sorted(ENGLISH_STOP_WORDS | {
    "programming", "language", "languages", "framework", "frameworks", "library", "libraries", "tool", "tools",
    "platform", "open", "source", "used", "use", "software", "applications", "application", "systems", "system",
    "development", "legacy", "modern", "popular", "building", "based", "data", "web", "code", "engineering",
})


def similarity_matrix(skills: list[Skill]) -> np.ndarray:
    """Cosine similarity between skill descriptions (TF-IDF, offline)."""
    docs = [f"{s.name} {s.category} {s.description or ''}" for s in skills]
    mat = TfidfVectorizer(stop_words=DOMAIN_STOP_WORDS, sublinear_tf=True, ngram_range=(1, 2)).fit_transform(docs)
    return (mat @ mat.T).toarray()


def _yearly_changes(data: FrequencyData, sid: int, min_jobs: int) -> np.ndarray:
    """Year-over-year change of the rolling 4-quarter share (NaN where undefined)."""
    mask = data.jobs >= min_jobs
    mentions, jobs = data.column(sid)[mask], data.jobs[mask]
    roll = rolling_share(mentions, jobs)
    out = np.full(len(roll), np.nan)
    out[4:] = roll[4:] - roll[:-4]
    return out


def compute_relations(db: Session, data: FrequencyData, metrics: dict[int, TrendMetrics | None],
                      skills: dict[int, Skill], min_jobs: int) -> tuple[list[dict], list[dict]]:
    """Return (cooccurrence_rows, replacement_rows) ready for ``SkillRelation`` insertion."""
    co = build_cooccurrence(db)
    cooc_rows: list[dict] = []
    for sid in co.skill_ids:
        for rel in related_skills(co, sid):
            cooc_rows.append({"skill_id": sid, "related_skill_id": rel["skill_id"], "kind": "cooccurrence",
                              "score": rel["score"], "details": {k: rel[k] for k in ("lift", "together", "share_with")}})

    ids = [sid for sid in data.skill_ids if sid in skills and metrics.get(sid) is not None]
    if not ids:
        return cooc_rows, []
    sim_ids = list(skills)
    sim = similarity_matrix([skills[s] for s in sim_ids])
    sim_pos = {s: i for i, s in enumerate(sim_ids)}
    changes = {sid: _yearly_changes(data, sid, min_jobs) for sid in ids}
    decliners = [s for s in ids if metrics[s].long_term_growth <= DECLINER_MAX_GROWTH and metrics[s].p_long < 0.05]
    growers = [s for s in ids if metrics[s].long_term_growth >= GROWER_MIN_GROWTH
               and metrics[s].current_demand >= GROWER_MIN_DEMAND and metrics[s].p_long < 0.05]

    repl_rows: list[dict] = []
    for d in decliners:
        scored = []
        for g in growers:
            if g == d:
                continue
            cd, cg = changes[d], changes[g]
            valid = ~np.isnan(cd) & ~np.isnan(cg)
            if valid.sum() < 4:
                continue
            overlap = float(np.mean((cd[valid] < 0) & (cg[valid] > 0)))
            corr = float(np.corrcoef(cd[valid], cg[valid])[0, 1]) if np.std(cd[valid]) > 0 and np.std(cg[valid]) > 0 else 0.0
            temporal = 0.5 * overlap + 0.5 * max(0.0, -corr)
            semantic = min(1.0, float(sim[sim_pos[d], sim_pos[g]]) / 0.3)
            if semantic < MIN_SEMANTIC:
                continue
            category = 1.0 if skills[d].category == skills[g].category else 0.0
            if d in co.skill_ids and g in co.skill_ids:
                lf = lift(co, co.index(d), co.index(g))
                together = int(co.counts[co.index(d), co.index(g)])
            else:
                lf, together = 1.0, 0
            exclusivity = float(np.clip(1.0 - lf, 0.0, 1.0))
            if exclusivity < MIN_EXCLUSIVITY:
                continue  # skills that co-occur at or above chance are complements, not substitutes
            growth = min(1.0, max(0.0, metrics[g].pp_change) / 0.20)
            parts = {"temporal": temporal, "semantic": semantic, "category": category,
                     "exclusivity": exclusivity, "growth": growth}
            score = sum(WEIGHTS[k] * v for k, v in parts.items())
            if score >= MIN_SCORE:
                scored.append((score, g, parts, lf, together, overlap, corr))
        scored.sort(key=lambda r: -r[0])
        for score, g, parts, lf, together, overlap, corr in scored[:TOP_REPLACEMENTS]:
            repl_rows.append({
                "skill_id": d, "related_skill_id": g, "kind": "replacement", "score": float(score),
                "details": {"components": {k: float(v) for k, v in parts.items()}, "lift": float(lf),
                            "together": together, "overlap": overlap, "correlation": corr,
                            "decliner_change": float(metrics[d].long_term_growth),
                            "grower_change": float(metrics[g].long_term_growth),
                            "grower_pp_change": float(metrics[g].pp_change),
                            "note": CAUSATION_NOTE.format(grower=skills[g].name, decliner=skills[d].name)},
            })
    logger.info("Relations: %d co-occurrence pairs, %d replacement hypotheses for %d declining skills",
                len(cooc_rows), len(repl_rows), len(decliners))
    return cooc_rows, repl_rows


def replacement_pressure(rows: list[dict]) -> dict[int, float]:
    """Top replacement score per declining skill -> input for the 'emerging replacement risk' component."""
    best: dict[int, float] = {}
    for r in rows:
        best[r["skill_id"]] = max(best.get(r["skill_id"], 0.0), r["score"])
    return best
