"""Small text helpers shared by sources and filters."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime

_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_RE = re.compile(r"</?(p|div|br|li|ul|ol|h[1-6]|tr)[^>]*>", re.I)
_WS_RE = re.compile(r"[ \t\r\f\v\xa0]+")
_NL_RE = re.compile(r"\n\s*\n+")

# $120,000 - $150,000 | $120K–$150K | $55/hr - $65/hr ; requires a range to cut down on false hits
_COMP_RE = re.compile(
    r"\$\s?\d{2,3}(?:,\d{3})*(?:\.\d+)?\s?[kK]?(?:\s?(?:USD|/\s?(?:yr|year|hr|hour)))?"
    r"\s?(?:-|–|—|to)\s?"
    r"\$?\s?\d{2,3}(?:,\d{3})*(?:\.\d+)?\s?[kK]?(?:\s?(?:USD|/\s?(?:yr|year|hr|hour)))?"
)


def html_to_text(raw: str | None, *, unescape_first: bool = False) -> str:
    """Strip HTML to readable plain text. Greenhouse double-escapes, so unescape before stripping."""
    if not raw:
        return ""
    s = html.unescape(raw) if unescape_first else raw
    s = _BLOCK_RE.sub("\n", s)
    s = _TAG_RE.sub(" ", s)
    s = html.unescape(s)
    s = _WS_RE.sub(" ", s)
    s = "\n".join(line.strip() for line in s.splitlines())
    return _NL_RE.sub("\n", s).strip()


_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)


def extract_links(raw_html: str | None) -> list[str]:
    """All http(s) links in an HTML/text blob, href targets first, de-duplicated, in order."""
    if not raw_html:
        return []
    s = html.unescape(raw_html)
    found = _HREF_RE.findall(s) + _URL_RE.findall(s)
    out: list[str] = []
    for u in found:
        u = u.rstrip(".,;")
        if u.startswith("http") and u not in out:
            out.append(u)
    return out


def extract_comp(text: str) -> str | None:
    m = _COMP_RE.search(text or "")
    return re.sub(r"\s+", " ", m.group(0)).strip() if m else None


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def from_epoch_ms(value: int | float | str | None) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def fmt_money(n: float | int | None) -> str:
    if n is None:
        return "?"
    n = float(n)
    if n >= 1000:
        return f"${n / 1000:.0f}K"
    return f"${n:,.0f}" if n == int(n) else f"${n:,.2f}"
