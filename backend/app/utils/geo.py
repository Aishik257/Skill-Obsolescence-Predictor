"""Light-weight location parsing: free text -> (city, country, region)."""
from __future__ import annotations

import re
from typing import NamedTuple

REGIONS = ["North America", "Europe", "Asia-Pacific", "Latin America", "Middle East & Africa"]


class Place(NamedTuple):
    city: str | None
    country: str | None
    region: str | None


_COUNTRY_REGION: dict[str, str] = {
    "United States": "North America", "Canada": "North America", "Mexico": "Latin America",
    "United Kingdom": "Europe", "Germany": "Europe", "France": "Europe", "Netherlands": "Europe",
    "Spain": "Europe", "Ireland": "Europe", "Poland": "Europe", "Sweden": "Europe", "Switzerland": "Europe",
    "Italy": "Europe", "India": "Asia-Pacific", "Singapore": "Asia-Pacific", "Australia": "Asia-Pacific",
    "Japan": "Asia-Pacific", "China": "Asia-Pacific", "Philippines": "Asia-Pacific",
    "Brazil": "Latin America", "Argentina": "Latin America", "Colombia": "Latin America",
    "United Arab Emirates": "Middle East & Africa", "Israel": "Middle East & Africa",
    "South Africa": "Middle East & Africa", "Nigeria": "Middle East & Africa", "Egypt": "Middle East & Africa",
}

_COUNTRY_ALIASES: dict[str, str] = {
    "us": "United States", "usa": "United States", "u.s.": "United States", "u.s.a.": "United States",
    "united states": "United States", "united states of america": "United States", "america": "United States",
    "uk": "United Kingdom", "u.k.": "United Kingdom", "united kingdom": "United Kingdom",
    "england": "United Kingdom", "scotland": "United Kingdom", "great britain": "United Kingdom",
    "uae": "United Arab Emirates", "holland": "Netherlands", "deutschland": "Germany",
}
_COUNTRY_ALIASES.update({c.lower(): c for c in _COUNTRY_REGION})

_US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY",
    "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND",
    "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}
_CA_PROVINCES = {"ON", "BC", "QC", "AB", "MB", "NS", "NB"}

_CITY_COUNTRY: dict[str, str] = {
    "san francisco": "United States", "new york": "United States", "seattle": "United States",
    "austin": "United States", "boston": "United States", "chicago": "United States", "atlanta": "United States",
    "denver": "United States", "los angeles": "United States", "bengaluru": "India", "bangalore": "India",
    "hyderabad": "India", "pune": "India", "mumbai": "India", "chennai": "India", "gurgaon": "India",
    "delhi": "India", "london": "United Kingdom", "manchester": "United Kingdom", "berlin": "Germany",
    "munich": "Germany", "paris": "France", "amsterdam": "Netherlands", "dublin": "Ireland",
    "madrid": "Spain", "warsaw": "Poland", "stockholm": "Sweden", "zurich": "Switzerland",
    "toronto": "Canada", "vancouver": "Canada", "montreal": "Canada", "sydney": "Australia",
    "melbourne": "Australia", "singapore": "Singapore", "tokyo": "Japan", "sao paulo": "Brazil",
    "mexico city": "Mexico", "dubai": "United Arab Emirates", "tel aviv": "Israel", "cape town": "South Africa",
}

_REMOTE_RE = re.compile(r"\bremote\b", re.I)


def parse_location(location: str | None) -> Place:
    """Parse "City, Country" / "City, ST" / "Remote - Country" style strings.

    Unknown pieces come back as None so analytics can exclude them instead of guessing.
    """
    if not location or not location.strip():
        return Place(None, None, None)
    raw = location.strip()
    parts = [p.strip() for p in re.split(r"[,|;/]| - ", raw) if p.strip()]
    city: str | None = None
    country: str | None = None

    for part in reversed(parts):
        key = part.lower().rstrip(".")
        if key in _COUNTRY_ALIASES:
            country = _COUNTRY_ALIASES[key]
            break
        if part.upper() in _US_STATES and len(parts) > 1:
            country = "United States"
            break
        if part.upper() in _CA_PROVINCES and len(parts) > 1:
            country = "Canada"
            break

    for part in parts:
        key = part.lower()
        if _REMOTE_RE.fullmatch(part):
            city = "Remote"
            continue
        if key in _COUNTRY_ALIASES or part.upper() in _US_STATES or part.upper() in _CA_PROVINCES:
            continue
        city = part.title()  # a real city name replaces a "Remote" marker
        if country is None and key in _CITY_COUNTRY:
            country = _CITY_COUNTRY[key]
        break

    if city is None and country is None:
        return Place(None, None, None)
    region = _COUNTRY_REGION.get(country) if country else None
    return Place(city, country, region)
