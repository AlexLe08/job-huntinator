# 01: Credentials and first live run

## Goal
Get the scraper writing to the real sheet locally, then from GitHub Actions on schedule.

## Context
The code is done, and offline tests plus live dry runs pass. Nothing has written to the sheet yet because the service account
doesn't exist. Repo: github.com/AlexLe08/job-huntinator (public). See README "Setup" and "GitHub Actions".

## Steps
**Alex (manual, in a browser):**
1. Google Cloud Console: create a project, enable the **Google Sheets API**, create a **service account**, and add a JSON key.
   Save the key **outside** this repo (e.g. `~/.config/job-huntinator/sa.json`).
2. Share "Job Applications Tracker" with the service account's email as **Editor**.
3. Create `.env` from `.env.example`: `GOOGLE_SHEET_ID=<id from the sheet URL>` and `GOOGLE_SERVICE_ACCOUNT_JSON=<path to key>`.

**Claude (in the session):**
4. Run `python -m jobscraper run --explain --no-feeds --company vercel linear`. Confirm the **Scraper** tab is created with the
   header `Date Found | Company | Role | Location | Link | Posted | Comp | ATS | Tier | Flags` and that the tracker loads
   (the count printed comes from Applications + Archive + Leads).
5. Run the full `python -m jobscraper run --explain`, then immediately run it again. **The second run must append 0 rows.**
6. Spot-check that dedupe works: pick a job already in Applications or Leads that's still open on a polled board, and confirm it
   was not appended. `--explain` shows `already-tracked:*` counts.
7. Delete the local `state/` and `data/` afterwards. Production state should start fresh from the Actions cache.

**Alex:**
8. GitHub repo → Settings → Environments → `production` (deployment branches: `main` only) → Environment secrets → add `GOOGLE_SHEET_ID`, and `GOOGLE_SERVICE_ACCOUNT_JSON`
   (the **contents** of the key file, not the path). Optional: `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` (free at developer.adzuna.com).
9. Actions → **scrape** → Run workflow, first with dry_run checked, then unchecked.

**Claude:**
10. `gh run list --workflow scrape.yml` and `gh run view <id> --log`: confirm success, counts-only logs (no titles/links), and
    "Cache saved". Trigger one more run and confirm the cache restores (`Cache restored from key: jobscraper-state-…`) and
    that it appended ~0 rows.

## Done when
- Two consecutive real runs, the second appending 0 rows, both locally and in Actions.
- Scheduled runs at 11:30 / 17:30 UTC show up on the Actions tab the next day.
- No secrets in git: `git status` is clean, `.env` is untracked.

## Watch out
- If Sheets returns 403, the sheet isn't shared with the service account, or the Sheets API isn't enabled on that project.
- Multi-line JSON doesn't work in `.env`. Locally, use the path to the key file.
