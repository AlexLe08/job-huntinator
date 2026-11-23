"""Recruitee public offers API (<company>.recruitee.com/api/offers/)."""

from __future__ import annotations

from ..companies import Company
from ..http import PoliteClient
from ..models import Job
from ..text import extract_comp, fmt_money, html_to_text, parse_iso

API_NAME = "recruitee"


def board_url(token: str) -> str:
    return f"https://{token}.recruitee.com/api/offers/"


def fetch(client: PoliteClient, company: Company) -> list[Job]:
    data = client.get_json(board_url(company.token))
    return [normalize(j, company) for j in data.get("offers", []) if j.get("status", "published") == "published"]


def _salary(s: dict | None) -> str | None:
    if not s or (s.get("min") is None and s.get("max") is None):
        return None
    try:
        lo, hi = float(s["min"]) if s.get("min") else None, float(s["max"]) if s.get("max") else None
    except (TypeError, ValueError):
        return None
    return " ".join(filter(None, [f"{fmt_money(lo)}–{fmt_money(hi)}", s.get("currency"), s.get("period")]))


def normalize(raw: dict, company: Company) -> Job:
    locs = raw.get("locations") or []
    location = (
        "; ".join(
            dict.fromkeys(
                ", ".join(filter(None, [l.get("city") or l.get("name"), l.get("state"), l.get("country")]))
                for l in locs
            )
        )
        or raw.get("location")
        or ""
    )
    if raw.get("remote") and "remote" not in location.lower():
        location = f"Remote - {location}" if location else "Remote"
    description = "\n".join(filter(None, [html_to_text(raw.get("description")), html_to_text(raw.get("requirements"))]))
    published = (raw.get("published_at") or raw.get("created_at") or "").replace(" UTC", "+00:00")
    return Job(
        id=f"recruitee:{company.token}:{raw['id']}",
        source=API_NAME,
        company=company.company,
        title=(raw.get("title") or "").strip(),
        location=location,
        url=raw.get("careers_url") or "",
        remote=raw.get("remote"),
        country=raw.get("country_code"),
        posted_at=parse_iso(published.replace(" ", "T", 1) if published else None),
        compensation=_salary(raw.get("salary")) or extract_comp(description),
        department=raw.get("department"),
        description=description,
        tier=company.tier,
    )
