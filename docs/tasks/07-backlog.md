# 07: Backlog and known limitations

Small items. Pick any; each should come with tests.

- **Workday 429 from GitHub runners (addressed):** Cloudflare 429s the first request to nearly every `*.myworkdayjobs.com`
  board from GitHub runners, while home connections get 200. More politeness won't fix an IP block, and spoofing a browser is
  off the table. Fix: CI runs with `--skip-ats workday`, and a launchd job on Alex's Mac runs a Workday-only pass
  (`scripts/workday-local.sh`, see README "Local Workday pass"). A self-hosted runner was rejected (risky on a public repo).
  Earlier side fixes: `PartialFetch` keeps earlier-query jobs on a later 429, and 3 consecutive first-request 429s skip the
  remaining Workday boards. Remaining gap: the pass only runs while the Mac is on and the repo's drive is mounted; check
  `state/workday/last-success` if Workday rows stop appearing.

- **Indeed alert digest (unverified):** real-email fixtures cover LinkedIn (both layouts) and Indeed's single-job
  "job match" email (`donotreply@match.indeed.com`, `cts.indeed.com/v3` redirect links). No classic multi-job Indeed
  alert from `alert@indeed.com` has arrived yet, so that layout is tested only on synthetic HTML. If one arrives, run it
  through `parse_message` and save a sanitized fixture (it likely uses the same `cts` redirects, which are already decoded).

- **Cache growth:** every run saves a new `jobscraper-state-<run_id>` cache entry. GitHub evicts old ones (10 GB repo limit), but a
  cleanup step (`gh cache delete` for all but the newest 5, needs `actions: write`) would keep things tidy.
- **60-day schedule disable:** GitHub disables scheduled workflows in public repos after 60 days without commits. Options are a
  monthly keep-alive (e.g. auto-commit the regenerated `companies.report.md`) or just a calendar reminder.
- **Stale postings:** jobs are reported once and never re-checked. Optional: mark Scraper rows whose job disappeared from the
  board (needs a write to the Scraper tab, so get Alex's OK first).
- **HN parsing:** `sources/hn.py` picks the role from the "Company | Role | Location" first line. Multi-role posts and posts not
  following the convention are partly missed. Could parse every matching role into separate jobs.
- **Adzuna:** `redirect_url` points at Adzuna, not the employer. Could follow the redirect once for matched jobs to store the
  employer URL (mind the rate limit).
- **Workday dates:** the list gives "Posted N Days Ago" (approximate); the exact `startDate` only comes from `enrich()`.
  This is fine for freshness (first-seen drives it), but the sheet's Posted column is approximate for non-enriched jobs.
- **Greenhouse pay ranges:** comp is regex-extracted from the description. Greenhouse's per-job endpoint can return structured
  pay ranges (`?pay_transparency=true`), but that costs one request per matched job.
- **Company suggestions are hard to read back:** discovery writes them only to the run's job summary (and the cached
  `state/suggestions.json`). The REST API doesn't expose job summaries, so a Claude session can't review them; during task 05
  a local feeds-only pass found none. Options: open the latest scrape run page and paste the "Company suggestions" table into
  the session, or print the suggestion count (no names) and keep reviewing via the run page.
- **Unsupported ATSes worth a source:** after task 05, several disabled companies sit on BambooHR (Aras, Validic, Prometheus
  Group), Breezy (Adwerx), Gem (Retool) and iCIMS (Atlassian/Loom, Jaggaer). BambooHR and Breezy have public JSON job lists;
  check their terms before adding one.
- **Action versions:** bump `actions/*` majors when GitHub deprecates them (watch for warnings on the run pages).
