"""Workable public widget API (apply.workable.com/<account>)."""
from __future__ import annotations

from ..companies import Company
from ..http import PoliteClient
from ..models import Job
from ..text import extract_comp, html_to_text, parse_iso

API_NAME = "workable"


def board_url(token: str) -> str:
    return f"https://apply.workable.com/api/v1/widget/accounts/{token}?details=true"


def fetch(client: PoliteClient, company: Company) -> list[Job]:
    data = client.get_json(board_url(company.token))
    return [normalize(j, company) for j in data.get("jobs", [])]


def normalize(raw: dict, company: Company) -> Job:
    locs = raw.get("locations") or []
    names = []
    for l in locs or [raw]:
        names.append(", ".join(filter(None, [l.get("city"), l.get("region") or l.get("state"), l.get("country")])))
    location = "; ".join(dict.fromkeys(n for n in names if n))
    codes = {l.get("countryCode") for l in locs if l.get("countryCode")}
    country = "US" if "US" in codes else (next(iter(codes)) if codes else raw.get("country"))
    remote = raw.get("telecommuting")
    if remote and "remote" not in location.lower():
        location = f"Remote - {location}" if location else "Remote"
    description = html_to_text(raw.get("description"))
    return Job(
        id=f"workable:{company.token}:{raw['shortcode']}",
        source=API_NAME,
        company=company.company,
        title=(raw.get("title") or "").strip(),
        location=location,
        url=raw.get("url") or raw.get("shortlink") or "",
        remote=bool(remote) if remote is not None else None,
        country=country,
        posted_at=parse_iso(raw.get("published_on") or raw.get("created_at")),
        compensation=extract_comp(description),
        department=raw.get("department") or raw.get("function"),
        description=description,
        tier=company.tier,
    )
