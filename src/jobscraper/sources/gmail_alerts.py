"""LinkedIn / Indeed job-alert emails from your own Gmail (read-only), so those boards are covered
without scraping them. Auth: OAuth refresh token created once with `python -m jobscraper gmail-auth`.

Alert email layouts change now and then. Parsing therefore keys on the stable part -- the job-view
link (LinkedIn /jobs/view/<id>, Indeed jk=<id>) -- and reads title/company/location from the text
around it. If a layout change breaks it, the feed returns fewer jobs; it never fails the run.
"""

from __future__ import annotations

import base64
import json
import os
import re
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlsplit

from ..http import PoliteClient
from ..models import Job

FEED = "gmail_alerts"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
API = "https://gmail.googleapis.com/gmail/v1/users/me"

LINKEDIN_JOB = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)", re.I)
INDEED_HOST = re.compile(r"(^|\.)indeed\.com$", re.I)
SKIP_TEXT = re.compile(
    r"^(view job|apply|easy apply|see all jobs|view all|unsubscribe|new|promoted|actively recruiting|\d+ (applicants|connections?|company alum(ni)?).*)$",
    re.I,
)


class MissingCredentials(RuntimeError):
    pass


# ------------------------------------------------------------------ auth
def access_token() -> str:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    client_raw = os.environ.get("GMAIL_OAUTH_CLIENT_JSON", "").strip()
    refresh = os.environ.get("GMAIL_REFRESH_TOKEN", "").strip()
    if not client_raw or not refresh:
        raise MissingCredentials("GMAIL_OAUTH_CLIENT_JSON / GMAIL_REFRESH_TOKEN not set")
    if not client_raw.startswith("{") and os.path.exists(client_raw):
        with open(client_raw) as fh:
            client_raw = fh.read()
    info = json.loads(client_raw)
    info = info.get("installed") or info.get("web") or info
    creds = Credentials(
        None,
        refresh_token=refresh,
        client_id=info["client_id"],
        client_secret=info["client_secret"],
        token_uri=info.get("token_uri", "https://oauth2.googleapis.com/token"),
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds.token


def run_auth_flow(client_secret_path: str) -> str:
    """One-time, local: opens a browser consent screen and returns a refresh token."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    return creds.refresh_token


# ------------------------------------------------------------------ fetch
def fetch(client: PoliteClient, settings: dict, now: datetime, token: str | None = None) -> list[Job]:
    token = token or access_token()
    headers = {"Authorization": f"Bearer {token}"}
    q = urlencode(
        {
            "q": settings.get("query", "label:job-alerts newer_than:3d"),
            "maxResults": int(settings.get("max_messages", 50)),
        }
    )
    listing = client.get_json(f"{API}/messages?{q}", headers=headers)
    jobs: dict[str, Job] = {}
    for m in listing.get("messages", []):
        msg = client.get_json(f"{API}/messages/{m['id']}?format=full", headers=headers)
        for job in parse_message(msg):
            jobs.setdefault(job.id, job)
    return list(jobs.values())


def _header(msg: dict, name: str) -> str:
    for h in (msg.get("payload") or {}).get("headers") or []:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _html_body(part: dict) -> str:
    if part.get("mimeType") == "text/html" and (part.get("body") or {}).get("data"):
        data = part["body"]["data"]
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
    for sub in part.get("parts") or []:
        if html := _html_body(sub):
            return html
    return ""


def parse_message(msg: dict) -> list[Job]:
    html = _html_body(msg.get("payload") or {})
    if not html:
        return []
    sender = _header(msg, "From").lower()
    received = (
        datetime.fromtimestamp(int(msg.get("internalDate", 0)) / 1000, tz=UTC) if msg.get("internalDate") else None
    )
    if "linkedin" in sender:
        return parse_alert_html(html, "linkedin", received)
    if "indeed" in sender:
        return parse_alert_html(html, "indeed", received)
    return parse_alert_html(html, None, received)  # forwarded / unknown sender: try both


# ------------------------------------------------------------------ parsing
class _Flatten(HTMLParser):
    """Flatten HTML into an ordered list of ("a", href, text) and ("t", None, text) tokens."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tokens: list[tuple[str, str | None, str]] = []
        self._href: str | None = None
        self._buf: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head"):
            self._skip += 1
        elif tag == "a":
            self._flush()
            self._href = dict(attrs).get("href")
        elif tag in ("br", "p", "div", "td", "tr", "li", "table", "span"):
            self._flush()

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head"):
            self._skip = max(0, self._skip - 1)
        elif tag == "a":
            self._flush(anchor=True)
            self._href = None
        elif tag in ("p", "div", "td", "tr", "li", "table", "span"):
            self._flush()

    def handle_data(self, data):
        if not self._skip:
            self._buf.append(data)

    def _flush(self, anchor: bool = False):
        text = re.sub(r"\s+", " ", unescape("".join(self._buf))).strip()
        self._buf = []
        if anchor and self._href:
            self.tokens.append(("a", self._href, text))
        elif text:
            self.tokens.append(("t", self._href, text))


def _job_ref(href: str, kind: str | None) -> tuple[str, str, str] | None:
    """-> (source, native id, canonical url) if href is a job-view link."""
    if not href:
        return None
    if kind in (None, "linkedin") and (m := LINKEDIN_JOB.search(href)):
        return "linkedin", m.group(1), f"https://www.linkedin.com/jobs/view/{m.group(1)}/"
    if kind in (None, "indeed"):
        u = urlsplit(href)
        if INDEED_HOST.search(u.hostname or ""):
            jk = (parse_qs(u.query).get("jk") or parse_qs(u.query).get("vjk") or [None])[0]
            if jk:
                return "indeed", jk, f"https://www.indeed.com/viewjob?jk={jk}"
    return None


def parse_alert_html(html: str, kind: str | None, received: datetime | None) -> list[Job]:
    p = _Flatten()
    p.feed(html)
    # Group text into job cards. A card is every text token under one job-view link plus the plain
    # (link-less) text right after it, until another link starts. This covers both layouts seen:
    #   real LinkedIn: one <a> wraps the whole card (title, then "Company · Location" line)
    #   Indeed / older LinkedIn: <a>Title</a> followed by plain-text company and location rows
    cards: dict[str, tuple[tuple[str, str, str], list[str]]] = {}
    current: str | None = None
    for _typ, href, text in p.tokens:
        if href:
            ref = _job_ref(href, kind)
            current = f"{ref[0]}:{ref[1]}" if ref else None
            if ref:
                cards.setdefault(current, (ref, []))
        if current is None or not text or SKIP_TEXT.match(text):
            continue
        texts = cards[current][1]
        if text not in texts and len(texts) < 3:
            texts.append(text)

    jobs: list[Job] = []
    for key, ((source, _native, url), texts) in cards.items():
        if not texts:
            continue  # e.g. an image-only link
        title, info = texts[0], texts[1:]
        company, location = "", ""
        if info:
            if "·" in info[0]:
                company, _, location = (s.strip() for s in info[0].partition("·"))
            else:
                company = info[0]
                location = info[1] if len(info) > 1 else ""
        jobs.append(
            Job(
                id=key,
                source=source,
                company=company,
                title=title,
                location=location,
                url=url,
                remote=True if "remote" in location.lower() else None,
                posted_at=received,
                description="",
                tier=f"{source}-alert",
            )
        )
    return jobs
