# 05: Review the company list

## Goal
Recover dead entries that simply moved ATS, confirm the uncertain matches, and add companies Alex cares about.

## Context
`config/companies.report.md` holds the last full validation: 261 OK, 95 dead, 7 empty, 4 unsure, 10 skipped.
"Dead" means no board was found on Greenhouse, Lever, Ashby, Workable or Recruitee under the guessed slugs. Many of these
companies are still hiring on a different slug or ATS (or their own ATS, e.g. HubSpot, Wayfair, Etsy, Shopify).

**Unsure, needs a human decision** (the possible match is written in each entry's `notes`):
Help Scout → greenhouse/help? · Forward Financing → greenhouse/forward? · Nomad Health → ashby/nomad? ·
Prometheus Group → ashby/prometheus?

## Steps
1. For each unsure entry: open the candidate board (`https://jobs.ashbyhq.com/<token>`, `https://job-boards.greenhouse.io/<token>`)
   and check it's the same company. Apply it or add `no_autodetect: true`.
2. For dead entries, prioritise frontend-heavy and Boston/RTP ones (e.g. Retool, Framer, Postman, Grammarly, Loom, Coda, dbt Labs,
   Superhuman, The Browser Company, Rippling, Canva, Cal.com, Convex, Liveblocks, DuckDuckGo, HubSpot, Wayfair, Rapid7,
   DataRobot, Pendo-area RTP companies). Find the real careers URL with WebSearch or by fetching their careers page, then fix
   `ats`/`token`. Leave companies on custom ATSes disabled, with `notes: custom ATS`.
3. Check the GitHub run summary pages for **Company suggestions** (boards seen on HN and remote-board posts) and add good fits.
4. Ask Alex for must-include or exclude companies (e.g. exclude current/past employers if desired).
5. Run `python -m jobscraper validate-companies --fix` (~10 min). Review the "corrected" section for wrong-company matches,
   especially single-word names.

## Done when
- No unsure entries remain, the dead list is triaged, and the enabled count is ≥ 280. Commit the YAML and the regenerated report.
