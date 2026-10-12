"""Shared FastAPI dependencies: filters, pagination."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import Query

from app.core.errors import UnprocessableError
from app.services.analysis_data import Filters
from app.utils.roles import ROLES


def get_filters(
    role: str | None = Query(None, description="Job role, e.g. 'Data Scientist'"),
    industry: str | None = Query(None, description="Industry, e.g. 'FinTech'"),
    country: str | None = Query(None), region: str | None = Query(None), city: str | None = Query(None),
    year: int | None = Query(None, ge=2000, le=2100, description="Restrict to one calendar year"),
    date_from: date | None = Query(None), date_to: date | None = Query(None),
) -> Filters:
    """Parse the common data filters shared by every analytics endpoint."""
    if role and role not in ROLES:
        raise UnprocessableError(f"Unknown role '{role}'. Valid roles: {', '.join(ROLES)}.")
    if date_from and date_to and date_from > date_to:
        raise UnprocessableError("date_from must not be after date_to.")
    if year and not (date_from or date_to):
        date_from, date_to = date(year, 1, 1), date(year, 12, 31)
    return Filters(role=role, industry=industry, country=country, region=region, city=city,
                   date_from=date_from, date_to=date_to)


@dataclass
class Pagination:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def get_pagination(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=500)) -> Pagination:
    return Pagination(page, page_size)


def paginate(items: list, p: Pagination) -> dict:
    total = len(items)
    return {"items": items[p.offset:p.offset + p.page_size], "total": total, "page": p.page,
            "page_size": p.page_size, "pages": max(1, -(-total // p.page_size))}
