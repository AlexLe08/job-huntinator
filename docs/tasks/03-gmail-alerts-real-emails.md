# 03: Gmail job alerts, tuned on real emails

## Goal
Turn on the `gmail_alerts` feed so LinkedIn and Indeed alerts flow into the Scraper tab, and fix the parser against real emails.

## Context
`src/jobscraper/sources/gmail_alerts.py` parses alert emails by finding job-view links (`linkedin.com/.../jobs/view/<id>`,
Indeed `jk=`/`vjk=`) and reading title, company and location from the nearby text. It was written and tested only against
**synthetic** HTML (`tests/fixtures/gmail/*.html`), because no real alert emails were available. Expect layout differences.
Setup steps are in README → "LinkedIn / Indeed via Gmail alerts".

## Steps
1. **Alex:** create daily LinkedIn and Indeed job alerts, and a Gmail filter that applies the label `job-alerts` to mail from
   `jobalerts-noreply@linkedin.com` and `alert@indeed.com`. Wait until a few alerts have arrived.
2. **Alex:** Google Cloud → enable the Gmail API → OAuth client ID (Desktop app) → download the JSON (outside the repo) →
   OAuth consent screen: set publishing status to "In production" so the refresh token doesn't expire after 7 days.
3. **Claude:** run `python -m jobscraper gmail-auth <path>`. Alex approves the read-only scope. Put
   `GMAIL_OAUTH_CLIENT_JSON` (path locally) and `GMAIL_REFRESH_TOKEN` in `.env`.
4. **Claude:** set `gmail_alerts.enabled: true` in a scratch copy of `config/sources.yaml`, then run
   `python -m jobscraper run --dry-run --feeds gmail_alerts --hours 168 --explain`.
   Compare the parsed jobs with what the emails show: title, company and location for every job card, and no junk entries
   like "See all jobs".
5. Fix the parser. Save 1–2 real alert emails as fixtures **with personal data removed** (your name, email, tracking
   params with IDs, unsubscribe links) and add tests next to the synthetic ones.
6. Enable the feed in `config/sources.yaml`, and Alex adds the two `GMAIL_*` secrets to GitHub (client JSON **contents**).

## Done when
- A real dry run parses every job card in a LinkedIn alert and an Indeed alert correctly.
- Real-email fixtures (sanitized) are covered by tests, and CI is green.

## Notes
- Scope must stay `gmail.readonly`. Never print email contents in CI (the `--quiet` flag already hides titles).
- These rows link to LinkedIn/Indeed, not the employer, and have no description, so red-flag checks don't run on them.
