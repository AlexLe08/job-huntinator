# Privacy policy

_Last updated: 2026-11-23_

job-huntinator is a personal, single-user tool. Its only user is its owner. It isn't offered to anyone else, and the
Google OAuth app it uses isn't meant for other people to sign in to.

## What it accesses

- **Gmail (read-only, `gmail.readonly` scope).** If its optional Gmail feed is enabled, it lists messages matching a
  fixed search (by default `label:job-alerts newer_than:3d`, at most 50 messages) and reads only those messages. From
  LinkedIn and Indeed job-alert emails it extracts the job title, company, location, and job link. It can't send,
  change, label, or delete email.
- **Google Sheets.** It reads the owner's job-tracking spreadsheet to avoid duplicates and appends new job rows to one
  tab of it, using a service account the owner shared that sheet with.
- **Public job-board APIs** (Greenhouse, Lever, Ashby and similar), which hold no personal data.

## What it stores, and where

- New job postings (title, company, location, link, date, pay if listed) are appended to the owner's own Google Sheet.
- A small state file of job IDs and first-seen timestamps is kept in the GitHub Actions cache so the same job isn't
  reported twice. Entries are deleted 60 days after a job was last seen.
- OAuth credentials are kept as encrypted GitHub Actions environment secrets, and in a local `.env` file that's
  never committed.
- Email contents aren't stored. Only the extracted job fields above are kept.
- Workflow logs record counts only, never email contents, job titles, or links.

## Sharing

The data isn't sold, shared, or sent to any third party. It goes only to the owner's own Google Sheet. Google user data
isn't used for advertising, and it isn't used to train AI or machine-learning models.

## Revoking access

The owner can revoke Gmail access at any time at <https://myaccount.google.com/permissions>. To remove the Sheets
access, unshare the sheet from the service account.

## Contact

Open an issue at <https://github.com/AlexLe08/job-huntinator/issues>.
