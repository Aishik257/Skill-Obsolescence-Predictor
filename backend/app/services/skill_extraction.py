"""Hybrid skill extraction engine.

Layers (all deterministic and offline; an optional LLM layer lives in llm_enhancer.py):

1. **Dictionary / taxonomy** - O(tokens) n-gram lookup of every alias on word boundaries
   (no substring matching: "sql" is never found inside "sequel" or "PostgreSQL").
2. **Context rules** - ambiguous aliases (``Go``, ``R``, ``Swift``, ``Spring`` ...) are only
   accepted with their exact capitalization *and* technology context; ``React``-style
   aliases are only accepted capitalized and mid-sentence.
3. **Phrase detection (spaCy)** - sentences are segmented with spaCy and skill lists are
   pulled out of cue phrases ("experience with X, Y and Z"). Phrases are normalized
   ("the Django framework" -> Django), fuzzily matched for typos ("Kubernets"), and
   technology-looking leftovers are kept as *candidate* skills for taxonomy review.
4. **Semantic similarity** - remaining phrases ("container orchestration") are compared to
   every skill's description/aliases and mapped when similarity clears a threshold.

Every extraction carries a confidence and the method that found it.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field

from app.core.config import settings
from app.services.normalization import MODE_CASED, MODE_PLAIN, MODE_STRICT, Taxonomy, get_taxonomy
from app.services.semantic import SemanticMatcher
from app.utils.text import Atom, atoms, phrase_key

logger = logging.getLogger(__name__)

# --- context cues for strict aliases ----------------------------------------------
DEFAULT_CUES = {
    "programming", "language", "developer", "developers", "engineer", "framework", "library", "coding",
    "scripting", "backend", "stack", "proficiency", "proficient", "fluent", "fluency",
}
STRICT_CUES: dict[str, set[str]] = {
    "go": {"golang", "concurrency", "microservices", "backend", "services"},
    "r": {"statistical", "statistics", "rstudio", "ggplot", "analysis", "tidyverse", "data"},
    "c": {"embedded", "systems", "firmware", "kernel"},
    "swift": {"ios", "apple", "xcode", "objective", "swiftui", "macos"},
    "spring": {"boot", "mvc", "java", "hibernate", "microservices"},
    "express": {"node", "nodejs", "js", "middleware", "routes", "server", "javascript"},
    "spark": {"hadoop", "pyspark", "scala", "distributed", "cluster", "streaming", "databricks", "big"},
    "flash": {"actionscript", "animation", "player", "plugin", "adobe", "swf"},
    "puppet": {"configuration", "ansible", "chef", "manifests", "automation"},
    "chef": {"configuration", "cookbooks", "puppet", "ansible", "automation"},
    "julia": {"numerical", "scientific", "python", "computing"},
    "excel": {"spreadsheet", "spreadsheets", "pivot", "vba", "macros", "formulas", "powerpoint", "word"},
    "node": {"js", "javascript", "server", "backend", "npm"},
    "hadoop": {"hdfs", "mapreduce", "spark", "cluster", "warehouse", "big", "hbase", "yarn"},
}
_GAP_RE = re.compile(r"[ \t_/\-]{0,3}")
NEIGHBOR_WINDOW = 3  # atoms
CUE_WINDOW = 5

# --- phrase detection --------------------------------------------------------------
CUE_PHRASES = [
    "years of experience with", "years of experience in", "experience building production systems using",
    "experience working with", "experience with", "experience in", "experience using", "proficiency in",
    "proficiency with", "proficient in", "knowledge of", "familiarity with", "expertise in", "understanding of",
    "skills in", "background in", "exposure to", "real projects using", "solutions on", "improve our",
    "nice to have:", "nice to have", "maintain services using", "services using", "work with", "working with",
    "points for experience with", "competency in", "using",
]
_CUE_RE = re.compile("(?:" + "|".join(re.escape(c) for c in sorted(CUE_PHRASES, key=len, reverse=True)) + r")\s+", re.I)
_END_RE = re.compile(
    r"\s+(?:is required|is a plus|would be an advantage|are required|is preferred|in a team environment|"
    r"to deliver|stack|is an advantage)\b.*$|[.;]\s*$",
    re.I,
)
_SPLIT_RE = re.compile(r"\s*(?:,\s*(?:and\s+|or\s+)?|;\s*|\s+/\s+|/|\s+&\s+|\s+and\s+|\s+or\s+)\s*")
_LEAD_STRIP = {"strong", "solid", "deep", "hands-on", "hands", "on", "the", "a", "an", "our", "modern", "good", "great", "working"}
_TRAIL_STRIP = {"framework", "frameworks", "library", "libraries", "platform", "platforms", "tool", "tools", "tooling",
                "stack", "technologies", "technology", "language", "development", "experience", "environment", "skills"}
_GENERIC_WORDS = {
    "communication", "collaboration", "teamwork", "leadership", "mindset", "problem", "solving", "ownership", "team",
    "collaborative", "curiosity", "passion", "learning", "attention", "detail", "stakeholders", "customers", "business",
    "product", "products", "requirements", "quality", "performance", "reliability", "security", "delivery", "systems",
    "software", "engineering", "projects", "features", "services", "applications", "solutions", "data", "models",
    "design", "architecture", "documentation", "testing", "research", "analysis", "reporting", "insights",
}
_TECH_LIKE_RE = re.compile(r"^(?:[A-Z][A-Za-z0-9]*[A-Z0-9][A-Za-z0-9]*|[a-z]+[A-Z][A-Za-z0-9]*|[A-Z][a-z]{2,}[0-9]*|[A-Za-z0-9]+\.(?:js|io|ai|dev|net))$")

_ENGLISH_STOP = {
    "responsibilities", "requirements", "benefits", "apply", "join", "about", "what", "offer", "work", "team",
    "strong", "excellent", "good", "great", "ability", "plus", "nice", "have", "bonus", "points", "familiarity",
    "exposure", "years", "year", "demonstrated", "solid", "required", "preferred", "with", "using",
}


@dataclass
class Hit:
    slug: str
    confidence: float
    layer: str  # dictionary | fuzzy | ner | embedding
    method: str  # keyword | taxonomy | fuzzy | ner | embedding
    start: int = -1
    end: int = -1


@dataclass
class ExtractionResult:
    skills: dict[str, tuple[float, str]] = field(default_factory=dict)  # slug -> (confidence, method)
    candidates: list[str] = field(default_factory=list)  # technology-looking phrases not in the taxonomy


class _SentenceSplitter:
    """spaCy sentencizer when available (tokenizer-only pipeline, no model download), else regex."""

    def __init__(self) -> None:
        self.nlp = None
        try:
            import spacy

            self.nlp = spacy.blank("en")
            self.nlp.add_pipe("sentencizer")
            self.nlp.max_length = 2_000_000
        except Exception as exc:  # noqa: BLE001
            logger.warning("spaCy unavailable (%s); falling back to regex sentence splitting", exc)

    def split(self, text: str) -> list[str]:
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        out: list[str] = []
        if self.nlp is None:
            for ln in lines:
                out.extend(s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", ln) if s.strip())
            return out
        for doc in self.nlp.pipe(lines, batch_size=256):
            out.extend(s.text.strip() for s in doc.sents if s.text.strip())
        return out


class SkillExtractor:
    """Extracts normalized skills from posting text using the layered approach above."""

    def __init__(self, taxonomy: Taxonomy | None = None, semantic: SemanticMatcher | None = None,
                 use_semantic: bool = True):
        self.taxonomy = taxonomy or get_taxonomy()
        self.semantic = semantic if semantic is not None else (SemanticMatcher(self.taxonomy) if use_semantic else None)
        self.splitter = _SentenceSplitter()
        self._sem_cache: dict[str, tuple[str, float] | None] = {}
        self._fuzzy_cache: dict[str, tuple[str, float] | None] = {}
        self.min_conf = settings.MIN_EXTRACTION_CONFIDENCE

    # ------------------------------------------------------------------ layer 1+2
    def _dictionary_hits(self, text: str, toks: list[Atom]) -> tuple[list[Hit], list[tuple[int, int]]]:
        """Longest-match n-gram lookup; returns hits and consumed (start, end) char spans."""
        index, max_n = self.taxonomy.alias_index, self.taxonomy.max_ngram
        lowers = [t.lower for t in toks]
        n_tok = len(toks)
        plain: list[tuple[int, int, str, object]] = []  # (i, n, slug, info)
        deferred: list[tuple[int, int, object, object]] = []  # strict / cased candidates
        i = 0
        while i < n_tok:
            matched = False
            for n in range(min(max_n, n_tok - i), 0, -1):
                if n > 1 and not self._contiguous(text, toks, i, n):
                    continue  # never match a multi-word alias across a comma, newline, bracket...
                hit = index.get(" ".join(lowers[i:i + n]))
                if not hit and 2 <= n <= 3:
                    hit = self.taxonomy.compact_index.get("".join(lowers[i:i + n]))  # "Tensor Flow" -> TensorFlow
                if not hit:
                    continue
                entry, info = hit
                if info.mode == MODE_PLAIN:
                    plain.append((i, n, entry.slug, info))
                else:
                    surface = " ".join(t.text for t in toks[i:i + n])
                    if surface == info.text:  # exact capitalization required
                        deferred.append((i, n, entry, info))
                    else:
                        i += 0  # wrong case: treat as ordinary word, keep scanning shorter n-grams
                        continue
                i += n
                matched = True
                break
            if not matched:
                i += 1

        hits: list[Hit] = []
        spans: list[tuple[int, int]] = []
        plain_positions = [(p[0], p[0] + p[1]) for p in plain]
        for i, n, slug, info in plain:
            start, end = toks[i].start, toks[i + n - 1].end
            hits.append(Hit(slug, 0.98 if info.is_canonical else 0.92, "dictionary",
                            "keyword" if info.is_canonical else "taxonomy", start, end))
            spans.append((start, end))

        for i, n, entry, info in deferred:
            start, end = toks[i].start, toks[i + n - 1].end
            if self._glued(text, start, end):
                continue  # "C-suite", "R&D", "Go-getter": part of a different word/phrase
            neighbor = any(
                (j < i and i - j <= NEIGHBOR_WINDOW) or (j >= i + n and j - (i + n) < NEIGHBOR_WINDOW)
                for a, b in plain_positions for j in (a, b - 1)
            )
            lo, hi = max(0, i - CUE_WINDOW), min(n_tok, i + n + CUE_WINDOW)
            cues = DEFAULT_CUES | STRICT_CUES.get(entry.canonical.lower(), set())
            cue = any(lowers[j] in cues for j in range(lo, hi) if not (i <= j < i + n))
            if info.mode == MODE_STRICT:
                if neighbor:
                    conf = 0.78
                elif cue:
                    conf = 0.74
                else:
                    continue
            else:  # MODE_CASED: accepted mid-sentence on capitalization alone
                if self._sentence_initial(text, start) and not (neighbor or cue):
                    continue
                conf = 0.9
            hits.append(Hit(entry.slug, conf, "dictionary", "taxonomy", start, end))
            spans.append((start, end))
        return hits, spans

    @staticmethod
    def _contiguous(text: str, toks: list[Atom], i: int, n: int) -> bool:
        """True when atoms i..i+n-1 are separated only by spaces, hyphens or slashes."""
        for k in range(i, i + n - 1):
            if not _GAP_RE.fullmatch(text[toks[k].end:toks[k + 1].start]):
                return False
        return True

    @staticmethod
    def _glued(text: str, start: int, end: int) -> bool:
        """True when a token is fused to its neighbours by - & ' (e.g. C-suite, R&D, Go-getter)."""
        before = text[start - 1] if start > 0 else " "
        after = text[end] if end < len(text) else " "
        nxt = text[end + 1] if end + 1 < len(text) else " "
        if before in "-&'" and start > 1 and text[start - 2].isalnum():
            return True
        return after in "-&'" and nxt.isalnum()

    @staticmethod
    def _sentence_initial(text: str, start: int) -> bool:
        j = start - 1
        while j >= 0 and text[j] in " \t-*•":
            j -= 1
        return j < 0 or text[j] in ".!?:\n"

    # ------------------------------------------------------------------ layer 3
    def _phrase_items(self, text: str) -> list[tuple[str, int, int]]:
        """Skill-list items from cue phrases, as (item_text, abs_start, abs_end)."""
        items: list[tuple[str, int, int]] = []
        cursor = 0
        for sentence in self.splitter.split(text):
            pos = text.find(sentence, cursor)
            if pos < 0:
                pos = cursor
            cursor = pos + len(sentence)
            matches = list(_CUE_RE.finditer(sentence))
            if not matches:
                continue
            m = matches[-1] if len(matches) > 1 and matches[-1].start() - matches[0].end() < 3 else matches[0]
            tail = sentence[m.end():]
            tail_clean = _END_RE.sub("", tail).strip().rstrip(".")
            offset = pos + m.end()
            piece_start = 0
            for sep in list(_SPLIT_RE.finditer(tail_clean)) + [None]:
                piece_end = sep.start() if sep else len(tail_clean)
                piece = tail_clean[piece_start:piece_end].strip()
                if piece:
                    a = offset + tail_clean.find(piece, piece_start)
                    items.append((piece, a, a + len(piece)))
                if sep:
                    piece_start = sep.end()
        return items

    @staticmethod
    def _strip_words(phrase: str) -> str:
        words = phrase.split()
        while words and words[0].lower() in _LEAD_STRIP:
            words.pop(0)
        while words and words[-1].lower() in _TRAIL_STRIP:
            words.pop()
        return " ".join(words)

    def _fuzzy(self, token: str) -> tuple[str, float] | None:
        key = token.lower()
        if key not in self._fuzzy_cache:
            res = self.taxonomy.fuzzy_match_token(key)
            self._fuzzy_cache[key] = (res[0].slug, res[1]) if res else None
        return self._fuzzy_cache[key]

    def _semantic(self, phrase: str) -> tuple[str, float] | None:
        if self.semantic is None:
            return None
        key = phrase.lower()
        if key not in self._sem_cache:
            m = self.semantic.match(key)
            self._sem_cache[key] = (m.entry.slug, m.score) if m else None
        return self._sem_cache[key]

    def _semantic_confidence(self, similarity: float) -> float:
        """Map a similarity that cleared the threshold to a confidence: threshold -> 0.58, +0.1 similarity -> +0.06."""
        threshold = self.semantic.threshold if self.semantic else 0.0
        return round(min(0.9, 0.58 + 0.6 * max(0.0, similarity - threshold)), 3)

    @staticmethod
    def _tech_like(phrase: str) -> bool:
        words = phrase.split()
        if not 1 <= len(words) <= 3 or len(phrase) > 30 or len(phrase) < 2:
            return False
        if any(w.lower() in _GENERIC_WORDS or w.lower() in _ENGLISH_STOP for w in words):
            return False
        return all(_TECH_LIKE_RE.match(w) for w in words) and not phrase.isdigit()

    # ------------------------------------------------------------------ public API
    def extract(self, text: str) -> ExtractionResult:
        """Extract skills (slug -> confidence, method) and candidate phrases from one posting."""
        result = ExtractionResult()
        if not text:
            return result
        toks = atoms(text)
        hits, spans = self._dictionary_hits(text, toks)
        candidates: list[str] = []

        for item, a, b in self._phrase_items(text):
            item_atoms = [t for t in atoms(item)]
            if not item_atoms:
                continue
            covered = sum(1 for t in item_atoms if any(s <= a + t.start and a + t.end <= e for s, e in spans))
            if covered * 2 >= len(item_atoms):
                continue  # already explained by the dictionary layer
            cleaned = self._strip_words(item)
            if not cleaned:
                continue
            # (a) phrase normalization: "the Django framework" -> Django
            entry = self.taxonomy.lookup(cleaned) or self.taxonomy.lookup_compact(cleaned)
            if entry:
                hits.append(Hit(entry.slug, 0.86, "ner", "ner", a, b))
                continue
            # (b) typo-tolerant match for single tokens: "Kubernets" -> Kubernetes
            words = cleaned.split()
            if len(words) == 1:
                fz = self._fuzzy(words[0])
                if fz:
                    hits.append(Hit(fz[0], round(min(0.88, fz[1] / 100 * 0.93), 3), "fuzzy", "fuzzy", a, b))
                    continue
            # (c) semantic similarity: "container orchestration" -> Kubernetes
            sem = self._semantic(cleaned) if len(cleaned) >= 6 else None
            if sem:
                hits.append(Hit(sem[0], self._semantic_confidence(sem[1]), "embedding", "embedding", a, b))
                continue
            # (d) technology-looking but unknown -> candidate for taxonomy review
            if self._tech_like(cleaned):
                candidates.append(cleaned)

        # merge hits per skill
        by_slug: dict[str, list[Hit]] = {}
        for h in hits:
            by_slug.setdefault(h.slug, []).append(h)
        for slug, group in by_slug.items():
            best = max(group, key=lambda h: h.confidence)
            layers = {h.layer for h in group}
            if len(layers) > 1:
                conf, method = min(0.99, best.confidence + 0.02 * (len(layers) - 1)), "hybrid"
            else:
                conf, method = best.confidence, best.method
            if conf >= self.min_conf:
                result.skills[slug] = (round(conf, 3), method)
        result.candidates = candidates
        return result


def count_candidates(results: list[tuple[int, ExtractionResult]]) -> dict[str, dict]:
    """Aggregate unknown technology phrases: phrase -> {mentions, first_year, last_year}."""
    stats: dict[str, dict] = {}
    for year, res in results:
        for phrase in set(res.candidates):
            s = stats.setdefault(phrase, {"mentions": 0, "first_year": year, "last_year": year})
            s["mentions"] += 1
            s["first_year"] = min(s["first_year"], year)
            s["last_year"] = max(s["last_year"], year)
    return stats


__all__ = ["ExtractionResult", "SkillExtractor", "count_candidates", "phrase_key", "Counter"]
