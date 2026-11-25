"""BambooHR public careers API (<company>.bamboohr.com/careers/list).

This is the JSON the company's own careers page loads (robots.txt allows it). The list has no description, date or
country for on-site/hybrid roles; enrich() fills them from /careers/<id>/detail for filtered candidates only.
"""

from __future__ import annotations

from ..companies import Company
from ..http import FetchError, PoliteClient
from ..models import Job
from ..text import extract_comp, html_to_text, parse_iso

API_NAME = "bamboohr"
REMOTE = "1"  # locationType: 0 on-site, 1 remote, 2 hybrid


def board_url(token: str) -> str:
    return f"https://{token}.bamboohr.com/careers/list"


def job_url(token: str, job_id: str) -> str:
    return f"https://{token}.bamboohr.com/careers/{job_id}"


def get_board(client: PoliteClient, token: str) -> dict:
    """Fetch the list. An unknown subdomain 302s to bamboohr.com's marketing site, so report that as a 404."""
    resp = client.request("GET", board_url(token))
    if resp.url.host != f"{token}.bamboohr.com":
        raise FetchError(f"no BambooHR board for {token}", 404)
    try:
        data = resp.json()
    except ValueError:
        raise FetchError(f"BambooHR board {token} did not return JSON", resp.status_code) from None
    if not isinstance(data, dict):
        raise FetchError(f"BambooHR board {token} returned unexpected JSON", resp.status_code)
    return data


def fetch(client: PoliteClient, company: Company) -> list[Job]:
    return [normalize(j, company) for j in get_board(client, company.token).get("result") or []]


def _place(*parts: str | None) -> str:
    return ", ".join(dict.fromkeys(p.strip() for p in parts if p and p.strip() and p.strip().lower() != "remote"))


def normalize(raw: dict, company: Company) -> Job:
    loc = raw.get("location") or {}
    ats = raw.get("atsLocation") or {}
    remote = str(raw.get("locationType")) == REMOTE or bool(raw.get("isRemote"))
    # On-site/hybrid roles fill `location` (no country); remote roles fill `atsLocation` (with country).
    location = _place(loc.get("city"), loc.get("state")) or _place(
        ats.get("city"), ats.get("state") or ats.get("province"), ats.get("country")
    )
    if remote:
        location = f"Remote - {location}" if location else "Remote"
    return Job(
        id=f"bamboohr:{company.token}:{raw['id']}",
        source=API_NAME,
        company=company.company,
        title=(raw.get("jobOpeningName") or "").strip(),
        location=location,
        url=job_url(company.token, raw["id"]),
        remote=remote,
        country=ats.get("country") or None,
        department=raw.get("departmentLabel"),
        description="",
        tier=company.tier,
    )


def enrich(client: PoliteClient, job: Job, company: Company) -> None:
    job_id = job.id.rsplit(":", 1)[1]
    data = client.get_json(f"{job_url(company.token, job_id)}/detail")
    opening = (data.get("result") or {}).get("jobOpening") or {}
    job.description = html_to_text(opening.get("description"))
    comp = opening.get("compensation")
    job.compensation = job.compensation or (str(comp).strip() if comp else None) or extract_comp(job.description)
    job.posted_at = job.posted_at or parse_iso(opening.get("datePosted"))
    job.country = job.country or (opening.get("location") or {}).get("addressCountry") or None
    if opening.get("jobOpeningShareUrl"):
        job.url = opening["jobOpeningShareUrl"]
