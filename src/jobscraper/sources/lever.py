from __future__ import annotations

from ..companies import Company
from ..http import PoliteClient
from ..models import Job
from ..text import extract_comp, fmt_money, from_epoch_ms, html_to_text

API_NAME = "lever"


def board_url(token: str) -> str:
    return f"https://api.lever.co/v0/postings/{token}?mode=json"


def fetch(client: PoliteClient, company: Company) -> list[Job]:
    data = client.get_json(board_url(company.token))
    if not isinstance(data, list):  # {"ok": false, "error": ...}
        return []
    return [normalize(j, company) for j in data]


def _salary(sr: dict | None) -> str | None:
    if not sr or (sr.get("min") is None and sr.get("max") is None):
        return None
    cur = sr.get("currency") or ""
    interval = (sr.get("interval") or "").replace("per-", "/").replace("-salary", "").replace("-wage", "")
    rng = f"{fmt_money(sr.get('min'))}–{fmt_money(sr.get('max'))}"
    return " ".join(filter(None, [rng, cur, interval])).strip()


def normalize(raw: dict, company: Company) -> Job:
    cats = raw.get("categories") or {}
    all_locs = cats.get("allLocations") or []
    location = cats.get("location") or ""
    extra = [l for l in all_locs if l and l != location]
    if extra:
        location = "; ".join([location, *extra]) if location else "; ".join(extra)

    parts = [raw.get("openingPlain"), raw.get("descriptionPlain") or raw.get("descriptionBodyPlain")]
    for lst in raw.get("lists") or []:
        parts.append(lst.get("text", ""))
        parts.append(html_to_text(lst.get("content")))
    parts.append(raw.get("additionalPlain"))
    description = "\n\n".join(p.strip() for p in parts if p and p.strip())

    wt = (raw.get("workplaceType") or "").lower()
    remote = True if wt == "remote" or "remote" in location.lower() else (False if wt in ("onsite", "hybrid") else None)
    return Job(
        id=f"lever:{company.token}:{raw['id']}",
        source=API_NAME,
        company=company.company,
        title=(raw.get("text") or "").strip(),
        location=location,
        url=raw.get("hostedUrl") or "",
        remote=remote,
        country=raw.get("country"),
        posted_at=from_epoch_ms(raw.get("createdAt")),
        updated_at=None,
        compensation=_salary(raw.get("salaryRange")) or extract_comp(description),
        department=cats.get("department") or cats.get("team"),
        description=description,
        tier=company.tier,
    )
