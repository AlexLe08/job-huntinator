# CLAUDE.md

Context for Claude Code sessions working in this repo. Read `README.md` for user-facing docs, and
`docs/tasks/` for the queued follow-up tasks. Each task file is self-contained.

## What this is

Alex Le's job-posting scraper. It polls public job-board APIs twice a day and appends fresh, relevant US frontend roles to the
"Scraper" tab of the "Job Applications Tracker" Google Sheet. A separate Claude scheduled task screens that tab
and promotes the top rows to "Leads". The pipeline: fetch → first-seen state → filters → tracker dedupe → output.

## Hard rules

- **Public repo.** Never commit secrets, credentials, the sheet ID, Alex's email, or phone number. `.env`, `state/`,
  `data/` and key files are gitignored; keep it that way.
- **CI logs are public.** The workflow runs `--quiet`, which logs counts only. Never print job titles or links, and never
  print tracker contents in CI. Don't add artifact uploads (they're downloadable by any GitHub user).
- Write the user's name as **"Alex"** or **"Alex Le"**, never "Alexander".
- **Public ATS/feed APIs only.** No LinkedIn/Indeed scraping and no HTML scraping. LinkedIn/Indeed coverage comes only from alert
  emails in Alex's own Gmail (read-only).
- Sheets: read Applications / Archive / Leads; **only append** to Scraper. Never edit or delete other tabs.
- Commit or push only when Alex asks; end commit messages with the attribution lines the harness provides.
- Workflows: pass `inputs.*` / event data to `run:` steps through `env:`, never `${{ }}` inside the script. Pin actions
  to commit SHAs (Dependabot bumps them). `zizmor .` must stay clean.
- Logs must never contain job titles or job URLs, including in error/warning paths: log job IDs and HTTP status instead.

## Commands

```bash
source .venv/bin/activate            # or: python3 -m venv .venv && pip install -e ".[dev]"
pytest -q                            # offline, fixtures only; keep it green
ruff check . && ruff format --check .   # CI enforces both; `ruff format .` to fix
uv lock                              # after any dependency change in pyproject.toml; commit uv.lock
python -m jobscraper run --dry-run --explain              # live APIs, writes nothing
python -m jobscraper run --dry-run --explain --hours 336 --company vercel   # judge filters on 2 weeks of data
python -m jobscraper validate-companies [--fix] [--only NAME]   # full run ~6–10 min, rewrites config/companies.report.md
```

A full live dry-run polls ~270 boards and feeds in ~3 minutes.

## Layout

- `config/companies.yaml`: boards (`company, ats, token, tier`, plus `host`/`site` for workday, `disabled`, `no_autodetect`, `notes`)
- `config/filters.yaml`: every filter knob. `config/sources.yaml`: aggregator feeds.
- `src/jobscraper/sources/`: one module per ATS/feed. Company sources expose `fetch(client, company)`, `normalize(raw, company)`,
  and optionally `enrich(client, job, company)`, which is called only for jobs that pass the cheap title/location filters.
  Register ATS sources in `sources/base.py` and feeds in `sources/aggregators.py`.
- `filters.py` (title / location / red flags), `state.py` (first-seen and flood guard), `dedupe.py`, `sheets.py`, `run.py`
  (pipeline + cross-source merge), `discovery.py` (suggested boards → GitHub job summary), `cli.py`.
- `tests/fixtures/`: trimmed **real** API responses. When adding a source, save a trimmed real response, and strip personal
  data (recruiter names, personal emails, HN usernames) before committing.

## Conventions

- Every filter change gets a regression case in `tests/test_filters.py` (table-driven).
- `PoliteClient` (`http.py`) is the only HTTP path. It handles the UA, timeouts, retries with backoff, and per-host spacing.
  Use one client per host so hosts run in parallel and each stays polite.
- One failing board or feed must never fail the run. Catch the error, log it, and move on. Exit 1 only if more than 50% of boards fail.
- Job IDs are `<source>:<token>:<native id>` (or `<feed>:<id>`). State keys depend on them, so don't change ID formats casually:
  every existing job would look new.
