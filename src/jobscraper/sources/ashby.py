from __future__ import annotations

from ..companies import Company
from ..http import PoliteClient
from ..models import Job
from ..text import extract_comp, html_to_text, parse_iso

API_NAME = "ashby"


def board_url(token: str) -> str:
    return f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"


def fetch(client: PoliteClient, company: Company) -> list[Job]:
    data = client.get_json(board_url(company.token))
    return [normalize(j, company) for j in data.get("jobs", []) if j.get("isListed", True)]


def _location(raw: dict) -> str:
    names = [raw.get("location") or ""]
    for sec in raw.get("secondaryLocations") or []:
        names.append(sec.get("location") or "")
    return "; ".join(n for n in names if n)


def normalize(raw: dict, company: Company) -> Job:
    location = _location(raw)
    country = ((raw.get("address") or {}).get("postalAddress") or {}).get("addressCountry")
    description = raw.get("descriptionPlain") or html_to_text(raw.get("descriptionHtml"))
    comp = raw.get("compensation") or {}
    comp_str = comp.get("compensationTierSummary") or comp.get("scrapeableCompensationSalarySummary")
    wt = (raw.get("workplaceType") or "").lower()
    remote = raw.get("isRemote")
    if remote is None and wt:
        remote = wt == "remote"
    dept = raw.get("department")
    if raw.get("team") and raw.get("team") != dept:
        dept = f"{dept} / {raw['team']}" if dept else raw["team"]
    return Job(
        id=f"ashby:{company.token}:{raw['id']}",
        source=API_NAME,
        company=company.company,
        title=(raw.get("title") or "").strip(),
        location=location,
        url=raw.get("jobUrl") or "",
        remote=remote,
        country=country,
        posted_at=parse_iso(raw.get("publishedAt")),
        updated_at=None,
        compensation=comp_str or extract_comp(description),
        department=dept,
        description=description,
        tier=company.tier,
    )
