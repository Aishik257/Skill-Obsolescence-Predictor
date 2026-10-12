"""Synthetic job postings with *known* demand curves, so tests can check what the pipeline recovers."""
from __future__ import annotations

import csv
import io
import random
from datetime import date, timedelta

QUARTERS = [(y, q) for y in range(2019, 2026) for q in range(1, 5)]  # 28 quarters
JOBS_PER_QUARTER = 70
N = len(QUARTERS) - 1

CURVES = {  # skill -> share of postings at quarter index i (0..27)
    "Python": lambda i: 0.20 + 0.40 * i / N,
    "COBOL": lambda i: 0.30 - 0.27 * i / N,
    "Flash": lambda i: 0.22 - 0.21 * i / N,
    "Java": lambda i: 0.35,
    "Docker": lambda i: 0.10 + 0.40 * i / N,
    "Generative AI": lambda i: 0.0 if i < 15 else min(0.55, 0.03 + 0.045 * (i - 15)),
    "Git": lambda i: 0.50,
}
SURFACE = {"Python": ["Python", "Python3", "python"], "COBOL": ["COBOL", "Cobol"], "Flash": ["Adobe Flash", "Flash Player"],
           "Java": ["Java", "Core Java"], "Docker": ["Docker", "Docker containers"], "Generative AI": ["Generative AI", "GenAI"],
           "Git": ["Git", "GitHub"]}
ROLES_TITLES = ["Software Engineer", "Backend Developer", "Data Scientist", "DevOps Engineer", "Frontend Developer"]
INDUSTRIES = ["FinTech", "Healthcare", "Banking", "Technology"]


def build_rows(seed: int = 1, per_quarter: int = JOBS_PER_QUARTER) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    n = 0
    for i, (y, q) in enumerate(QUARTERS):
        start = date(y, 3 * q - 2, 1)
        for _ in range(per_quarter):
            n += 1
            skills = [s for s, f in CURVES.items() if rng.random() < f(i)]
            mention = ", ".join(rng.choice(SURFACE[s]) for s in skills) or "strong communication"
            company = f"Company {rng.randrange(300)} {rng.choice(['Labs', 'Group', 'Systems'])}"
            rows.append({
                "job_id": f"T-{n:05d}", "title": rng.choice(ROLES_TITLES), "company": company,
                "location": rng.choice(["London, United Kingdom", "Bengaluru, India", "Austin, TX", "Berlin, Germany"]),
                "description": f"<p>We need a engineer #{n}. Experience with {mention}. Reference {rng.randrange(10**6)}.</p>",
                "industry": rng.choice(INDUSTRIES), "employment_type": "Full-time",
                "posted_date": (start + timedelta(days=rng.randrange(85))).isoformat(), "source": "test",
            })
    return rows


COLUMNS = ["job_id", "title", "company", "location", "description", "industry", "employment_type", "posted_date", "source"]


def to_csv(rows: list[dict], columns: list[str] | None = None) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns or COLUMNS, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def row(**over) -> dict:
    base = {"job_id": "J1", "title": "Python Developer", "company": "Acme", "location": "Austin, TX",
            "description": "We use Python and Docker.", "industry": "Technology", "employment_type": "Full-time",
            "posted_date": "2024-05-10", "source": "test"}
    base.update(over)
    return base
