"""Semantic matching of free-text phrases to taxonomy skills (extraction layer 4).

Two interchangeable backends:

* ``sentence-transformers`` - neural sentence embeddings (optional dependency; needs to
  download a model from Hugging Face on first use).
* ``tfidf`` - word + character TF-IDF cosine similarity against each skill's description
  and alias text. Fully offline and deterministic; this is the default fallback.

A phrase is mapped to a skill only when its similarity exceeds a configured threshold
*and* beats the runner-up skill by a margin, so ambiguous phrases are left unmapped.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from app.core.config import settings
from app.services.normalization import Taxonomy, TaxonomyEntry

logger = logging.getLogger(__name__)


@dataclass
class SemanticMatch:
    entry: TaxonomyEntry
    score: float
    margin: float


class SemanticMatcher:
    """Maps phrases such as "container orchestration" onto skills such as Kubernetes."""

    def __init__(self, taxonomy: Taxonomy, backend: str | None = None):
        self.taxonomy = taxonomy
        self.entries = taxonomy.entries
        requested = (backend or settings.EMBEDDING_BACKEND).lower()
        self.backend = "tfidf"
        self._model = None
        self._cache: dict[str, np.ndarray] = {}
        if requested in ("auto", "sentence-transformers"):
            try:  # optional dependency
                from sentence_transformers import SentenceTransformer  # type: ignore

                self._model = SentenceTransformer(settings.EMBEDDING_MODEL)
                self.backend = "sentence-transformers"
            except Exception as exc:  # noqa: BLE001 - any failure falls back to TF-IDF
                if requested == "sentence-transformers":
                    logger.warning("sentence-transformers unavailable (%s); using TF-IDF backend", exc)
                else:
                    logger.info("Neural embeddings not available (%s); using TF-IDF backend", type(exc).__name__)
        self.threshold = settings.SEMANTIC_THRESHOLD_NEURAL if self.backend == "sentence-transformers" else settings.SEMANTIC_THRESHOLD_TFIDF
        self._fit()

    # ------------------------------------------------------------------
    def _documents(self) -> tuple[list[str], list[str]]:
        desc = [f"{e.canonical} {e.description}" for e in self.entries]
        alias = [" ".join([e.canonical] + e.aliases) for e in self.entries]
        return desc, alias

    def _fit(self) -> None:
        desc, alias = self._documents()
        if self.backend == "sentence-transformers":
            self._desc_emb = self._model.encode(desc, normalize_embeddings=True)
            self._alias_emb = self._model.encode(alias, normalize_embeddings=True)
            return
        corpus = desc + alias
        self._word = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", sublinear_tf=True).fit(corpus)
        self._char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True).fit(corpus)
        self._desc_w, self._alias_w = self._word.transform(desc), self._word.transform(alias)
        self._desc_c, self._alias_c = self._char.transform(desc), self._char.transform(alias)

    # ------------------------------------------------------------------
    def similarities(self, phrases: list[str]) -> np.ndarray:
        """Similarity matrix of shape (n_phrases, n_skills) in [0, 1]."""
        if not phrases:
            return np.zeros((0, len(self.entries)))
        if self.backend == "sentence-transformers":
            emb = self._model.encode(phrases, normalize_embeddings=True)
            return np.maximum(emb @ self._desc_emb.T, emb @ self._alias_emb.T).clip(0, 1)
        qw, qc = self._word.transform(phrases), self._char.transform(phrases)
        word = np.maximum((qw @ self._desc_w.T).toarray(), (qw @ self._alias_w.T).toarray())
        char = np.maximum((qc @ self._desc_c.T).toarray(), (qc @ self._alias_c.T).toarray())
        return 0.75 * word + 0.25 * char

    def match_many(self, phrases: list[str]) -> list[SemanticMatch | None]:
        """Match phrases in one vectorized call; unmatched phrases yield ``None``."""
        sims = self.similarities(phrases)
        out: list[SemanticMatch | None] = []
        for row in sims:
            if row.size < 2:
                out.append(None)
                continue
            top2 = np.argpartition(-row, 1)[:2]
            best, second = sorted(top2, key=lambda i: -row[i])
            score, margin = float(row[best]), float(row[best] - row[second])
            if score >= self.threshold and margin >= settings.SEMANTIC_MARGIN:
                out.append(SemanticMatch(self.entries[best], score, margin))
            else:
                out.append(None)
        return out

    def match(self, phrase: str) -> SemanticMatch | None:
        return self.match_many([phrase])[0]
