# 07: Backlog and known limitations

Small items. Pick any; each should come with tests.

- **Workday 429 from GitHub runners (biggest gap):** every scheduled run since 2026-11-23 gets HTTP 429 from Cloudflare on the
  *first* request to nearly every `*.myworkdayjobs.com` board (only Vertex on wd501 sometimes gets through), while the same boards
  return 200 from a home connection. So the ~20 Workday boards only work in local runs. More politeness won't fix an IP block,
  and spoofing a browser to get past it is off the table. Options: run a Workday-only pass from a non-datacenter machine (e.g. a
  launchd job on Alex's Mac appending to the Scraper tab), or a self-hosted runner; still needs Alex's decision. Side fixes
  done: a 429 on a later query keeps the jobs from earlier queries (`PartialFetch`, shown as "partial" in the run summary),
  and after 3 consecutive first-request 429s the remaining Workday boards are skipped without a request.

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
- **Action versions:** bump `actions/*` majors when GitHub deprecates them (watch for warnings on the run pages).
