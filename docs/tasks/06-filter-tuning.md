# 06: Tune filters after a week of real data

## Goal
Use a week of real Scraper rows, plus what Alex promoted or ignored, to cut false positives and catch missed roles.

## Context
Filters live in `config/filters.yaml` (see the README table). They were tuned against live postings once, but haven't been
checked against Alex's actual choices. Leads (promoted) and Scraper (everything) together show what's useful.

## Steps
1. Read the Scraper and Leads tabs (read-only). Bucket the Scraper rows: promoted, plausible but skipped, and obviously wrong.
2. For the "obviously wrong" rows, find the pattern responsible (title tier, generic SWE, location class, `loc?`) and propose a
   change. Common candidates: more `generic_swe_exclude` specialties, `remote_unspecified` handling, tier2 noise.
3. Look for misses. Run `python -m jobscraper run --dry-run --explain --hours 168` and list jobs dropped as `title-no-match`,
   `title-swe-specialty` or `location:*` whose titles look frontend-relevant. Consider adding tier1 patterns.
4. Check volume. If there are more than 25 rows/day, the screener is overloaded; tighten tier2 or switch `senior_mode`. If there are
   fewer than ~3/day, loosen the filters.
5. Every change gets a regression case in `tests/test_filters.py`. Show Alex the before/after counts on the same 7-day dry run
   before committing.

## Done when
- Alex agrees with the changes, tests are green, and the before/after numbers are noted in the commit message.
