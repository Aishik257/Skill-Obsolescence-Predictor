"""Skill taxonomy loading and alias normalization.

The taxonomy CSV is the single source of truth for what counts as a skill. Every alias is
mapped to exactly one canonical skill, so "Postgres", "PostgreSQL DB" and "PostgreSQL"
always aggregate into one technology.

Alias markers in the CSV:
    ``Go!``     strict   - only counted with technology context (see skill_extraction)
    ``React~``  cased    - only counted when written with its exact capitalization
                           and not as the first word of a sentence
"""
from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.skill import Skill
from app.utils.text import phrase_key

logger = logging.getLogger(__name__)

MODE_PLAIN = "plain"
MODE_STRICT = "strict"
MODE_CASED = "cased"


@dataclass(frozen=True)
class AliasInfo:
    text: str
    key: str
    mode: str
    is_canonical: bool = False


@dataclass
class TaxonomyEntry:
    canonical: str
    slug: str
    category: str
    description: str
    aliases: list[str] = field(default_factory=list)  # display aliases, markers removed
    alias_infos: list[AliasInfo] = field(default_factory=list)

    @property
    def profile_text(self) -> str:
        """Text used to build the semantic profile of the skill."""
        return f"{self.canonical}. {self.category}. {self.description}. {' '.join(self.aliases)}"


class TaxonomyError(ValueError):
    """Raised when the taxonomy file is malformed or contains conflicting aliases."""


def slugify(name: str) -> str:
    s = name.lower().replace("++", "-plus-plus").replace("#", "-sharp").replace("+", "-plus")
    s = re.sub(r"[^a-z0-9.]+", "-", s).strip("-")
    return s


def _parse_alias(raw: str) -> tuple[str, str]:
    raw = raw.strip()
    if raw.endswith("!"):
        return raw[:-1].strip(), MODE_STRICT
    if raw.endswith("~"):
        return raw[:-1].strip(), MODE_CASED
    return raw, MODE_PLAIN


class Taxonomy:
    """In-memory view of the skill taxonomy with an alias index for O(1) phrase lookup."""

    def __init__(self, entries: list[TaxonomyEntry]):
        self.entries = entries
        self.by_slug = {e.slug: e for e in entries}
        self.by_canonical = {e.canonical.lower(): e for e in entries}
        self.alias_index: dict[str, tuple[TaxonomyEntry, AliasInfo]] = {}
        conflicts: list[str] = []
        for entry in entries:
            for info in entry.alias_infos:
                if not info.key:
                    continue
                existing = self.alias_index.get(info.key)
                if existing and existing[0] is not entry:
                    conflicts.append(f"'{info.text}' -> {existing[0].canonical} and {entry.canonical}")
                    continue
                if existing and existing[1].mode != MODE_PLAIN and info.mode == MODE_PLAIN:
                    continue  # a marked alias wins over the unmarked canonical form
                self.alias_index[info.key] = (entry, info)
        if conflicts:
            raise TaxonomyError("Conflicting aliases in taxonomy: " + "; ".join(conflicts))
        # compact (space-free) spellings of single-word aliases: "tensor flow" / "java script"
        self.compact_index: dict[str, tuple[TaxonomyEntry, AliasInfo]] = {
            k: v for k, v in self.alias_index.items() if " " not in k and len(k) >= 6 and v[1].mode == MODE_PLAIN
        }
        self.max_ngram = max((len(k.split()) for k in self.alias_index), default=1)
        self._fuzzy_keys = [k for k, (_, i) in self.alias_index.items() if i.mode == MODE_PLAIN and " " not in k and len(k) >= 6]

    def __len__(self) -> int:
        return len(self.entries)

    def lookup(self, text: str) -> TaxonomyEntry | None:
        """Exact alias lookup (case/punctuation-insensitive)."""
        hit = self.alias_index.get(phrase_key(text))
        return hit[0] if hit else None

    def lookup_compact(self, text: str) -> TaxonomyEntry | None:
        """Match spellings that only differ by spaces, e.g. "Tensor Flow"."""
        hit = self.compact_index.get(phrase_key(text).replace(" ", ""))
        return hit[0] if hit else None

    def resolve(self, text: str, fuzzy_cutoff: int = 88) -> TaxonomyEntry | None:
        """Resolve user-entered text to a skill: exact alias first, then fuzzy on single words."""
        entry = self.lookup(text)
        if entry:
            return entry
        key = phrase_key(text)
        if len(key) < 4 or not self._fuzzy_keys:
            return None
        match = process.extractOne(key, self._fuzzy_keys, scorer=fuzz.ratio, score_cutoff=fuzzy_cutoff)
        return self.alias_index[match[0]][0] if match else None

    def fuzzy_match_token(self, token: str) -> tuple[TaxonomyEntry, float] | None:
        """Typo-tolerant match of a single lowercase token against plain single-word aliases."""
        if len(token) < 6 or not self._fuzzy_keys:
            return None
        match = process.extractOne(token, self._fuzzy_keys, scorer=fuzz.ratio, score_cutoff=settings.FUZZY_THRESHOLD)
        if not match:
            return None
        key, score, _ = match
        if key == token:
            return None  # exact matches are handled by the dictionary layer
        # Typos only: reject when lengths differ a lot or the first letter differs.
        if abs(len(key) - len(token)) > 2 or key[0] != token[0]:
            return None
        return self.alias_index[key][0], float(score)


