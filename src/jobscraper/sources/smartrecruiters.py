"""SmartRecruiters public postings API. List has no description; enrich() fetches it for filtered candidates."""
from __future__ import annotations

from ..companies import Company
from ..http import PoliteClient
from ..models import Job
from ..text import extract_comp, html_to_text, parse_iso

API_NAME = "smartrecruiters"
PAGE = 100
MAX_PAGES = 20


def board_url(token: str, offset: int = 0, country: str | None = "us") -> str:
    url = f"https://api.smartrecruiters.com/v1/companies/{token}/postings?limit={PAGE}&offset={offset}"
    return url + (f"&country={country}" if country else "")


def fetch(client: PoliteClient, company: Company) -> list[Job]:
    country = company.extra.get("country", "us")  # set `country: null` in companies.yaml to fetch all countries
    jobs: list[Job] = []
    for page in range(MAX_PAGES):
        data = client.get_json(board_url(company.token, page * PAGE, country))
        content = data.get("content") or []
        jobs.extend(normalize(j, company) for j in content)
        if len(content) < PAGE or len(jobs) >= data.get("totalFound", 0):
            break
    return jobs


def normalize(raw: dict, company: Company) -> Job:
    loc = raw.get("location") or {}
    location = loc.get("fullLocation") or ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")]))
    location = location.replace(", ,", ",")
    ident = (raw.get("company") or {}).get("identifier") or company.token
    return Job(
        id=f"smartrecruiters:{company.token}:{raw['id']}",
        source=API_NAME,
        company=company.company,
        title=(raw.get("name") or "").strip(),
        location=location,
        url=f"https://jobs.smartrecruiters.com/{ident}/{raw['id']}",
        remote=bool(loc.get("remote")) if loc.get("remote") is not None else None,
        country=(loc.get("country") or "").upper() or None,
        posted_at=parse_iso(raw.get("releasedDate")),
        department=((raw.get("department") or {}).get("label") or (raw.get("function") or {}).get("label")),
        description="",
        tier=company.tier,
    )


def enrich(client: PoliteClient, job: Job, company: Company) -> None:
    posting_id = job.id.rsplit(":", 1)[1]
    data = client.get_json(f"https://api.smartrecruiters.com/v1/companies/{company.token}/postings/{posting_id}")
    sections = ((data.get("jobAd") or {}).get("sections") or {})
    parts = [html_to_text((sections.get(k) or {}).get("text")) for k in
             ("companyDescription", "jobDescription", "qualifications", "additionalInformation")]
    job.description = "\n".join(p for p in parts if p)
    job.compensation = job.compensation or extract_comp(job.description)
    if data.get("postingUrl"):
        job.url = data["postingUrl"]
