"""Google Sheets I/O. Reads Applications/Archive/Leads (and Scraper) for dedupe; only ever appends to Scraper."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from .dedupe import TrackerIndex

log = logging.getLogger(__name__)

SCRAPER_TAB = "Scraper"
SCRAPER_HEADER = ["Date Found", "Company", "Role", "Location", "Link", "Posted", "Comp", "ATS", "Tier", "Flags"]
TRACKER_TABS = ["Applications", "Archive", "Leads", SCRAPER_TAB]
LINK_HEADERS = ("job posting link", "link", "url")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsNotConfigured(RuntimeError):
    pass


def credentials_from_env() -> tuple[str, dict[str, Any]]:
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not sheet_id or not raw:
        raise SheetsNotConfigured("set GOOGLE_SHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw.startswith("{") and os.path.exists(raw):  # allow a path locally
        with open(raw) as fh:
            raw = fh.read()
    return sheet_id, json.loads(raw)


def open_sheet():
    import gspread

    sheet_id, info = credentials_from_env()
    gc = gspread.service_account_from_dict(info, scopes=SCOPES)
    return gc.open_by_key(sheet_id)


def _col(header: list[str], *names: str) -> int | None:
    h = [c.strip().lower() for c in header]
    for n in names:
        if n in h:
            return h.index(n)
    return None


def index_rows(tab_rows: dict[str, list[list[str]]]) -> TrackerIndex:
    """Build a dedupe index from {tab name: rows incl. header}. Columns are located by header name."""
    idx = TrackerIndex()
    for tab, rows in tab_rows.items():
        if not rows:
            continue
        header = rows[0]
        ci, ri, li = _col(header, "company"), _col(header, "role", "title"), _col(header, *LINK_HEADERS)
        if li is None:
            log.warning("tab %s has no link column; matching on company+role only", tab)
        for row in rows[1:]:
            get = lambda i: row[i].strip() if i is not None and i < len(row) else ""
            idx.add(get(ci), get(ri), get(li))
    return idx


def load_tracker_index(sh) -> TrackerIndex:
    titles = {ws.title: ws for ws in sh.worksheets()}
    rows = {}
    for tab in TRACKER_TABS:
        if tab in titles:
            rows[tab] = titles[tab].get_all_values()
        elif tab != SCRAPER_TAB:
            log.warning("tracker tab %r not found", tab)
    return index_rows(rows)


def ensure_scraper_tab(sh):
    import gspread

    try:
        ws = sh.worksheet(SCRAPER_TAB)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(SCRAPER_TAB, rows=1000, cols=len(SCRAPER_HEADER))
        ws.append_row(SCRAPER_HEADER, value_input_option="RAW")
        ws.freeze(rows=1)
        return ws
    if not ws.row_values(1):
        ws.append_row(SCRAPER_HEADER, value_input_option="RAW")
    return ws


def append_rows(sh, rows: list[list[str]]) -> None:
    if not rows:
        return
    ws = ensure_scraper_tab(sh)
    # USER_ENTERED so the Link renders as a clickable URL; values are escaped against formula injection.
    ws.append_rows([[_safe(v) for v in r] for r in rows], value_input_option="USER_ENTERED")


def _safe(v: Any) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s
