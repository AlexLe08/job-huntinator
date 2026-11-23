"""Workday career sites via the (undocumented, unauthenticated) CXS JSON endpoint the sites themselves use.

companies.yaml entry:
  - {company: Red Hat, ats: workday, token: redhat, host: redhat.wd5.myworkdayjobs.com, site: jobs, tier: rtp}
`token` is the tenant (the path segment after /wday/cxs/), `site` is the career-site name in the public URL.
Large employers have thousands of postings, so we run a few keyword searches instead of paging everything.
This endpoint may change without notice; failures are logged per company and never stop the run.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit
from datetime import datetime, timedelta, timezone

from ..companies import Company
from ..http import PoliteClient
from ..models import Job
from ..text import extract_comp, html_to_text, parse_iso

API_NAME = "workday"
PAGE = 20  # Workday rejects larger pages
MAX_PAGES_PER_QUERY = 5
DEFAULT_QUERIES = ["frontend", "front end", "software engineer", "web developer", "ui engineer", "full stack"]


def _base(company: Company) -> tuple[str, str]:
    host, site = company.extra.get("host"), company.extra.get("site")
    if not host or not site:
        raise ValueError(f"workday company {company.company} needs host and site in companies.yaml")
    return host, site


def board_url(company: Company) -> str:
    host, site = _base(company)
    return f"https://{host}/wday/cxs/{company.token}/{site}/jobs"


def parse_posted_on(text: str | None, now: datetime | None = None) -> datetime | None:
    """'Posted Today' / 'Posted Yesterday' / 'Posted 3 Days Ago' / 'Posted 30+ Days Ago' -> approximate datetime."""
    if not text:
        return None
    now = now or datetime.now(timezone.utc)
    t = text.lower()
    if "today" in t:
        return now
    if "yesterday" in t:
        return now - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*days?", t)
    return now - timedelta(days=int(m.group(1))) if m else None


def fetch(client: PoliteClient, company: Company, now: datetime | None = None) -> list[Job]:
    queries = company.extra.get("queries") or DEFAULT_QUERIES
    url = board_url(company)
    seen: dict[str, Job] = {}
    for q in queries:
        for page in range(MAX_PAGES_PER_QUERY):
            data = client.post_json(url, {"appliedFacets": {}, "limit": PAGE, "offset": page * PAGE, "searchText": q})
            postings = data.get("jobPostings") or []
            for raw in postings:
                if raw.get("externalPath") and raw["externalPath"] not in seen:
                    seen[raw["externalPath"]] = normalize(raw, company, now)
            if len(postings) < PAGE:
                break
    return list(seen.values())


def normalize(raw: dict, company: Company, now: datetime | None = None) -> Job:
    host, site = _base(company)
    path = raw["externalPath"]
    req = (raw.get("bulletFields") or [None])[0] or path.rsplit("_", 1)[-1]
    location = raw.get("locationsText") or ""
    remote_type = (raw.get("remoteType") or "").lower()
    if remote_type == "remote" and "remote" not in location.lower():
        location = f"Remote - {location}"
    return Job(
        id=f"workday:{company.token}:{req}",
        source=API_NAME,
        company=company.company,
        title=(raw.get("title") or "").strip(),
        location=location,
        url=f"https://{host}/{site}{path}",
        remote=True if remote_type == "remote" else (False if remote_type in ("onsite", "on-site", "hybrid") else None),
        posted_at=parse_posted_on(raw.get("postedOn"), now),
        description="",
        tier=company.tier,
    )


def enrich(client: PoliteClient, job: Job, company: Company) -> None:
    host, site = _base(company)
    path = urlsplit(job.url).path.removeprefix(f"/{site}")
    data = client.get_json(f"https://{host}/wday/cxs/{company.token}/{site}{path}")
    info = data.get("jobPostingInfo") or {}
    job.description = html_to_text(info.get("jobDescription"))
    job.compensation = job.compensation or extract_comp(job.description)
    if info.get("location") and info.get("additionalLocations"):
        job.location = "; ".join([info["location"], *info["additionalLocations"]])
    if info.get("country", {}).get("descriptor"):
        job.country = info["country"]["descriptor"]
    if info.get("externalUrl"):
        job.url = info["externalUrl"]
    if info.get("startDate"):  # exact posting date, better than the "Posted N Days Ago" estimate
        job.posted_at = parse_iso(info["startDate"] + "T12:00:00+00:00") or job.posted_at
