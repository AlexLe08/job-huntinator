# 02: Rewrite the Claude scheduled task to read the Scraper tab

## Goal
Replace the old scheduled task's blind WebSearch discovery with "screen and rank the scraper's output".

## Context
Today a scheduled Claude task WebSearches for postings, verifies them on the employer's ATS page, and appends leads to the sheet.
Search results are stale, so it often finds nothing. The scraper (task 01) now fills the **Scraper** tab twice a day, around
6:30–7:30am and 12:30–1:30pm US Eastern.

The task prompt to use is in README.md, section **"Claude scheduled task (paste this)"**.

## Steps
1. Find the existing scheduled task. It may be a Claude Code routine (`/schedule` lists them) or a claude.ai scheduled task.
   Ask Alex which one, and where, if it isn't obvious.
2. Replace its prompt with the README section. Keep any delivery settings it already has (push notification).
3. Schedule it **after** the scraper runs, e.g. 8:00am and 2:00pm US Eastern, so each run sees fresh rows.
4. The prompt takes rows whose Date Found is in the last 24h. With two runs a day the windows overlap, and the "skip if already in
   Leads" step prevents double-adding. Confirm Alex is fine with that, or switch to "rows since the previous run".
5. Do one manual run with Alex watching. Check that the chosen rows land in **Leads** with Status `New lead` and a one-line Note,
   that a push notification arrives, and that Scraper/Applications/Archive are untouched.

## Done when
- The scheduled task no longer uses WebSearch for discovery.
- One supervised run produced correct Leads rows and a notification (or correctly stayed silent with nothing to report).

## Notes
- Leads columns: Date Found | Company | Role | Location | Job Posting Link | Status | Notes.
- Profile details to screen against are in the README prompt. Write the name as "Alex" or "Alex Le" only.
