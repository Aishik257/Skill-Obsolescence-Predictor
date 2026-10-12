"""Text cleaning and tokenization helpers shared by cleaning and extraction."""
from __future__ import annotations

import html
import re
import unicodedata
from typing import NamedTuple

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1>", re.I | re.S)
_BLOCK_TAG_RE = re.compile(r"</?(p|div|br|li|ul|ol|h[1-6]|tr|td|table)\b[^>]*>", re.I)
_CONTROL_RE = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f​-‏⁠﻿]")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")
_SENIORITY_RE = re.compile(
    r"\b(senior|sr|junior|jr|lead|staff|principal|associate|entry[- ]level|intern|trainee|"
    r"i{1,3}|iv|v|level \d)\b\.?",
    re.I,
)
_COMPANY_SUFFIX_RE = re.compile(
    r"\b(inc|llc|ltd|limited|gmbh|corp|corporation|co|plc|pvt|private|pty|sa|ag|bv)\b\.?", re.I
)

_CHAR_MAP = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "•": "-", "·": "-", "●": "-",
    "…": "...", " ": " ",
}


def strip_html(text: str) -> str:
    """Remove scripts/styles and tags, turning block tags into newlines, and unescape entities."""
    text = _SCRIPT_RE.sub(" ", text)
    text = _BLOCK_TAG_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    return html.unescape(text)


def clean_text(text: str | None) -> str:
    """Return case-preserving, HTML-free, Unicode-normalized, whitespace-collapsed text.

    Case is preserved on purpose: the skill extractor needs it to disambiguate words such
    as "Go" (language) from "go" (verb). Lowercasing is applied where matching needs it.
    """
    if not text:
        return ""
    text = strip_html(str(text))
    text = unicodedata.normalize("NFKC", text)
    for src, dst in _CHAR_MAP.items():
        text = text.replace(src, dst)
    text = _CONTROL_RE.sub("", text)
    text = _WS_RE.sub(" ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text.strip()


def normalize_title(title: str | None) -> str:
    """Lowercase a job title and strip seniority markers / punctuation for duplicate matching."""
    if not title:
        return ""
    t = unicodedata.normalize("NFKC", html.unescape(title)).lower()
    t = _SENIORITY_RE.sub(" ", t)
    t = re.sub(r"[^a-z0-9+#/ ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def normalize_company(company: str | None) -> str:
    """Lowercase a company name and drop legal suffixes."""
    if not company:
        return ""
    c = unicodedata.normalize("NFKC", html.unescape(company)).lower()
    c = _COMPANY_SUFFIX_RE.sub(" ", c)
    c = re.sub(r"[^a-z0-9 ]+", " ", c)
    return re.sub(r"\s+", " ", c).strip()


def sanitize_cell(value: object, max_len: int = 5000) -> str | None:
    """Sanitize an uploaded CSV cell: strip control chars and cap its length."""
    if value is None:
        return None
    s = str(value)
    if s.lower() in {"nan", "none", "null", "nat"}:
        return None
    s = _CONTROL_RE.sub("", s).strip()
    return s[:max_len] if s else None


# --- tokenization for skill matching -------------------------------------
# An "atom" is an alphanumeric token that may contain inner dots (Node.js, ASP.NET), a
# leading dot (.NET) and a trailing +/# (C++, C#). Hyphens, slashes and underscores split
# atoms, so "scikit-learn" and "CI/CD" become two atoms each and are matched as phrases.
ATOM_RE = re.compile(r"\.?[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*(?:\+\+|\+|#)?")


class Atom(NamedTuple):
    text: str
    lower: str
    start: int
    end: int


def atoms(text: str) -> list[Atom]:
    """Tokenize text into atoms (see ATOM_RE)."""
    out: list[Atom] = []
    for m in ATOM_RE.finditer(text):
        tok = m.group(0)
        out.append(Atom(tok, tok.lower(), m.start(), m.end()))
    return out


def phrase_key(text: str) -> str:
    """Canonical lookup key for an alias or phrase: lowercase atoms joined by a space."""
    return " ".join(a.lower for a in atoms(text))
