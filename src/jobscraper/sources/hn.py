"""Hacker News monthly "Ask HN: Who is hiring?" thread via the official Algolia HN API.

A post can list several roles, in the header ("Acme | Frontend Engineer, Backend Engineer | ...") and/or in the
body (bullets, "Roles: A, B", "Title: <link>"). Each relevant role becomes its own Job. The primary role keeps the
ID `hn:<objectID>`, which is what the source emitted before multi-role parsing, so existing state stays valid.
Further roles get `hn:<objectID>:<title-slug>`.
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime, timedelta

from ..filters import FilterConfig, classify_title, normalize_title
from ..http import PoliteClient
from ..models import Job
from ..text import extract_comp, extract_links, html_to_text
from .feeds import ATS_LINK, best_link

FEED = "hn"
API = "https://hn.algolia.com/api/v1"
ROLE_WORDS = re.compile(
    r"\b(engineer|developer|designer|programmer|swe|sde|frontend|front-end|full ?stack|devrel|advocate|qa|sdet)\b", re.I
)
LOCATION_WORDS = re.compile(r"\b(remote|onsite|on-site|hybrid|in office|anywhere)\b|,\s*[A-Z]{2}\b", re.I)
NOISE = re.compile(r"\b(full[- ]?time|part[- ]?time|contract|intern(ship)?|visa|equity|salary|\$|€|£|\d+k)\b", re.I)
ROLE_SPLIT = re.compile(r",|;|\s/\s|\band\b|&")
# Headers without pipes: "Acme (YC W21) is hiring a Senior Frontend Engineer in New York, NY (onsite)".
IS_HIRING = re.compile(r"^(?P<company>[^|.!?]{2,60}?)\s+(?:is|are)\s+hiring\b:?\s*(?P<rest>.*)$", re.I)
ROLE_LIST = re.compile(r"^(?:open\s+)?(?:roles?|positions?|openings?|hiring(?:\s+for)?)\s*:\s*(?P<roles>.+)$", re.I)
# Words that mark a body line as prose rather than a bare job title.
SENTENCE = re.compile(r"\b(we|we're|you|your|our|i|i'm|looking|who|will|is|are|with|if)\b", re.I)
SEEKING = re.compile(r"^\s*seeking\s+(work|freelancers?|freelance)\b", re.I)
# Leading bullets, list numbers and HN footnote refs: "- ", "++ ", "2) ", "[3]".
BULLET = re.compile(r"^\s*(?:[-+*•·▪◦–—>]+|\d{1,2}[.)]|\[\d{1,2}\])\s*")
URL = re.compile(r"https?://\S+|\bwww\.\S+", re.I)
TITLE_STRIP = " :-–—|+*"
MAX_ROLE_WORDS = 7
ROLES_PLACEHOLDER = re.compile(r"\b(roles|positions|openings)\b", re.I)
BLOCK_TAG = re.compile(r"</?(?:p|div|br|li|ul|ol|h[1-6]|tr)[^>]*>|\n", re.I)  # line breaks, as in text.html_to_text


def latest_thread(client: PoliteClient) -> dict | None:
    data = client.get_json(f"{API}/search_by_date?tags=story,author_whoishiring&hitsPerPage=10")
    for h in data.get("hits", []):
        if "who is hiring" in (h.get("title") or "").lower():
            return h
    return None


def _clean_title(t: str) -> str:
    return BULLET.sub("", t.strip()).strip(TITLE_STRIP).rstrip(".!").strip()


def _split_roles(text: str) -> list[str]:
    return [c for r in ROLE_SPLIT.split(text) if (c := _clean_title(r))]


def _pick(roles: list[str], cfg: FilterConfig | None, fallback: str) -> list[str]:
    """Every role that passes the title filter, or one fallback role so the filters still see the post."""
    if cfg is not None and (kept := [r for r in roles if classify_title(r, cfg).keep]):
        return kept
    return [roles[0] if roles else fallback]


def parse_header(first_line: str, cfg: FilterConfig | None = None) -> tuple[str, str, str]:
    """'Acme | Senior Frontend Engineer, Backend Engineer | Boston, MA / Remote (US) | Full-time | $150k'
    -> (company, best-matching role, location)."""
    company, roles, location = parse_header_roles(first_line, cfg)
    return company, roles[0], location


def parse_header_roles(first_line: str, cfg: FilterConfig | None = None) -> tuple[str, list[str], str]:
    """(company, matching roles (best first, never empty), location) from a post's first line."""
    if m := IS_HIRING.match(first_line):
        return _parse_is_hiring(m, first_line, cfg)
    parts = [p.strip() for p in re.split(r"\s+[|•·]\s+|\s+-\s+|\s+—\s+", first_line) if p.strip()]
    if len(parts) < 2:
        return (parts[0] if parts else first_line.strip()), [first_line.strip()], ""
    company = re.sub(r"\s*\(.*?\)\s*$", "", parts[0]).strip()
    roles: list[str] = []
    locations: list[str] = []
    for p in parts[1:]:
        if URL.match(p):
            continue  # "Acme | Engineer | NYC | https://acme.com/jobs/software-engineer"
        if ROLE_WORDS.search(p):
            roles.extend(_split_roles(p))
        elif ROLES_PLACEHOLDER.search(p):
            continue  # "Multiple roles", "Various positions": the roles are listed in the body
        elif LOCATION_WORDS.search(p) or (not NOISE.search(p) and len(p) < 60 and re.search(r"[A-Z][a-z]+", p)):
            locations.append(p)
    fallback = next((p for p in parts[1:] if not URL.match(p)), parts[1])
    return company, _pick(roles, cfg, fallback=fallback), " / ".join(locations)


