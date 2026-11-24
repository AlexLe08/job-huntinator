# job-huntinator

A small job-posting scraper for Alex Le's frontend job search. Twice a day it polls **public job-board APIs**
(no logins, no HTML scraping, no LinkedIn/Indeed scraping), keeps only fresh, relevant US roles, removes
anything already in the "Job Applications Tracker" Google Sheet, and appends new matches to a **Scraper** tab.
A Claude scheduled task then screens that tab and promotes the best rows to **Leads**
(see [Claude scheduled task](#claude-scheduled-task-paste-this)).

```
companies.yaml ─┐                                   ┌─> Scraper tab (Google Sheet)
sources.yaml  ──┼─> fetch ─> first-seen state ─> filters ─> tracker dedupe ─┼─> data/matches/YYYY-MM-DD.json
                │   (polite, parallel per host)  (48h)    (title/location/    │
                │                                         red flags)          └─> data/companies.suggested.md
```

## What it polls

| Kind | Sources |
|---|---|
| Company boards (`config/companies.yaml`) | Greenhouse, Lever, Ashby, Workable, Recruitee, SmartRecruiters, Workday |
| Aggregator feeds (`config/sources.yaml`) | Hacker News "Who is hiring?", Remotive, RemoteOK, Himalayas, We Work Remotely, Adzuna (free key), LinkedIn/Indeed **alert emails** in your Gmail (optional) |

About 270 company boards and 5–6 feeds take ~3 minutes per run.

## How "new" is decided

- Each job's ID gets a **first-seen** timestamp in `state/seen.json`. A job is reported once, and only if it was first seen in the
  last `freshness_hours` (48). Greenhouse's `updated_at` changes on every edit, so the scraper doesn't use it.
- **Flood guard:** the first time a board is polled (and after the state cache is lost), its existing jobs are recorded
  silently. Only jobs whose *own* posted date is within 48h are reported, so a cold start doesn't dump 20,000 old jobs.
- Aggregator posts that duplicate a company-board posting (same company + similar title) are dropped, so the employer link wins.

## Setup (local)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"                     # or, for the exact CI versions: uv sync --locked --extra dev
pytest -q                                   # ~190 tests, all offline (fixtures)
ruff check . && ruff format --check .       # lint + format (CI enforces both)
python -m jobscraper run --dry-run --explain   # live APIs, writes nothing
```

Optional but recommended: `pip install pre-commit && pre-commit install`. It runs ruff and a
[gitleaks](https://github.com/gitleaks/gitleaks) secret scan on every commit. VS Code picks up `.vscode/` (interpreter,
pytest, format-on-save with Ruff) and suggests the extensions in `.vscode/extensions.json`. For `git blame` to skip the
bulk-formatting commit, run `git config blame.ignoreRevsFile .git-blame-ignore-revs` once.

**Dependencies** are pinned in `uv.lock`; CI installs exactly those versions (`uv sync --locked`), so a new upstream
release can't break a scheduled run. After changing dependencies in `pyproject.toml`, run `uv lock` and commit the result.
Dependabot proposes monthly lockfile and action updates.

`--dry-run` prints matches and writes nothing: no sheet, no state, no JSON. Without sheet credentials, it skips tracker dedupe.

### Google Sheet access (service account)

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project, enable the **Google Sheets API**,
   create a **service account**, and add a JSON key. Download the key and keep it **outside** this repo.
2. Open the "Job Applications Tracker" sheet → **Share** → add the service account's `…@….iam.gserviceaccount.com`
   address as **Editor**. The code only *reads* Applications / Archive / Leads, and only *appends* to Scraper
   (it creates the tab with headers on the first run).
3. Copy `.env.example` to `.env` and fill in:
   - `GOOGLE_SHEET_ID`: the long ID in the sheet URL (`/spreadsheets/d/<ID>/edit`)
   - `GOOGLE_SERVICE_ACCOUNT_JSON`: the path to the key file locally (or the raw JSON)
4. `python -m jobscraper run --explain`. Run it twice: the second run should append 0 rows.

`.env`, key files, `state/` and `data/` are all gitignored. **Never commit credentials.**

## GitHub Actions

`.github/workflows/scrape.yml` runs at 11:30 and 17:30 UTC. That's 6:30am/12:30pm in winter (EST) and 7:30am/1:30pm
in summer (EDT). You can also trigger it from **Actions → scrape → Run workflow**, which has an optional dry-run switch
and an extra-args field such as `--hours 72` or `--feeds hn`.

Secrets go in the **`production` environment** (**Settings → Environments → production → Environment secrets**), not
as repo secrets. The scrape job runs in that environment, and the environment's deployment branches are limited to
`main`, so a workflow on any other branch can't read them.

| Secret | Required | Value |
|---|---|---|
| `GOOGLE_SHEET_ID` | yes | sheet ID |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | yes | the **full JSON contents** of the key file |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | no | free keys from [developer.adzuna.com](https://developer.adzuna.com/) |
| `GMAIL_OAUTH_CLIENT_JSON`, `GMAIL_REFRESH_TOKEN` | no | see [Gmail alerts](#linkedin--indeed-via-gmail-alerts-optional) |

A feed whose secrets are missing is skipped with a warning.

**State** lives in the Actions cache: it's restored at the start of each run and saved at the end. Nothing is committed back.
Caches unused for 7 days are evicted. That won't happen with two runs a day, and if it does, the flood guard keeps the next run sane.

**Public-repo notes:**
- Actions logs are public, so the workflow runs with `--quiet`, which logs counts only and never job titles or links.
  `test_cli_quiet_failures_leak_no_titles_or_job_links` guards this, including the board and enrichment failure paths.
- Workflow inputs reach the script only through environment variables (never `${{ }}` inside `run:`), so the
  extra-args field can't inject shell commands. Every action is pinned to a commit SHA.
- No artifacts are uploaded (public-repo artifacts can be downloaded by any signed-in GitHub user). In CI, matches
  only go to the sheet; the dated JSON is written for local runs.
- GitHub **disables scheduled workflows after 60 days without repo activity**. The `keepalive` job in `scrape.yml`
  re-enables the workflow through the API once a day, which resets that timer. If it ever lapses anyway, re-enable it
  from the Actions tab.

`tests.yml` runs on PRs and pushes to `main`: pytest on Python 3.11 and 3.13, plus a lint + audit job (ruff,
[zizmor](https://docs.zizmor.sh/) for workflow security, and pip-audit for known-vulnerable dependencies).

## Adding companies

Add one line to `config/companies.yaml`:

```yaml
  - {company: Acme, ats: greenhouse, token: acme, tier: boston}
```

`token` is the slug in the company's job-board URL:

| ATS | Careers URL looks like | token |
|---|---|---|
| greenhouse | `boards.greenhouse.io/acme`, `job-boards.greenhouse.io/acme`, or `?gh_jid=` on their site | `acme` |
| lever | `jobs.lever.co/acme` | `acme` |
| ashby | `jobs.ashbyhq.com/acme` | `acme` |
| workable | `apply.workable.com/acme` | `acme` |
| recruitee | `acme.recruitee.com` | `acme` |
| smartrecruiters | `jobs.smartrecruiters.com/Acme` | `Acme` (fetches US postings; add `country: null` for all) |
| workday | `acme.wd5.myworkdayjobs.com/AcmeCareers` | `token: acme, host: acme.wd5.myworkdayjobs.com, site: AcmeCareers` |

`tier` is free-form and shows in the sheet. The seed list uses `frontend-product`, `boston`, `rtp` and `remote-first`.

Then validate:

```bash
python -m jobscraper validate-companies                 # writes config/companies.report.md
python -m jobscraper validate-companies --fix           # apply corrections, disable dead boards
python -m jobscraper validate-companies --only "Acme"   # just one (prints, doesn't overwrite the report)
```

The validator checks each listed board. If a board is missing or empty, it tries the other ATSes with slug variants:

- **corrected:** a confident match. `--fix` applies it.
- **unsure:** a match from a loose guess (the first word of a multi-word name, e.g. "Help Scout" → `help`). `--fix`
  disables the entry and writes the candidate into `notes` for you to confirm.
- **dead:** no board found. `--fix` sets `disabled: true`.

Single-word names can still collide; for example, `greenhouse/remote` belongs to General Assembly. Check the
"board:" names in the report. After rejecting a wrong guess, add `no_autodetect: true` to the entry so it isn't suggested again. Workday can't be guessed, so copy `host`/`site` from the company's careers URL.

**Discovery:** aggregator posts that link to an ATS board missing from your list become suggestions with
ready-to-paste YAML lines. In GitHub Actions they're shown on each run's **summary page** (Actions → scrape → a run),
listing company names and board tokens only. Locally they're written to `data/companies.suggested.md`. Suggestions
drop off once the board is in `companies.yaml`. Nothing is added automatically.

## Tuning filters

Everything lives in `config/filters.yaml`. Patterns are case-insensitive regexes, matched against a normalized title
(lowercase, punctuation → spaces).

| Knob | What it does |
|---|---|
| `freshness_hours` | report window from first-seen (48) |
| `senior_mode` | `flag` (keep, add "senior" to Flags) or `drop` |
| `title.tier1` / `title.tier2` | strong vs adjacent title matches (Tier column shows `T1`/`T2`) |
| `title.generic_swe` + `generic_swe_exclude` | plain "Software Engineer" counts as T1 unless it names a non-frontend specialty (backend, ML, infra, …) |
| `title.exclude` | hard drops (staff, principal, lead, manager, director, head of, intern, embedded, firmware, data scientist, …) |
| `title.mobile_only` | iOS/Android titles are dropped unless they also mention web/frontend |
| `location.keep` | classes to keep: `MA`, `NC`, `us_remote`, `us_onsite`, `remote_unspecified`, `unknown` (`non_us` is dropped) |
| `location.flag` | classes that get a `loc?` flag (e.g. "Remote" with no country) |
| `red_flags` | 8+ years, clearance / TS/SCI, US-citizen-plus-clearance. `mode: drop` or `flag` |
| `dedupe.title_similarity` | company + title fuzzy-match threshold for "already tracked" (0.85) |

Use `--explain` to see why jobs were dropped, and `--hours 336` to judge filters on two weeks of postings:

```bash
python -m jobscraper run --dry-run --explain --hours 336 --company vercel stripe linear
```

Add a regression case to `tests/test_filters.py` whenever you change a pattern.

## CLI

```
python -m jobscraper run [--dry-run] [--no-sheet] [--quiet] [--explain]
                         [--company NAME_OR_TOKEN ...] [--limit N] [--hours H]
                         [--feeds hn remotive ...] [--no-feeds] [--feeds-only]
python -m jobscraper validate-companies [--fix] [--all] [--shallow] [--only NAME ...]
python -m jobscraper gmail-auth path/to/client_secret.json
```

The exit code is 1 if more than half of the boards fail. One failing board is logged and never stops the run.

## LinkedIn / Indeed via Gmail alerts (optional)

The scraper never touches LinkedIn or Indeed directly. Instead, it reads the job-alert emails they already send you:

1. On LinkedIn and Indeed, create job alerts for your searches (daily).
2. In Gmail, add a filter: from `jobalerts-noreply@linkedin.com` OR `jobs-noreply@linkedin.com` OR `alert@indeed.com` → apply label `job-alerts`.
3. In Google Cloud (same project is fine), enable the **Gmail API**. Then create an **OAuth client ID** of type *Desktop app*
   and download its JSON. While the consent screen is in "Testing" mode, add yourself as a test user.
   - Testing-mode refresh tokens expire after 7 days. To get a long-lived token, set the app's publishing status to
     "In production". It stays unverified, which is fine for your own account: you'll click through an
     "unverified app" warning once during consent.
4. Run `python -m jobscraper gmail-auth path/to/client_secret.json` locally, approve the **read-only** scope, and
   store the printed values as the `GMAIL_*` secrets.
5. Set `gmail_alerts.enabled: true` in `config/sources.yaml`.

These rows link to LinkedIn/Indeed rather than the employer, and have no description, so red-flag checks can't run on them.
The parser keys on job-view links. If an email redesign breaks it, the feed just returns fewer jobs.

## Politeness

Each request carries a `job-huntinator/0.1` User-Agent and a 15s timeout, with up to 3 retries on 429/5xx with backoff
(honoring `Retry-After`). There's a ~0.6–0.9s gap between requests **per host**; hosts run in parallel, but each one sees one
polite client. Aggregator terms are respected: Remotive and RemoteOK links point back to their listings, and Remotive is
polled 2×/day (they ask for ≤4).

## Next steps

Queued follow-up work (credentials, Gmail tuning, coverage, filter tuning) is in
[`docs/tasks/`](docs/tasks/README.md). Each file is a self-contained brief for a new Claude Code session.

## Layout

```
config/companies.yaml        company boards (+ companies.report.md from the validator)
config/filters.yaml          all filter knobs
config/sources.yaml          aggregator feeds on/off + settings
src/jobscraper/sources/      one module per ATS / feed (fetch + normalize [+ enrich])
src/jobscraper/filters.py    title / location / red-flag logic
src/jobscraper/state.py      first-seen state, freshness, flood guard
src/jobscraper/dedupe.py     URL / ATS-id / company+title matching
src/jobscraper/sheets.py     tracker read + Scraper append
src/jobscraper/run.py        pipeline
tests/fixtures/              trimmed real API responses
```

## Claude scheduled task (paste this)

This is the lead-screening part of Alex's scheduled Claude task (a Claude app scheduled task that runs at 8:45am and 2:45pm
US Eastern, after the scrapes, with push notifications on). The deployed prompt also has sheet/file IDs and a resume-drafting
part that runs when Alex replies in the session; those stay out of this public repo. To change the prompt, edit it in the
Claude app: a `RemoteTrigger` API update replaces the task's whole session config.

> **Job lead screening (reads the scraper's output; no web searching for discovery).**
>
> 1. Open the Google Sheet "Job Applications Tracker" → **Scraper** tab. Columns: Date Found (`YYYY-MM-DD H:MM`, US
>    Eastern; the hour may lack a leading zero) | Company | Role | Location | Link | Posted | Comp | ATS | Tier | Flags.
>    Take rows whose **Date Found** is within the last 24 hours. If there are none, find the newest Date Found in the
>    whole tab: if it is 48+ hours old, send a push notification "Scraper tab has no new rows since <date> – check the
>    GitHub Actions scrape." and stop; otherwise stop without notifying.
> 2. Read Applications / Archive / Leads columns A:F only. Skip any row whose Link, or Company + a near-identical Role,
>    is already in **Leads**, **Applications**, or **Archive** (runs overlap, so many rows will already be in Leads).
> 3. Screen each remaining row against Alex's profile: frontend engineer, ~4 years at CVS Health building Stencil.js
>    web-component libraries (global header/navigation, Search) consumed by Next.js apps; personal work in React, Next.js,
>    TypeScript, FastAPI, LLM apps; game development degree (RPI); based in Worcester, MA, open to relocating. Good fits:
>    frontend, frontend-leaning full-stack, UI / design-systems / web-components, general SWE; mid-level or
>    early-career-friendly.
>    - Tier is `T1`/`T2` (how closely the title matched; prefer T1) `·` the source: a company group (`frontend-product`,
>      `boston`, `rtp`, `remote-first`) or a feed (`himalayas`, `weworkremotely`, `remoteok`, `remotive`, `adzuna`, `hn`,
>      `linkedin-alert`, `indeed-alert`).
>    - Prefer Worcester/Central MA, Boston, Raleigh–Durham or US-remote; on-site/hybrid anywhere in the US is fine.
>    - Flags: `senior` is OK if the posting asks for ≤5–6 years; `loc?` means confirm the role is open to US
>      candidates; `no-desc` means the description wasn't fetched, so read the posting.
>    - Reject 8+ years required, active clearance, non-US-only, closed, spam or scams, if the scraper missed them.
>    - Shortlist from the row data, then open the posting for the top candidates (at most 8 fetches) to confirm it is
>      live and read the requirements.
>    - Feed rows (Tier ends in a feed name) don't link to the employer. Never fetch LinkedIn or Indeed. For a shortlisted
>      feed row, find the same posting on the employer's own ATS/careers page (their board URL, or one targeted
>      WebSearch) and use that link; if it isn't there, drop the row. WebSearch is only for this lookup.
> 4. Rank and pick the **top 5** (fewer if fewer are good). For each, append a row to **Leads**:
>    Date Found = today (MM/DD/YYYY) | Company | Role | Location | Job Posting Link = the employer link |
>    Status = `New lead` | Notes = one line (under ~200 chars) on why it fits and anything to watch
>    (e.g. "Senior, asks 5+ yrs; Stencil/design-system match; $150–180k").
> 5. Send a push notification: "N new leads: Company – Role; Company – Role; …". Then reply with a numbered list (best
>    first: company – role, location, posting age, link, why it fits, biggest gap). If nothing qualified, say so in one
>    line, add no rows, and don't notify.
> 6. In this part, only append to Leads: never edit or delete rows in the Scraper, Applications, or Archive tabs.
