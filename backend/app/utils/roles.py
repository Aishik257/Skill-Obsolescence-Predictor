"""Map free-text job titles onto a fixed set of analysis roles."""
from __future__ import annotations

import re

ROLES: list[str] = [
    "Software Engineer",
    "Backend Developer",
    "Frontend Developer",
    "Data Scientist",
    "Data Analyst",
    "ML Engineer",
    "DevOps Engineer",
    "Cloud Engineer",
    "Cybersecurity Analyst",
]
OTHER_ROLE = "Other"

# Order matters: the first matching rule wins, so specific roles come before generic ones.
_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("ML Engineer", re.compile(r"\b(ml|machine learning|ai|deep learning|mlops|nlp|computer vision|applied scientist|llm|genai)\b.*\b(engineer|developer|specialist|scientist)\b|\bml ?ops\b|\bapplied scientist\b", re.I)),
    ("Data Scientist", re.compile(r"\bdata scien", re.I)),
    ("Data Analyst", re.compile(r"\b(data|business intelligence|bi|analytics|reporting) (analyst|analytics)\b|\bbi (developer|analyst)\b|\banalytics engineer\b|\bbusiness analyst\b", re.I)),
    ("DevOps Engineer", re.compile(r"\b(devops|site reliability|sre|platform engineer|release engineer|build engineer|infrastructure engineer)\b", re.I)),
    ("Cloud Engineer", re.compile(r"\bcloud\b", re.I)),
    ("Cybersecurity Analyst", re.compile(r"\b(security|cyber|infosec|soc analyst|penetration|pentest)\b", re.I)),
    ("Frontend Developer", re.compile(r"\b(front[- ]?end|ui (engineer|developer)|react developer|web ui|angular developer|vue developer)\b", re.I)),
    ("Backend Developer", re.compile(r"\b(back[- ]?end|server[- ]side|api (developer|engineer)|java developer|python developer|\.net developer|php developer)\b", re.I)),
    ("Software Engineer", re.compile(r"\b(software|full[- ]?stack|application|programmer|developer|swe|engineer)\b", re.I)),
]


def normalize_role(title: str | None) -> str:
    """Return the analysis role for a job title, or "Other" when nothing matches."""
    if not title:
        return OTHER_ROLE
    for role, pattern in _RULES:
        if pattern.search(title):
            return role
    return OTHER_ROLE
