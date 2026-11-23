"""Hacker News monthly "Ask HN: Who is hiring?" thread via the official Algolia HN API."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime, timedelta

from ..filters import FilterConfig, classify_title
from ..http import PoliteClient
from ..models import Job
from ..text import extract_comp, extract_links, html_to_text
from .feeds import best_link

FEED = "hn"
API = "https://hn.algolia.com/api/v1"
ROLE_WORDS = re.compile(
    r"\b(engineer|developer|designer|programmer|swe|sde|frontend|front-end|full ?stack|devrel|advocate|qa|sdet)\b", re.I
)
LOCATION_WORDS = re.compile(r"\b(remote|onsite|on-site|hybrid|in office|anywhere)\b|,\s*[A-Z]{2}\b", re.I)
NOISE = re.compile(r"\b(full[- ]?time|part[- ]?time|contract|intern(ship)?|visa|equity|salary|\$|€|£|\d+k)\b", re.I)


def latest_thread(client: PoliteClient) -> dict | None:
    data = client.get_json(f"{API}/search_by_date?tags=story,author_whoishiring&hitsPerPage=10")
    for h in data.get("hits", []):
        if "who is hiring" in (h.get("title") or "").lower():
            return h
    return None


def parse_header(first_line: str, cfg: FilterConfig | None = None) -> tuple[str, str, str]:
    """'Acme | Senior Frontend Engineer, Backend Engineer | Boston, MA / Remote (US) | Full-time | $150k'
    -> (company, best-matching role, location)."""
    parts = [p.strip() for p in re.split(r"\s+[|•·]\s+|\s+-\s+|\s+—\s+", first_line) if p.strip()]
    if len(parts) < 2:
        return (parts[0] if parts else first_line.strip()), first_line.strip(), ""
    company = re.sub(r"\s*\(.*?\)\s*$", "", parts[0]).strip()
    roles: list[str] = []
    locations: list[str] = []
    for p in parts[1:]:
        if ROLE_WORDS.search(p):
            roles.extend(r.strip() for r in re.split(r",|;|\s/\s|\band\b|&", p) if r.strip())
        elif LOCATION_WORDS.search(p) or (not NOISE.search(p) and len(p) < 60 and re.search(r"[A-Z][a-z]+", p)):
            locations.append(p)
    role = ""
    if roles and cfg is not None:
        role = next((r for r in roles if classify_title(r, cfg).keep), "")
    role = role or (roles[0] if roles else parts[1])
    return company, role, " / ".join(locations)


def fetch(client: PoliteClient, settings: dict, now: datetime, cfg: FilterConfig | None = None) -> list[Job]:
    story = latest_thread(client)
    if not story:
        return []
    since = int((now - timedelta(hours=float(settings.get("lookback_hours", 72)))).timestamp())
    jobs: list[Job] = []
    page = 0
    while True:
        data = client.get_json(
            f"{API}/search_by_date?tags=comment,story_{story['objectID']}"
            f"&numericFilters=created_at_i>{since}&hitsPerPage=200&page={page}"
        )
        for h in data.get("hits", []):
            if str(h.get("parent_id")) != str(story["objectID"]) or not h.get("comment_text"):
                continue  # replies, deleted
            job = normalize(h, cfg)
            if job:
                jobs.append(job)
        page += 1
        if page >= int(data.get("nbPages", 0)) or page >= 10:
            break
    return jobs


def normalize(hit: dict, cfg: FilterConfig | None = None) -> Job | None:
    raw = hit["comment_text"]
    text = html_to_text(raw)
    first = html.unescape(text.split("\n", 1)[0]).strip()
    if "|" not in first and " - " not in first:
        return None  # not following the "Company | Role | Location" convention; usually not a job post
    company, role, location = parse_header(first, cfg)
    comment_url = f"https://news.ycombinator.com/item?id={hit['objectID']}"
    return Job(
        id=f"hn:{hit['objectID']}",
        source=FEED,
        company=company[:80],
        title=role[:120],
        location=location[:160],
        url=best_link(extract_links(raw), comment_url),
        remote=True if re.search(r"\bremote\b", first, re.I) else None,
        posted_at=datetime.fromtimestamp(int(hit["created_at_i"]), tz=UTC),
        compensation=extract_comp(first) or extract_comp(text),
        description=text,
        tier="hn",
    )
