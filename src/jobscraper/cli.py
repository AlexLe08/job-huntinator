from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMPANIES = ROOT / "config" / "companies.yaml"


def cmd_validate(args: argparse.Namespace) -> int:
    from .companies import load_companies
    from .validate import apply_fixes, validate_all, write_report

    companies = load_companies(args.companies, include_disabled=args.all)
    if args.only:
        companies = [c for c in companies if c.company.lower() in {o.lower() for o in args.only}]
    print(f"validating {len(companies)} companies...", file=sys.stderr)
    results = validate_all(companies, deep=not args.shallow)
    partial = bool(args.only)
    report_path = Path(args.companies).with_name("companies.report.md")
    text = write_report(results, report_path if not partial else None)
    print(text.split("\n\n")[1] if "\n\n" in text else text)
    if partial:
        print(text)
    else:
        print(f"report: {report_path}")
    if args.fix:
        n = apply_fixes(args.companies, results)
        print(f"applied {n} fixes to {args.companies}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from . import output
    from .sources.base import COMPANY_SOURCES
    from .companies import load_companies
    from .filters import FilterConfig
    from .run import default_paths, fetch_aggregators, fetch_all, make_clients, make_enricher, now_utc, select
    from .sources.aggregators import enabled_feeds, load_settings
    from .state import State

    load_dotenv(ROOT / ".env")
    now = now_utc()
    paths = default_paths(ROOT)
    state_path = Path(args.state or paths["state"])
    cfg = FilterConfig.load(args.filters)
    if args.hours:
        cfg.freshness_hours = args.hours

    companies = load_companies(args.companies)
    if args.company:
        wanted = {c.lower() for c in args.company}
        companies = [c for c in companies if c.company.lower() in wanted or c.token.lower() in wanted]
    if args.limit:
        companies = companies[: args.limit]
    if args.feeds_only:
        companies = []
    feed_settings = {} if args.no_feeds else enabled_feeds(load_settings(args.sources), args.feeds)
    if not companies and not feed_settings:
        print("no companies or feeds selected", file=sys.stderr)
        return 2

    state = State.load(state_path)
    if not state.loaded_from_disk:
        print(
            f"note: no state at {state_path} -- first-poll flood guard applies (only jobs posted <"
            f"{cfg.freshness_hours:g}h ago are reported)",
            file=sys.stderr,
        )

    # Tracker dedupe: required for a real run, optional (best effort) for --dry-run.
    from .sheets import SheetsNotConfigured, append_rows, load_tracker_index, open_sheet

    sh = tracker = None
    try:
        sh = open_sheet()
        tracker = load_tracker_index(sh)
        if not args.quiet:
            print(f"tracker loaded: {len(tracker)} entries", file=sys.stderr)
    except SheetsNotConfigured as exc:
        if not (args.dry_run or args.no_sheet):
            print(f"error: {exc} (or use --dry-run / --no-sheet)", file=sys.stderr)
            return 2
        print(f"note: sheet not configured ({exc}); skipping tracker dedupe", file=sys.stderr)

    print(f"polling {len(companies)} boards + feeds: {', '.join(feed_settings) or 'none'}...", file=sys.stderr)
    clients = make_clients()
    try:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=2) as pool:
            boards_f = pool.submit(fetch_all, companies, clients)
            feeds_f = pool.submit(fetch_aggregators, feed_settings, now, cfg)
            feeds = boards_f.result() + feeds_f.result()
        result = select(feeds, state, cfg, now, tracker, make_enricher(clients))
    finally:
        for c in clients.values():
            c.close()
    jobs = [m.job for m in result.matches]

    if not args.quiet:
        print(output.table(jobs))
    print(
        f"\n{len(jobs)} new matches | {sum(len(f.jobs) for f in feeds)} jobs on {len(feeds)} boards | "
        f"{len(result.failed)} boards failed",
        file=sys.stderr,
    )
    if args.explain:
        for reason, n in result.drop_reasons.most_common():
            print(f"  {n:6d}  {reason}", file=sys.stderr)
        for f in result.failed:
            print(f"  FAILED {f.company.company} ({f.feed}): {f.error}", file=sys.stderr)

    import os

    from .discovery import find_boards, render_markdown, summary_markdown, update_suggestions

    agg_jobs = [j for f in feeds if f.company.ats not in COMPANY_SOURCES for j in f.jobs]
    if args.dry_run:
        known = {(c.ats, c.token.lower()) for c in load_companies(args.companies, include_disabled=True)}
        new = {b for j in agg_jobs for b in find_boards(j)} - known
        if new:
            print(f"discovery: {len(new)} unlisted ATS boards seen on aggregator posts", file=sys.stderr)
        print("dry run: nothing written", file=sys.stderr)
    else:
        sugg = update_suggestions(
            agg_jobs,
            load_companies(args.companies, include_disabled=True),
            state_path.with_name("suggestions.json"),
            now,
        )
        if sugg:
            render_markdown(sugg, paths["matches"].parent / "companies.suggested.md")
        if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):  # set by GitHub Actions
            with open(summary_path, "a") as fh:
                fh.write(summary_markdown(sugg, now))
        records = [output.match_record(m.job, now, m.location_class) for m in result.matches]
        if records:
            path = output.write_json(records, paths["matches"], now)
            print(f"wrote {path}", file=sys.stderr)
        if sh is not None and not args.no_sheet:
            append_rows(sh, [output.sheet_row(j, now) for j in jobs])
            print(f"appended {len(jobs)} rows to the Scraper tab", file=sys.stderr)
        state.mark_reported([j.id for j in jobs], now)
        # tracked-elsewhere jobs never need re-checking either
        state.mark_reported([j.id for j, _ in result.already_tracked], now)
        pruned = state.prune(now)
        state.save(state_path)
        print(f"state saved ({len(state.jobs)} jobs, pruned {pruned})", file=sys.stderr)

    if feeds and len(result.failed) > len(feeds) / 2:
        print("error: more than half of the boards failed", file=sys.stderr)
        return 1
    return 0