def load_taxonomy(path: Path | None = None) -> Taxonomy:
    """Parse the taxonomy CSV into a Taxonomy object."""
    path = path or settings.taxonomy_path
    if not path.exists():
        raise TaxonomyError(f"Skill taxonomy not found at {path}")
    entries: list[TaxonomyEntry] = []
    seen_slugs: set[str] = set()
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        required = {"canonical", "category", "aliases", "description"}
        if not required.issubset(reader.fieldnames or []):
            raise TaxonomyError(f"Taxonomy must have columns {sorted(required)}")
        for row in reader:
            canonical = (row["canonical"] or "").strip()
            if not canonical:
                continue
            slug = slugify(canonical)
            if slug in seen_slugs:
                raise TaxonomyError(f"Duplicate canonical skill '{canonical}'")
            seen_slugs.add(slug)
            entry = TaxonomyEntry(
                canonical=canonical,
                slug=slug,
                category=(row["category"] or "Other").strip(),
                description=(row["description"] or "").strip(),
            )
            canon_key = phrase_key(canonical)
            entry.alias_infos.append(AliasInfo(canonical, canon_key, MODE_PLAIN, is_canonical=True))
            for raw in (row["aliases"] or "").split("|"):
                text, mode = _parse_alias(raw)
                if not text:
                    continue
                key = phrase_key(text)
                if mode == MODE_PLAIN and key == canon_key:
                    continue
                if key == canon_key:  # marker on the canonical form, e.g. "Go!"
                    entry.alias_infos = [i for i in entry.alias_infos if i.key != canon_key]
                    entry.alias_infos.append(AliasInfo(canonical, key, mode, is_canonical=True))
                    continue
                entry.alias_infos.append(AliasInfo(text, key, mode))
                entry.aliases.append(text)
            entries.append(entry)
    logger.info("Loaded taxonomy with %d skills from %s", len(entries), path)
    return Taxonomy(entries)


@lru_cache(maxsize=1)
def get_taxonomy() -> Taxonomy:
    """Cached taxonomy for the configured path."""
    return load_taxonomy()


def clear_taxonomy_cache() -> None:
    get_taxonomy.cache_clear()


def sync_taxonomy(db: Session, taxonomy: Taxonomy | None = None) -> dict[str, int]:
    """Upsert Skill rows from the taxonomy. Aliases are stored on the skill, never as skills."""
    taxonomy = taxonomy or get_taxonomy()
    existing = {s.canonical_name: s for s in db.scalars(select(Skill))}
    created = updated = 0
    for entry in taxonomy.entries:
        skill = existing.get(entry.slug)
        if skill is None:
            db.add(Skill(name=entry.canonical, canonical_name=entry.slug, category=entry.category,
                         description=entry.description, aliases=entry.aliases))
            created += 1
        else:
            if (skill.name, skill.category, skill.description, skill.aliases) != (
                entry.canonical, entry.category, entry.description, entry.aliases
            ):
                skill.name, skill.category = entry.canonical, entry.category
                skill.description, skill.aliases = entry.description, entry.aliases
                updated += 1
    db.commit()
    return {"created": created, "updated": updated, "total": len(taxonomy)}
