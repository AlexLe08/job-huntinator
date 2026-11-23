from __future__ import annotations

from ..companies import Company
from ..http import PoliteClient
from ..models import Job
from ..text import extract_comp, html_to_text, parse_iso

API_NAME = "greenhouse"
PLACEHOLDER_LOCATIONS = {"", "na", "n/a", "location", "tbd", "various", "multiple", "multiple locations", "-"}


def board_url(token: str) -> str:
    return f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"


def fetch(client: PoliteClient, company: Company) -> list[Job]:
    data = client.get_json(board_url(company.token))
    return [normalize(j, company) for j in data.get("jobs", [])]


def normalize(raw: dict, company: Company) -> Job:
    location = ((raw.get("location") or {}).get("name") or "").strip()
    offices = [o.get("location") or o.get("name") for o in raw.get("offices") or [] if o]
    if location.lower() in PLACEHOLDER_LOCATIONS:
        location = "; ".join(filter(None, offices))
    description = html_to_text(raw.get("content"), unescape_first=True)
    depts = [d.get("name") for d in raw.get("departments") or [] if d.get("name")]
    return Job(
        id=f"greenhouse:{company.token}:{raw['id']}",
        source=API_NAME,
        company=company.company,
        title=(raw.get("title") or "").replace("\xa0", " ").strip(),
        location=location,
        url=raw.get("absolute_url") or "",
        remote=True if "remote" in location.lower() else None,
        posted_at=parse_iso(raw.get("first_published")),
        updated_at=parse_iso(raw.get("updated_at")),
        compensation=extract_comp(description),
        department=", ".join(depts) or None,
        description=description,
        tier=company.tier,
    )