def load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines) so local runs don't need python-dotenv."""
    import os

    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def cmd_gmail_auth(args: argparse.Namespace) -> int:
    from .sources.gmail_alerts import run_auth_flow

    token = run_auth_flow(args.client_secret)
    print("\nSuccess. Store these as GitHub Actions secrets (Settings -> Secrets and variables -> Actions):")
    print("  GMAIL_OAUTH_CLIENT_JSON = <the full contents of", args.client_secret + ">")
    print("  GMAIL_REFRESH_TOKEN     =", token)
    print("For local runs, put the same two values in .env (never commit it).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobscraper", description="Poll public ATS job boards for fresh frontend roles.")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="poll boards, filter, dedupe, write matches")
    r.add_argument("--dry-run", action="store_true", help="print matches; write nothing (no sheet, state, or JSON)")
    r.add_argument("--no-sheet", action="store_true", help="write JSON + state but skip Google Sheets")
    r.add_argument("--explain", action="store_true", help="print drop-reason counts and failed boards")
    r.add_argument(
        "--quiet",
        action="store_true",
        help="no job titles/links in output, counts only (use in CI: public-repo Actions logs are public)",
    )
    r.add_argument("--company", nargs="+", help="only these companies (name or token)")
    r.add_argument("--limit", type=int, help="only the first N companies")
    r.add_argument("--hours", type=float, help="override freshness_hours")
    r.add_argument("--companies", default=str(DEFAULT_COMPANIES))
    r.add_argument(
        "--feeds",
        nargs="+",
        help="only these aggregator feeds (hn remotive remoteok himalayas weworkremotely adzuna ...)",
    )
    r.add_argument("--no-feeds", action="store_true", help="company boards only")
    r.add_argument("--feeds-only", action="store_true", help="aggregator feeds only, no company boards")
    r.add_argument("--sources", default=None, help="path to sources.yaml")
    r.add_argument("--filters", default=None, help="path to filters.yaml")
    r.add_argument("--state", default=None, help="path to seen.json")
    r.set_defaults(func=cmd_run)

    g = sub.add_parser("gmail-auth", help="one-time local OAuth consent for reading job-alert emails (gmail.readonly)")
    g.add_argument(
        "client_secret", help="path to the OAuth client JSON downloaded from Google Cloud (Desktop app type)"
    )
    g.set_defaults(func=cmd_gmail_auth)

    v = sub.add_parser("validate-companies", help="check every board token resolves; auto-detect ATS")
    v.add_argument("--companies", default=str(DEFAULT_COMPANIES))
    v.add_argument("--fix", action="store_true", help="rewrite companies.yaml with corrections; disable dead boards")
    v.add_argument("--all", action="store_true", help="include disabled companies")
    v.add_argument("--shallow", action="store_true", help="only check the listed ats/token, no auto-detect")
    v.add_argument("--only", nargs="+", help="validate just these company names")
    v.set_defaults(func=cmd_validate)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return args.func(args)
