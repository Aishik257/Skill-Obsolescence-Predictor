"""Data-grounded explanations. Every sentence is templated from stored metrics - no free generation."""
from __future__ import annotations

from app.services.obsolescence import ScoreResult
from app.services.trend_analysis import STATUS_LABELS

LIMITATIONS = [
    "Job-posting trends are a proxy for market demand and do not perfectly represent the entire technology labor market.",
    "A declining mention rate does not necessarily mean that a technology is technically obsolete.",
    "Predictions are estimates based on historical data and should not be interpreted as guaranteed future outcomes.",
]


def pct(x: float | None, signed: bool = True) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:+.0f}%" if signed else f"{x * 100:.0f}%"


def share(x: float) -> str:
    return f"{x * 100:.1f}%"


def _top_roles_text(top_roles: list[dict]) -> str:
    names = [r["role"] for r in top_roles[:3]]
    return ", ".join(names[:-1]) + (" and " if len(names) > 1 else "") + names[-1] if names else ""


def recommendation(status: str, name: str, risk: str | None, top_roles: list[dict], replacements: list[dict]) -> str:
    roles = _top_roles_text(top_roles)
    where = f" It is most requested in {roles} postings." if roles else ""
    if status == "emerging":
        return (f"{name} is a young, fast-growing skill in this data.{where} Worth learning early if it fits your "
                f"direction, but treat the history as short.")
    if status == "growing":
        return f"{name} is gaining share of postings and remains a strong skill to build or deepen.{where}"
    if status == "stable":
        return f"{name} shows no significant shift in demand, so it stays a dependable skill rather than a bet on a trend.{where}"
    if status in ("declining", "at_risk"):
        alt = ", ".join(r["name"] for r in replacements[:3])
        tail = f" Growing alternatives to explore: {alt} (a market transition signal, not proof of causation)." if alt else ""
        verb = "has a high risk of losing market demand" if risk in ("HIGH", "CRITICAL") else "is losing share of postings"
        return f"{name} {verb}. Keep it if your role depends on it, but avoid making it your only specialty.{tail}"
    return f"There is not enough history or mentions to say anything reliable about {name}."


def build_explanation(*, name: str, category: str, status: str, rules: list[dict], metrics: dict | None,
                      forecast: dict | None, score: ScoreResult | None, top_roles: list[dict],
                      replacements: list[dict], as_of: str | None) -> dict:
    """Assemble the structured explanation shown on the skill page (all values come from ``metrics``)."""
    label = STATUS_LABELS.get(status, status)
    if metrics is None:
        return {"headline": f"{name}: insufficient data", "status": status, "status_label": label,
                "summary": f"{name} appears too rarely, or over too short a period, for a trend to be measured.",
                "bullets": [], "recommendation": recommendation(status, name, None, top_roles, replacements),
                "rules": rules, "limitations": LIMITATIONS}
    m = metrics
    first, cur = m["first_demand"], m["current_demand"]
    first_period = m["first_period"].split("-")[0]
    last_period = m["last_period"]
    summary = (f"Demand moved from {share(first)} of postings in {first_period} to {share(cur)} in the 12 months to "
               f"{last_period} ({'+' if m['pp_change'] >= 0 else ''}{m['pp_change'] * 100:.1f} percentage points).")
    bullets = [
        f"Long-term change: {pct(m['long_term_growth'])} over {m['years_span']:.1f} years (CAGR {pct(m['cagr'])})",
        f"Last 12 months vs the 12 before: {pct(m['yoy_growth'])}; recent momentum {pct(m['momentum'])} per year",
        f"Trend significance: first-year vs latest-year difference p={m['p_long']:.3g}; Kendall tau {m['kendall_tau']:+.2f}",
        f"Currently held below its peak by {pct(1 - m['persistence'], signed=False)} (peak {share(m['peak_demand'])} in {m['peak_period']})"
        if m["persistence"] < 0.95 else f"Currently at or near its peak demand ({share(m['peak_demand'])})",
    ]
    if forecast and forecast.get("status") == "ok":
        bullets.append(f"Forecast ({forecast['model']}): {share(forecast['y1'])} in 1 year, {share(forecast['y2'])} in 2 years "
                       f"({pct(forecast['change_2y'])} vs today), {share(forecast['y3'])} in 3 years")
    else:
        bullets.append("Forecast: insufficient historical data")
    if replacements and status in ("declining", "at_risk"):
        bullets.append("Potential replacement trend: " + ", ".join(f"{r['name']} ({pct(r['grower_change'])})" for r in replacements[:3]))
    out = {"headline": f"{name}: {label}", "status": status, "status_label": label, "summary": summary, "bullets": bullets,
           "recommendation": recommendation(status, name, score.risk_level if score else None, top_roles, replacements),
           "rules": rules, "limitations": LIMITATIONS, "as_of": as_of, "category": category}
    if score:
        out["score_breakdown"] = [{"component": k, **v} for k, v in score.components.items()]
        out["risk_text"] = f"Obsolescence score {score.score:.0f}/100 - {score.risk_level} risk, {score.confidence_label.lower()} confidence ({score.confidence * 100:.0f}%)"
        out["confidence_reasons"] = score.confidence_reasons
        out["score_notes"] = score.notes
    return out


def market_outlook(rows: list[dict], total_jobs: int, date_min: str | None, date_max: str | None) -> dict:
    """Dashboard 'Market Outlook' text, computed only from the rows shown on the dashboard."""
    assessed = [r for r in rows if r["trend_status"] != "insufficient_data"]
    if not assessed:
        return {"headline": "Not enough data for an outlook yet.", "bullets": []}
    by = lambda *st: [r for r in assessed if r["trend_status"] in st]  # noqa: E731
    rising, falling = by("growing", "emerging"), by("declining", "at_risk")
    bullets = [f"{len(rising)} of {len(assessed)} assessed skills are growing or emerging; {len(falling)} are declining or at risk "
               f"(based on {total_jobs:,} postings, {date_min} to {date_max})."]
    big = sorted([r for r in rising if r.get("current_demand", 0) >= 0.05], key=lambda r: -(r.get("growth_rate") or 0))[:3]
    if big:
        bullets.append("Largest gains among established skills: " + ", ".join(
            f"{r['name']} ({pct(r.get('growth_rate'))})" for r in big) + ".")
    emerging = sorted(by("emerging"), key=lambda r: -r.get("current_demand", 0))[:4]
    if emerging:
        bullets.append("Emerging technologies: " + ", ".join(f"{r['name']} ({share(r['current_demand'])} of postings)" for r in emerging) + ".")
    risky = sorted([r for r in assessed if r.get("obsolescence_score") is not None], key=lambda r: -r["obsolescence_score"])[:3]
    if risky and risky[0]["obsolescence_score"] >= 50:
        bullets.append("Highest obsolescence risk: " + ", ".join(
            f"{r['name']} ({r['obsolescence_score']:.0f}/100)" for r in risky if r["obsolescence_score"] >= 50) + ".")
    return {"headline": "Demand is shifting toward " + (rising and sorted(rising, key=lambda r: -r.get("current_demand", 0))[0]["category"].lower() or "no clear category") + " skills.",
            "bullets": bullets}
