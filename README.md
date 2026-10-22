# SKW DealDesk

A private commercial real estate transaction workspace for SKW Realty LLC. It keeps properties, deals, documents, deadlines, checklists, contacts and commissions as separate linked records, and answers one daily question: **what needs attention, what could delay or jeopardize a deal, and what documents or money are still missing?**

## Stack and why

| Concern | Choice |
|---|---|
| Web app | Django 5.2 (server-rendered pages, small vanilla JS). Built-in sign-in, sessions, CSRF protection, migrations, test runner. No front-end build step. |
| Database | SQLite for local single-user use (the current setup). PostgreSQL is supported via `DATABASE_URL` if the app is ever moved to a server; the same migrations and tests run on both. |
| Files | Private storage under `DEALDESK_DATA_DIR/private_storage`, never served publicly. Downloads use signed links that are user-bound and expire in 10 minutes. |
| Background work | Jobs live in a database queue and run via `manage.py run_worker`. Reminders are delivered by the same worker or by cron (`process_reminders`). No Redis required. |
| OCR | macOS Vision (offline, `bin/vision_ocr`), or Tesseract on Linux. If neither is available the file is still stored and manual entry still works. |
| Contract extraction | Claude (`claude-opus-5-5`, structured JSON output, PDF input) when `ANTHROPIC_API_KEY` is set. Otherwise a labeled offline pattern extractor runs. Either way the output is **proposals only**. |
| Money | Integer cents everywhere. A blank amount means *unknown* (`None`) and is never treated as zero. |

Extraction is kept separate from the deterministic logic. `deadlines/engine.py` and `commissions/ledger.py` never read unreviewed AI output.

## Setup (local, single user)

DealDesk runs on this Mac for one user. It listens on `127.0.0.1` only, so other computers and phones — even on the same Wi-Fi — cannot reach it. No cloud hosting is configured.

First-time setup:

```bash
cd ~/SKW-DealDesk
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./scripts/build_ocr.sh                     # macOS only: offline OCR for scanned PDFs
.venv/bin/python manage.py migrate         # also seeds stages, holiday calendars, checklist templates
.venv/bin/python manage.py createsuperuser # becomes an Administrator
```

Start DealDesk (web app on http://localhost:8020 plus the background worker for document processing and reminders):

```bash
./scripts/run_local.sh
```

It keeps running while that terminal stays open; Ctrl-C stops both. If it is already running, the script says so and exits.

Or have macOS run it for you (recommended):

```bash
./scripts/install_autostart.sh     # start at login, restart after a crash, daily backup at 20:00
./scripts/uninstall_autostart.sh   # undo; data and backups are kept
```

With auto-start installed, everyday use is just opening http://localhost:8020 — no terminal needed. Logs are in `var/logs/`. Without it, run `./scripts/run_local.sh` whenever the page does not load (the terminal was closed or the Mac restarted).

Your data lives in `var/` (database `var/dealdesk.sqlite3` and uploaded files in `var/private_storage/`). It is not in Git. Auto-start includes a daily backup; you can also run one any time:

```bash
.venv/bin/python manage.py backup        # writes var/backups/dealdesk-<timestamp>.tar.gz
```

Copy the backup archives somewhere off this Mac (an external drive or a private cloud folder). See [docs/BACKUP_AND_RESTORE.md](docs/BACKUP_AND_RESTORE.md).

Configuration is read from environment variables; see `.env.example`.

## Demo mode

```bash
./scripts/run_demo.sh      # http://127.0.0.1:8017
```

Demo mode uses its own database and storage (`var-demo/`). It loads clearly fictional "SAMPLE" records arranged to show each acceptance flow. `seed_demo` refuses to run against the real database. Sign-in details and a walkthrough are in [docs/DEMO.md](docs/DEMO.md).

## Tests

```bash
.venv/bin/python manage.py test tests
```

There are 112 tests: the deadline rule engine (calendar and business days, trigger-day inclusion, holidays, weekend rules, DST), amendments, commission arithmetic, reporting totals, import duplicates and reversal, permissions, reminders, document safeguards, and an end-to-end run of all 15 acceptance flows through the HTTP layer. They pass on SQLite and on PostgreSQL 17.

## Languages (中 / EN)

The switch in the top bar changes the whole interface between English and Simplified Chinese; the choice is remembered per browser. Text you enter (deal names, notes, deadline names) is shown as entered, and computed explanations such as deadline rule text stay in English.

After adding or changing interface text:

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python manage.py collect_strings
.venv/bin/python manage.py makemessages -l zh_Hans --ignore=.venv --ignore=var --ignore=var-demo --ignore=tests --ignore=locale --no-obsolete
.venv/bin/python locale/fill_zh.py      # lists any strings that still need a Chinese entry in locale/zh_extra_*.py
.venv/bin/python manage.py compilemessages -l zh_Hans --ignore=.venv
```

## Repository map

```
core/         users and roles, permissions, audit log, job queue, holidays, dashboard, settings, list framework
crm/          companies and contacts (client details restricted by role)
properties/   properties, parcels, spaces, rent roll, asking-price history, charges, facts with verification
deals/        deals, stages, parties, representation, prices, deposits, trigger events, contract terms, issues, activity
documents/    upload validation, versions, OCR/text, classification, extraction (claude.py / pattern.py), safeguards, review, amendments
deadlines/    engine.py (pure rules), services (revisions, preview), reminders, calendar export
checklists/   templates (acquisition, disposition, lease, land, business asset) and conditional checklist items
commissions/  agreements, allocations, installments, append-only ledger, derived status (ledger.py)
imports/      CSV/XLSX mapping, validation, duplicate detection, commit, safe reversal
reports/      volume and financial reports with drill-down to the source records
demo/         sample document generators and the demo seed (fictional data only)
tests/        focused tests and acceptance flows
```

## Operating notes

- **Execution is never assumed.** Uploaded files start as "Unknown". Contract terms publish only after a user confirms execution, with evidence. Unsigned amendments stay "Proposed — not effective".
- **Deadlines come from rules.** Each deadline stores its trigger, period, day basis, trigger-day counting, holiday calendar, weekend rule (only if the contract establishes one), time and time zone, source clause, and revision history. A missing trigger shows "Awaiting Trigger", never a guessed date.
- **Commission status is derived** from agreements, installments and immutable ledger entries. Corrections are made by reversal. No split to the designated broker is assumed.
- **Reports count deal-level consideration once** by actual closing date. Lease and business-asset consideration are always reported separately.
- **Document text is untrusted data.** It is never treated as instructions. Drafted emails are never sent by the system.

See [REQUIREMENTS.md](REQUIREMENTS.md) for the requirements checklist, and [docs/BACKUP_AND_RESTORE.md](docs/BACKUP_AND_RESTORE.md) for backups.

## Remaining dependencies

- **Claude extraction** needs an `ANTHROPIC_API_KEY`. The integration is implemented against the current SDK (structured outputs, PDF input, refusal fallback) but has **not been exercised against the live API** here. Until a key is set, the offline extractor runs.
- **Email reminders** need SMTP settings. Until then they are recorded as failed delivery, and in-app reminders still go out.
- **Hosting:** DealDesk runs locally on this Mac for a single user. Sharing it with the team would need a server and is not set up.
- **Real data:** your actual transaction records have not been loaded. Use Settings → Historical imports or manual entry.
