# 04: More Workday boards for Boston and RTP coverage

## Goal
Raise Boston/Worcester and Raleigh–Durham coverage by configuring Workday career sites for big local employers.

## Context
Only ~12 RTP and ~45 Boston boards are live. Many large local employers use Workday, which can't be auto-detected: each entry
needs `token` (tenant), `host` and `site`, all copied from the careers URL `https://<tenant>.wd<N>.myworkdayjobs.com/<site>`.
A 422 from `POST https://<host>/wday/cxs/<tenant>/<site>/jobs` means the tenant exists but the site name is wrong.
Working examples are in `config/companies.yaml` (Red Hat, Cisco, IQVIA, Fidelity, State Street, …).

Currently disabled because host/site is unknown: Liberty Mutual, Cimpress/Vistaprint, Pegasystems, Mass General Brigham,
Citrix (Cloud Software Group), NetApp, Avalara, Veradigm.

Candidates to add (check which use Workday): SAS, Bandwidth, Lenovo (Morrisville), Fortinet, Dell, IBM (RTP), MetLife (Cary),
Truist, Duke Health / UNC Health IT, Merck, Biogen (RTP + Cambridge), Akamai, MassMutual, BJ's, Hanover Insurance (Worcester),
UMass Chan / UMass Memorial (Worcester), Chewy (Boston office), MathWorks (custom ATS, skip if not Workday).

## Steps
1. For each company, find its careers page and follow the "search jobs" link. If it lands on `*.myworkdayjobs.com/<site>`,
   record tenant, wdN and site. Use WebSearch, or fetch the careers page. **Don't** brute-force site names
   against Workday.
2. Add `{company, ats: workday, token, host, site, tier}` lines, then run
   `python -m jobscraper validate-companies --only "<names>"`.
3. Dry-run them: `python -m jobscraper run --dry-run --explain --hours 336 --no-feeds --company <tokens>`. Check the Workday
   keyword queries (`DEFAULT_QUERIES` in `sources/workday.py`, overridable per company with `queries:`) catch the relevant roles.
4. Runtime check: each Workday board costs up to 6 queries × 5 pages. Keep a full run under ~6 minutes.

## Done when
- At least 10 more live Boston/Worcester/RTP boards, all validating OK, with the disabled entries either fixed or annotated with why.
