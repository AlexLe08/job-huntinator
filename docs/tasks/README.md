# Follow-up tasks

Each file is a self-contained brief for a fresh Claude Code session. Start the session in this repo and say
"Do docs/tasks/<file>". `CLAUDE.md` gives the session the project context and rules.

| # | Task | Who | Blocks |
|---|---|---|---|
| 01 | [Credentials and first live run](01-credentials-and-first-run.md) | Alex does the Google/GitHub clicks; Claude verifies | everything that writes to the sheet |
| 02 | [Rewrite the Claude scheduled task](02-rewrite-scheduled-task.md) | Claude | needs 01 (Scraper tab has rows) |
| 03 | [Gmail alerts: tune on real emails](03-gmail-alerts-real-emails.md) | Alex sets up alerts + OAuth; Claude tunes the parser | needs 01 |
| 04 | [More Workday boards (Boston / RTP coverage)](04-workday-coverage.md) | Claude | none |
| 05 | [Review the company list](05-company-list-review.md) | Claude proposes, Alex approves | none |
| 06 | [Tune filters after a week of real data](06-filter-tuning.md) | Claude + Alex | ~1 week after 01 |
| 07 | [Backlog / known limitations](07-backlog.md) | pick as needed | none |

When a task is done, tick it here and delete or archive its file in the same commit.
