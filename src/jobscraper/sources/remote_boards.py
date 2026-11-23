"""Remote job boards with public feeds: Remotive, RemoteOK, Himalayas, We Work Remotely (RSS).
Their terms ask for attribution / link-back, so job URLs stay pointed at the board's own listing."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from ..http import PoliteClient
from ..models import Job
from ..text import extract_comp, fmt_money, html_to_text, parse_iso


def _range(lo, hi, suffix: str = "") -> str | None:
    try:
        lo, hi = float(lo or 0), float(hi or 0)
    except (TypeError, ValueError):
        return None
    if not lo and not hi:
        return None
    return f"{fmt_money(lo)}–{fmt_money(hi)}{suffix}" if lo and hi else f"{fmt_money(lo or hi)}{suffix}"


# ------------------------------------------------------------------ Remotive
def fetch_remotive(client: PoliteClient, settings: dict, now: datetime) -> list[Job]:
    jobs: list[Job] = []
    for cat in settings.get("categories") or ["software-dev"]:
        data = client.get_json(f"https://remotive.com/api/remote-jobs?category={cat}")
        jobs.extend(normalize_remotive(j) for j in data.get("jobs", []))
    return jobs


def normalize_remotive(raw: dict) -> Job:
    desc = html_to_text(raw.get("description"))
    loc = raw.get("candidate_required_location") or "Worldwide"
    return Job(
        id=f"remotive:{raw['id']}",
        source="remotive",
        company=raw.get("company_name") or "",
        title=(raw.get("title") or "").strip(),
        location=f"Remote - {loc}",
        url=raw.get("url") or "",
        remote=True,
        posted_at=parse_iso(raw.get("publication_date")),
        compensation=(raw.get("salary") or "").strip() or extract_comp(desc),
        department=raw.get("category"),
        description=desc,
        tier="remotive",
    )


# ------------------------------------------------------------------ RemoteOK
def fetch_remoteok(client: PoliteClient, settings: dict, now: datetime) -> list[Job]:
    data = client.get_json("https://remoteok.com/api")
    return [normalize_remoteok(j) for j in data if isinstance(j, dict) and j.get("id") and j.get("position")]


def normalize_remoteok(raw: dict) -> Job:
    desc = html_to_text(raw.get("description"))
    loc = raw.get("location") or "Worldwide"
    return Job(
        id=f"remoteok:{raw['id']}",
        source="remoteok",
        company=raw.get("company") or "",
        title=(raw.get("position") or "").strip(),
        location=f"Remote - {loc}",
        url=raw.get("url") or "",
        remote=True,
        posted_at=parse_iso(raw.get("date")),
        compensation=_range(raw.get("salary_min"), raw.get("salary_max")) or extract_comp(desc),
        department=", ".join((raw.get("tags") or [])[:4]) or None,
        description=desc,
        tier="remoteok",
    )


# ------------------------------------------------------------------ Himalayas
def fetch_himalayas(client: PoliteClient, settings: dict, now: datetime) -> list[Job]:
    cutoff = now - timedelta(hours=float(settings.get("lookback_hours", 72)))
    jobs: list[Job] = []
    for page in range(int(settings.get("max_pages", 15))):
        data = client.get_json(f"https://himalayas.app/jobs/api?limit=20&offset={page * 20}")
        batch = [normalize_himalayas(j) for j in data.get("jobs", [])]
        jobs.extend(batch)
        if not batch or all(j.posted_at and j.posted_at < cutoff for j in batch):
            break
    return jobs


def normalize_himalayas(raw: dict) -> Job:
    desc = html_to_text(raw.get("description"))
    restrictions = raw.get("locationRestrictions") or []
    loc = ", ".join(restrictions) or "Worldwide"
    country = "US" if restrictions == ["United States"] else (None if not restrictions else restrictions[0])
    period = {"hourly": "/hr", "yearly": "/yr", "annual": "/yr"}.get((raw.get("salaryPeriod") or "").lower(), "")
    pub = raw.get("pubDate")
    return Job(
        id=f"himalayas:{raw.get('guid')}",
        source="himalayas",
        company=raw.get("companyName") or "",
        title=(raw.get("title") or "").strip(),
        location=f"Remote - {loc}",
        url=raw.get("applicationLink") or raw.get("guid") or "",
        remote=True,
        country=country if len(restrictions) == 1 else None,
        posted_at=datetime.fromtimestamp(int(pub), tz=timezone.utc) if pub else None,
        compensation=_range(raw.get("minSalary"), raw.get("maxSalary"), period) or extract_comp(desc),
        department=", ".join(raw.get("parentCategories") or []) or None,
        description=desc,
        tier="himalayas",
    )


# ------------------------------------------------------------------ We Work Remotely (RSS)
def fetch_wwr(client: PoliteClient, settings: dict, now: datetime) -> list[Job]:
    jobs: list[Job] = []
    for feed in settings.get("feeds") or []:
        xml = client.get_text(f"https://weworkremotely.com/categories/{feed}.rss")
        jobs.extend(parse_wwr(xml))
    return jobs


def parse_wwr(xml: str) -> list[Job]:
    root = ET.fromstring(xml)
    out: list[Job] = []
    for item in root.iter("item"):
        get = lambda tag: (item.findtext(tag) or "").strip()
        company, _, title = get("title").partition(": ")
        if not title:
            company, title = "", company
        link = get("link") or get("guid")
        desc = html_to_text(get("description"))
        try:
            posted = parsedate_to_datetime(get("pubDate"))
        except (TypeError, ValueError):
            posted = None
        region = get("region") or "Anywhere"
        country = get("country") or None
        out.append(
            Job(
                id=f"weworkremotely:{link.rstrip('/').rsplit('/', 1)[-1]}",
                source="weworkremotely",
                company=company.strip(),
                title=title.strip(),
                location=f"Remote - {region}" + (f" ({country})" if country else ""),
                url=link,
                remote=True,
                country=country,
                posted_at=posted,
                compensation=extract_comp(desc),
                department=get("category") or None,
                description=desc,
                tier="weworkremotely",
            )
        )
    return out
