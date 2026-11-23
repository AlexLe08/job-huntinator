"""Match scraped jobs against what's already in the tracker (by URL / ATS job id, then company + similar title)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from urllib.parse import parse_qs, urlsplit

from .filters import normalize_title
from .models import Job

_GH_PATH = re.compile(r"/jobs/(\d+)")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_CORP = re.compile(r"\b(inc|llc|ltd|corp|corporation|co|company|technologies|technology|labs|hq|the)\b")


def normalize_url(url: str) -> str:
    if not url:
        return ""
    u = urlsplit(url.strip())
    host = (u.hostname or "").lower().removeprefix("www.")
    host = {"job-boards.greenhouse.io": "boards.greenhouse.io"}.get(host, host)
    path = re.sub(r"/(apply|application)/?$", "", u.path).rstrip("/")
    return f"{host}{path}"


def job_key(url: str) -> str | None:
    """Stable ATS job identifier, independent of which domain/embed the link came from."""
    if not url:
        return None
    u = urlsplit(url.strip())
    q = parse_qs(u.query)
    if "gh_jid" in q:
        return f"gh:{q['gh_jid'][0]}"
    host = (u.hostname or "").lower()
    if "greenhouse.io" in host and (m := _GH_PATH.search(u.path)):
        return f"gh:{m.group(1)}"
    if host.endswith(("lever.co", "ashbyhq.com")) and (m := _UUID.search(u.path)):
        return f"{host.split('.')[-2]}:{m.group(0).lower()}"
    return None


def normalize_company(name: str) -> str:
    s = re.sub(r"\(.*?\)", " ", (name or "").lower())
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = _CORP.sub(" ", s)
    return re.sub(r"\s+", "", s)


@dataclass
class TrackerIndex:
    urls: set[str] = field(default_factory=set)
    keys: set[str] = field(default_factory=set)
    titles_by_company: dict[str, list[str]] = field(default_factory=dict)

    def add(self, company: str, role: str, url: str) -> None:
        if url:
            self.urls.add(normalize_url(url))
            if k := job_key(url):
                self.keys.add(k)
        if company and role:
            self.titles_by_company.setdefault(normalize_company(company), []).append(normalize_title(role))

    def match(self, job: Job, threshold: float) -> str | None:
        """Return why this job is already tracked, or None."""
        if normalize_url(job.url) in self.urls:
            return "url"
        k = job_key(job.url)
        if k and k in self.keys:
            return "job-id"
        t = normalize_title(job.title)
        for existing in self.titles_by_company.get(normalize_company(job.company), []):
            if SequenceMatcher(None, t, existing).ratio() >= threshold:
                return "company+title"
        return None

    def __len__(self) -> int:
        return len(self.urls) + sum(len(v) for v in self.titles_by_company.values())
