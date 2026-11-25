from __future__ import annotations

import re

from ..companies import Company
from ..http import PoliteClient
from ..models import Job
from ..text import extract_comp, fmt_money, html_to_text, parse_iso

API_NAME = "greenhouse"
PLACEHOLDER_LOCATIONS = {"", "na", "n/a", "location", "tbd", "various", "multiple", "multiple locations", "-"}
# Pay ranges whose title marks them as on-target / variable pay rather than base salary.
NON_BASE_RE = re.compile(r"\b(?:ote|on[- ]target|variable|commission|bonus)\b", re.I)
HOURLY_MAX = 1000  # a range topping out under 1,000 (dollars, euros, ...) is an hourly rate


def board_url(token: str) -> str:
    # pay_transparency adds each job's structured `pay_input_ranges` to the list: ~5% more bytes, no extra requests.
    return f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true&pay_transparency=true"


def fetch(client: PoliteClient, company: Company) -> list[Job]:
    data = client.get_json(board_url(company.token))
    return [normalize(j, company) for j in data.get("jobs", [])]


def _money(n: float, currency: str) -> str:
    s = fmt_money(n)
    return s if currency == "USD" else s.removeprefix("$")


def pay_range(ranges: list[dict] | None) -> str | None:
    """Summarize Greenhouse's structured pay ranges into one string, e.g. "$203K–$343K", "$27/hr", "90K–122K EUR".

    Base pay wins over OTE/variable ranges, USD over other currencies, and location zones collapse into one span
    (lowest min to highest max). None if the posting publishes no usable range.
    """
    usable = [
        r
        for r in ranges or []
        if isinstance(r, dict) and r.get("currency_type") and (r.get("min_cents") or r.get("max_cents"))
    ]
    if not usable:
        return None
    usable = [r for r in usable if not NON_BASE_RE.search(r.get("title") or "")] or usable
    currency = "USD" if any(r["currency_type"] == "USD" for r in usable) else usable[0]["currency_type"]
    values = [
        v / 100 for r in usable if r["currency_type"] == currency for v in (r.get("min_cents"), r.get("max_cents")) if v
    ]
    lo, hi = min(values), max(values)
    hourly = hi < HOURLY_MAX
    text = _money(lo, currency) if lo == hi else f"{_money(lo, currency)}–{_money(hi, currency)}"
    return text + ("/hr" if hourly else "") + ("" if currency == "USD" else f" {currency}")


def normalize(raw: dict, company: Company) -> Job:
    location = ((raw.get("location") or {}).get("name") or "").strip()
    offices = [o.get("location") or o.get("name") for o in raw.get("offices") or [] if o]
    if location.lower() in PLACEHOLDER_LOCATIONS:
        location = "; ".join(filter(None, offices))
    description = html_to_text(raw.get("content"), unescape_first=True)
    depts = [d.get("name") for d in raw.get("departments") or [] if d.get("name")]
    return Job(
        id=f"greenhouse:{company.token}:{raw['id']}",
        source=API_NAME,
        company=company.company,
        title=(raw.get("title") or "").replace("\xa0", " ").strip(),
        location=location,
        url=raw.get("absolute_url") or "",
        remote=True if "remote" in location.lower() else None,
        posted_at=parse_iso(raw.get("first_published")),
        updated_at=parse_iso(raw.get("updated_at")),
        compensation=pay_range(raw.get("pay_input_ranges")) or extract_comp(description),
        department=", ".join(depts) or None,
        description=description,
        tier=company.tier,
    )
