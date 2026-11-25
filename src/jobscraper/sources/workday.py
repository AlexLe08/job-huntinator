"""Workday career sites via the (undocumented, unauthenticated) CXS JSON endpoint the sites themselves use.

companies.yaml entry:
  - {company: Red Hat, ats: workday, token: redhat, host: redhat.wd5.myworkdayjobs.com, site: jobs, tier: rtp}
`token` is the tenant (the path segment after /wday/cxs/), `site` is the career-site name in the public URL.
Large employers have thousands of postings, so we run a few keyword searches instead of paging everything.
This endpoint may change without notice; failures are logged per company and never stop the run.

Cloudflare in front of *.myworkdayjobs.com rate-limits datacenter IPs (GitHub runners get 429 on the first request
to nearly every board). Two consequences handled here:
* if a later query fails, the jobs from earlier queries are kept (`PartialFetch`) instead of dropping the board;
* after `BLOCK_THRESHOLD` consecutive boards whose first request got 429, the remaining boards on the same client
  are skipped without a request (`WorkdayBlocked`), instead of burning retry backoff on each.
"""

from __future__ import annotations

import logging
import re
import threading
import weakref
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from ..companies import Company
from ..http import FetchError, PartialFetch, PoliteClient
from ..models import Job
from ..text import extract_comp, html_to_text, parse_iso

API_NAME = "workday"
PAGE = 20  # Workday rejects larger pages
MAX_PAGES_PER_QUERY = 5
DEFAULT_QUERIES = ["frontend", "front end", "software engineer", "web developer", "ui engineer", "full stack"]
BLOCK_THRESHOLD = 3  # consecutive first-request 429s before the rest of the Workday boards are skipped

log = logging.getLogger(__name__)


class WorkdayBlocked(FetchError):
    """Skipped without a request: earlier Workday boards on this client all got 429 on their first request."""


class _Breaker:
    """Counts consecutive boards whose first request got HTTP 429. Shared by all boards on one client (= one run)."""

    def __init__(self, threshold: int):
        self.threshold = threshold
        self.streak = 0
        self._lock = threading.Lock()

    @property
    def tripped(self) -> bool:
        return self.streak >= self.threshold

    def record(self, first_request_429: bool) -> None:
        with self._lock:
            was_tripped = self.tripped
            self.streak = self.streak + 1 if first_request_429 else 0
            if self.tripped and not was_tripped:
                log.warning(
                    "workday: %d boards in a row got HTTP 429 on their first request; skipping the rest this run",
                    self.streak,
                )


_breakers: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_breakers_lock = threading.Lock()


def _breaker(client: PoliteClient) -> _Breaker:
    with _breakers_lock:
        if client not in _breakers:
            _breakers[client] = _Breaker(BLOCK_THRESHOLD)
        return _breakers[client]


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
    now = now or datetime.now(UTC)
    t = text.lower()
    if "today" in t:
        return now
    if "yesterday" in t:
        return now - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*days?", t)
    return now - timedelta(days=int(m.group(1))) if m else None


def fetch(client: PoliteClient, company: Company, now: datetime | None = None) -> list[Job]:
    breaker = _breaker(client)
    if breaker.tripped:
        raise WorkdayBlocked(f"skipped: {breaker.streak} Workday boards in a row got HTTP 429", 429)
    queries = company.extra.get("queries") or DEFAULT_QUERIES
    url = board_url(company)
    seen: dict[str, Job] = {}
    first = True
    try:
        for q in queries:
            for page in range(MAX_PAGES_PER_QUERY):
                body = {"appliedFacets": {}, "limit": PAGE, "offset": page * PAGE, "searchText": q}
                try:
                    data = client.post_json(url, body)
                except FetchError as exc:
                    if first:
                        breaker.record(exc.status == 429)
                    raise
                if first:
                    breaker.record(False)
                    first = False
                postings = data.get("jobPostings") or []
                for raw in postings:
                    if raw.get("externalPath") and raw["externalPath"] not in seen:
                        seen[raw["externalPath"]] = normalize(raw, company, now)
                if len(postings) < PAGE:
                    break
    except FetchError as exc:
        if first:
            raise
        raise PartialFetch(list(seen.values()), exc) from exc
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