def _parse_is_hiring(m: re.Match, first_line: str, cfg: FilterConfig | None) -> tuple[str, list[str], str]:
    company = re.sub(r"\s*\(.*?\)\s*$", "", m["company"]).strip()
    rest = re.split(r"\s+[|•·—]\s+|\s+-\s+", m["rest"], maxsplit=1)[0]
    locations: list[str] = []
    if lm := re.search(r"\s(?:in|at)\s+([A-Z][^()|.!]*)", rest):
        locations.append(lm[1].strip(" ,"))
        rest = rest[: lm.start()]
    if rm := re.search(r"\b(remote|onsite|on-site|hybrid)\b", first_line, re.I):
        locations.append(rm[1])
    rest = re.sub(r"\(.*?\)", " ", rest).strip(" .!:")
    roles = [re.sub(r"^(?:an?|multiple|several|two|three)\s+", "", r, flags=re.I) for r in _split_roles(rest)]
    return company, _pick(roles, cfg, fallback=rest or first_line.strip()), " / ".join(locations)


def body_roles(raw_html: str, cfg: FilterConfig) -> list[tuple[str, str]]:
    """Roles listed in the post body after the first line, as (title, ATS link on that line or "").

    Only short, title-like lines count: bullets ("- Senior Frontend Engineer"), "Roles: A, B" lists and
    "Frontend Engineer: https://..." lines. Prose that merely mentions a role is ignored."""
    out: list[tuple[str, str]] = []
    lines = [ln for ln in BLOCK_TAG.sub("\n", raw_html).split("\n") if ln.strip()]
    for raw_line in lines[1:]:
        links = [u for u in extract_links(raw_line) if ATS_LINK.search(u)]
        line = html_to_text(raw_line)
        bare = BULLET.sub("", URL.sub(" ", line)).strip()
        if lm := ROLE_LIST.match(bare):
            cands = _split_roles(lm["roles"])
        else:
            cands = [_clean_title(re.split(r"\s+[-–—|]\s+|:\s|:$|\s*[(\[]", bare, maxsplit=1)[0])]
        for c in cands:
            if not c or len(c.split()) > MAX_ROLE_WORDS or not ROLE_WORDS.search(c) or SENTENCE.search(c):
                continue
            if classify_title(c, cfg).keep:
                out.append((c, links[0] if links and len(cands) == 1 else ""))
    return out


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
            jobs.extend(normalize_all(h, cfg))
        page += 1
        if page >= int(data.get("nbPages", 0)) or page >= 10:
            break
    return jobs


def normalize(hit: dict, cfg: FilterConfig | None = None) -> Job | None:
    """The post's primary role only."""
    jobs = normalize_all(hit, cfg)
    return jobs[0] if jobs else None


def normalize_all(hit: dict, cfg: FilterConfig | None = None) -> list[Job]:
    """One Job per relevant role in the post (header roles first, then body roles); [] if it isn't a job post."""
    raw = hit["comment_text"]
    text = html_to_text(raw)
    first = html.unescape(text.split("\n", 1)[0]).strip()
    if SEEKING.match(first):
        return []  # a candidate advertising themselves
    if "|" not in first and " - " not in first and not IS_HIRING.match(first):
        return []  # not following the "Company | Role | Location" convention; usually not a job post
    company, header_roles, location = parse_header_roles(first, cfg)
    comment_url = f"https://news.ycombinator.com/item?id={hit['objectID']}"
    post_url = best_link(extract_links(raw), comment_url)
    roles = [(r, "") for r in header_roles]
    if cfg is not None and (body := body_roles(raw, cfg)):
        # A header fallback that fails the title filter ("Acme | Multiple roles | NYC") yields to the body's roles.
        roles = (roles if classify_title(header_roles[0], cfg).keep else []) + body
    common = dict(
        source=FEED,
        company=company[:80],
        location=location[:160],
        remote=True if re.search(r"\bremote\b", first, re.I) else None,
        posted_at=datetime.fromtimestamp(int(hit["created_at_i"]), tz=UTC),
        compensation=extract_comp(first) or extract_comp(text),
        description=text,
        tier="hn",
    )
    jobs: list[Job] = []
    by_title: dict[str, Job] = {}
    for title, link in roles:
        key = normalize_title(title)
        if (dup := by_title.get(key)) is not None:
            if link and dup.url == post_url:
                dup.url = link  # a header role whose own posting link sits in the body
            continue
        suffix = ":" + _slug(key, {j.id for j in jobs}) if jobs else ""
        job = Job(id=f"hn:{hit['objectID']}{suffix}", title=title[:120], url=link or post_url, **common)
        by_title[key] = job
        jobs.append(job)
    return jobs


def _slug(normalized_title: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", normalized_title).strip("-")[:40] or "role"
    slug, n = base, 2
    while any(t.endswith(":" + slug) for t in taken):
        slug, n = f"{base}-{n}", n + 1
    return slug
