"""Check that every company's ATS board token resolves; auto-detect the right ATS/token when it doesn't."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import yaml

from .companies import Company
from .http import FetchError, PoliteClient
from .sources import bamboohr, workday
from .sources.base import AUTODETECT, COMPANY_SOURCES

# ATSes that rate-limit guessing: probe only the first N slug variants, with wider spacing.
LIGHT_PROBE = {"workable": 3, "recruitee": 3}


@dataclass
class Probe:
    ats: str
    token: str
    jobs: int
    board_name: str | None = None


@dataclass
class Result:
    company: Company
    status: str  # ok | empty | corrected | unsure | dead | skipped | error
    found: Probe | None = None
    error: str | None = None


def slug_variants(company: Company) -> list[tuple[str, bool]]:
    """(slug, confident) pairs. The bare first word of a multi-word name is a loose guess -- it can hit
    an unrelated company (e.g. "Help Scout" -> "help"), so those corrections need a human to confirm."""
    name = re.sub(r"\(.*?\)", "", company.company).strip().lower()
    base = re.sub(r"[^a-z0-9]+", "", name)
    hyph = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    first = re.split(r"[^a-z0-9]+", name)[0]
    out: list[tuple[str, bool]] = []
    for v, sure in (
        (company.token, True),
        (company.token.lower(), True),
        (base, True),
        (hyph, True),
        (f"{base}hq", True),
        (f"{base}inc", True),
        (first, first == base),
    ):
        if v and v not in [o for o, _ in out]:
            out.append((v, sure))
    return out


def probe(client: PoliteClient, ats: str, token: str) -> Probe | None:
    """Return a Probe if the board exists, None if it 404s. Other errors propagate."""
    try:
        if ats == "greenhouse":
            data = client.get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs")
            jobs = data.get("jobs", [])
            name = jobs[0].get("company_name") if jobs else None
            return Probe(ats, token, len(jobs), name)
        if ats == "lever":
            data = client.get_json(f"https://api.lever.co/v0/postings/{token}?mode=json")
            return Probe(ats, token, len(data), None) if isinstance(data, list) else None
        if ats == "ashby":
            data = client.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}")
            return Probe(ats, token, len(data.get("jobs", [])), None)
        if ats == "workable":
            data = client.get_json(f"https://apply.workable.com/api/v1/widget/accounts/{token}")
            return Probe(ats, token, len(data.get("jobs", [])), data.get("name"))
        if ats == "recruitee":
            data = client.get_json(f"https://{token}.recruitee.com/api/offers/")
            offers = data.get("offers", [])
            return Probe(ats, token, len(offers), offers[0].get("company_name") if offers else None)
        if ats == "smartrecruiters":
            data = client.get_json(f"https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=1")
            items = data.get("content") or []
            name = ((items[0].get("company") or {}).get("name")) if items else None
            return Probe(ats, token, int(data.get("totalFound", 0)), name)
        if ats == "bamboohr":
            return Probe(ats, token, len(bamboohr.get_board(client, token).get("result") or []), None)
    except FetchError as exc:
        if exc.status in (404, 400, 410):
            return None
        raise
    raise ValueError(f"cannot probe ats {ats}")


def probe_workday(client: PoliteClient, company: Company) -> Probe | None:
    try:
        data = client.post_json(
            workday.board_url(company), {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
        )
    except FetchError as exc:
        if exc.status in (404, 400, 410, 422):
            return None
        raise
    return Probe("workday", company.token, int(data.get("total", 0)), None)


def validate_one(clients: dict[str, PoliteClient], company: Company, deep: bool = True) -> Result:
    if company.ats not in COMPANY_SOURCES:
        return Result(company, "skipped", error=f"ats '{company.ats}' not supported yet")
    if company.ats == "workday":
        if not (company.extra.get("host") and company.extra.get("site")):
            return Result(company, "skipped", error="workday entry needs host and site")
        try:
            p = probe_workday(clients["workday"], company)
        except Exception as exc:
            return Result(company, "error", error=str(exc))
        return Result(company, "ok" if p and p.jobs else ("empty" if p else "dead"), p)
    try:
        p = probe(clients[company.ats], company.ats, company.token)
        if p and p.jobs > 0:
            return Result(company, "ok", p)
        empty = p
        if not deep or company.extra.get("no_autodetect"):
            return Result(company, "empty" if empty else "dead", empty)
        # Listed board is missing or empty: try every supported ATS x slug variant.
        for ats in AUTODETECT:
            variants = slug_variants(company)
            if ats in LIGHT_PROBE:  # stricter rate limits: only the most likely slugs
                variants = variants[: LIGHT_PROBE[ats]]
            for tok, sure in variants:
                if ats == company.ats and tok == company.token:
                    continue
                try:
                    q = probe(clients[ats], ats, tok)
                except FetchError as exc:
                    if exc.status == 429:  # rate limited: give up on this ATS for this company, keep going
                        break
                    raise
                if q and q.jobs > 0:
                    return Result(company, "corrected" if sure else "unsure", q)
        return Result(company, "empty" if empty else "dead", empty)
    except Exception as exc:  # network trouble etc. -- report, don't crash
        return Result(company, "error", error=str(exc))


def validate_all(companies: list[Company], workers: int = 6, deep: bool = True) -> list[Result]:
    clients = {ats: PoliteClient(retries=2, delay=1.5 if ats in LIGHT_PROBE else 0.4) for ats in COMPANY_SOURCES}
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(lambda c: validate_one(clients, c, deep), companies))
    finally:
        for c in clients.values():
            c.close()


def write_report(results: list[Result], path: str | Path | None) -> str:
    groups: dict[str, list[Result]] = {}
    for r in results:
        groups.setdefault(r.status, []).append(r)
    lines = ["# Company validation report", ""]
    lines.append(" | ".join(f"**{k}**: {len(v)}" for k, v in sorted(groups.items())))
    titles = {
        "corrected": "Auto-corrected (check the board name looks right)",
        "unsure": "Possible match, NOT applied by --fix (loose name guess; confirm by hand)",
        "dead": "Dead: no board found on any supported ATS",
        "empty": "Board exists but has 0 open jobs",
        "error": "Errors (network/other; re-run)",
        "skipped": "Skipped (unsupported ATS)",
        "ok": "OK",
    }
    for status in ("corrected", "unsure", "dead", "empty", "error", "skipped", "ok"):
        rs = groups.get(status)
        if not rs:
            continue
        lines += ["", f"## {titles[status]} ({len(rs)})", ""]
        for r in sorted(rs, key=lambda r: r.company.company.lower()):
            c, f = r.company, r.found
            if status in ("corrected", "unsure"):
                lines.append(
                    f"- {c.company}: {c.ats}/{c.token} -> **{f.ats}/{f.token}** ({f.jobs} jobs{', board: ' + f.board_name if f.board_name else ''})"
                )
            elif status == "ok":
                lines.append(f"- {c.company} ({c.ats}/{c.token}): {f.jobs} jobs")
            else:
                lines.append(f"- {c.company} ({c.ats}/{c.token}){': ' + r.error if r.error else ''}")
    text = "\n".join(lines) + "\n"
    if path:
        Path(path).write_text(text)
    return text


def apply_fixes(yaml_path: str | Path, results: list[Result]) -> int:
    """Rewrite companies.yaml in place: apply corrections, disable dead boards. Keeps the header comment."""
    p = Path(yaml_path)
    raw = p.read_text()
    header = "".join(line + "\n" for line in raw.splitlines() if line.startswith("#") and not line.startswith("  "))
    data = yaml.safe_load(raw)
    rows = data["companies"]
    by_key = {(r.company.ats, r.company.token, r.company.company): r for r in results}
    changed = 0
    for row in rows:
        r = by_key.get((str(row["ats"]).lower(), str(row["token"]), str(row["company"])))
        if not r:
            continue
        if r.status == "corrected":
            row["ats"], row["token"] = r.found.ats, r.found.token
            row.pop("disabled", None)
            changed += 1
        elif r.status == "dead" and not row.get("disabled"):
            row["disabled"] = True
            row["notes"] = "no board found (validator)"
            changed += 1
        elif r.status == "unsure" and not row.get("disabled"):
            row["disabled"] = True
            row["notes"] = f"listed board not found; possible match {r.found.ats}/{r.found.token} -- confirm by hand"
            changed += 1
    body_lines = ["companies:"]
    tier = None
    for row in rows:
        if row.get("tier") != tier:
            tier = row.get("tier")
            body_lines.append(f"\n  # ---- {tier}")
        body_lines.append("  - " + yaml.safe_dump(row, default_flow_style=True, sort_keys=False, width=1000).strip())
    p.write_text(header + "\n".join(body_lines) + "\n")
    return changed
