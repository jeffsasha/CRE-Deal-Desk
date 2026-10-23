# CRE Deal Desk

[![Django 5.2](https://img.shields.io/badge/Django-5.2-092E20?logo=django&logoColor=white)](https://www.djangoproject.com/)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![SQLite](https://img.shields.io/badge/Database-SQLite-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![English / 中文](https://img.shields.io/badge/Language-English%20%2F%20中文-A51C30)](#languages-中--en)

**Commercial real estate transactions, deadlines, contacts, and commissions in one local workspace.**

[Local setup](#setup-local-single-user) · [Demo mode](#demo-mode) · [Tests](#tests) · [Repository map](#repository-map)

A private commercial real estate transaction workspace for real estate teams. It keeps properties, deals, deadlines, checklists, contacts and commissions as separate linked records, and answers one daily question: **where does each deal stand, what date is next, and how much Commission is the brokerage still owed?**

How it works day to day (menu: Dashboard, Deals, Commissions, Contacts, Settings):

- **No sign-in locally.** The site only listens on 127.0.0.1 and signs every request in as the first administrator (`DEALDESK_AUTO_LOGIN`, on by default; demo mode keeps the login page).
- **Opening page** (`/`): a New York skyline photo with a slow drift and pointer parallax, the owner's badge hanging on a lanyard (drag it, click to flip) and a few headline numbers; **Enter dashboard** goes to `/dashboard/`. The badge portrait is read from `var/brand/` on this machine and is never committed: put a photo at `var/brand/photo.webp` (or .jpg/.png) and run `.venv/bin/python scripts/make_badge_photo.py` to make the black-and-white cut-out (works on a plain studio backdrop). Owner name and GitHub link: `DEALDESK_OWNER_NAME`, `DEALDESK_OWNER_GITHUB`.

- **A deal is its address.** New deal = kind (sale / lease / business), who the brokerage represents, and the street address. The property record behind it is found or created automatically, so every deal at the same address shares its history.
- **Deals page:** closed totals at the top (sales, lease consideration, the brokerage commission, with rolling numbers), then one table: open deals first, closed and terminated / lost at the end. Search by address or client.

- **Dashboard, top to bottom:** **Under Contract** — one timeline per deal (Effective Date → Feasibility Period → Closing Date, or Commencement Date for leases) with today's position, the next milestone and the brokerage's Commission; **Listings** — every property the brokerage has on the market for a seller or landlord, with asking price, days on market and listing expiration (red within 30 days); then buyer / tenant searches not yet under contract.
- **Listings:** a deal where the brokerage represents the seller or landlord and that is not yet Under Contract (new stage **Listed**). Enter the listing date, asking price or rent and the listing agreement expiration; the expiration goes on the calendar with reminders. When the deal goes Under Contract it moves up to the timeline section.
- **Key dates:** on each deal, enter the Effective Date and the contract periods by hand (Feasibility Period in days; Closing Date as a fixed date or days after the Effective Date). The rule engine calculates the dates: calendar days, the Effective Date itself not counted, weekends and holidays moved only when you tick that the contract says so. Changes keep their history.
- **Commission:** per deal, only the brokerage's expected amount and the payments received. A wrong payment is reversed, never deleted.

## Stack and why

| Concern | Choice |
|---|---|
| Web app | Django 5.2 (server-rendered pages, small vanilla JS). Built-in sign-in, sessions, CSRF protection, migrations, test runner. No front-end build step. |
| Database | SQLite for local single-user use (the current setup). PostgreSQL is supported via `DATABASE_URL` if the app is ever moved to a server; the same migrations and tests run on both. |
| Background work | `manage.py run_worker` delivers deadline reminders (or run `process_reminders` from cron). No Redis required. |
| Look | Solid cards with a neon edge and cursor spotlight on hover; a neon tube under the top bar pours pink → violet light over the page (an original take on React Bits Pro *Neon Reveal*: ignites on the first page of a visit, click the tube to re-light). Harvard crimson accents. English / 中文 switch. |
| Money | Integer cents everywhere. A blank amount means *unknown* (`None`) and is never treated as zero. |

There is no document upload: contract terms are typed in from the executed contract.

## Setup (local, single user)

DealDesk runs locally for one user. It listens on `127.0.0.1` only, so other computers and phones — even on the same Wi-Fi — cannot reach it. No cloud hosting is configured.

### Windows (PowerShell)

First-time setup (Python 3.12):

```powershell
cd CRE-Deal-Desk
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
```

Start the web app:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8020 --noreload
```

In a second PowerShell window, start the reminder worker:

```powershell
.\.venv\Scripts\python.exe manage.py run_worker
```

Open [http://localhost:8020](http://localhost:8020) and sign in with the account created above. Keep both terminals open; Ctrl-C stops each process. The macOS auto-start scripts below do not apply to Windows.

### macOS / Linux

First-time setup:

```bash
cd ~/CRE-Deal-Desk
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate         # also seeds stages, holiday calendars, checklist templates
.venv/bin/python manage.py createsuperuser # becomes an Administrator
```

Start DealDesk (web app on http://localhost:8020 plus the background worker for reminders):

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

Your data lives in `var/` (database `var/dealdesk.sqlite3`; import files in `var/private_storage/`). It is not in Git. Auto-start includes a daily backup; you can also run one any time:

```bash
.venv/bin/python manage.py backup        # writes var/backups/dealdesk-<timestamp>.tar.gz
```

Copy the backup archives somewhere off this Mac (an external drive or a private cloud folder). See [docs/BACKUP_AND_RESTORE.md](docs/BACKUP_AND_RESTORE.md).

Configuration is read from environment variables; see `.env.example`.

## Demo mode

```bash
./scripts/run_demo.sh      # http://127.0.0.1:8017
```

Demo mode uses its own database and storage (`var-demo/`). It loads a handful of clearly fictional "SAMPLE" deals with key dates and Commission figures. `seed_demo` refuses to run against the real database. Sign-in details and a walkthrough are in [docs/DEMO.md](docs/DEMO.md).

## Tests

```bash
.venv/bin/python manage.py test tests
```

There are 106 tests: the deadline rule engine (calendar and business days, trigger-day inclusion, holidays, weekend rules, DST), key dates entered by hand (history, reminders, weekend rule), brokerage Commission entry and reversal, listings, commission arithmetic, reporting totals, import duplicates and reversal, permissions, reminders, and an end-to-end run of the demo data through the HTTP layer in English and Chinese.

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

## Third-party code

- `static/vendor/three/` — three.js r169 (MIT), verified against the npm registry.
- `static/js/lanyard.js` — the React Bits Lanyard component, ported to a plain ES module.
- `static/js/rotating-text.js` — the React Bits RotatingText component, ported to a plain ES module on the Web Animations API (rotating word in the opening headline).
- `static/img/nyc-skyline.jpg` — photo by Luca Bravo on [Unsplash](https://unsplash.com/photos/_QdFx92MO2U), Unsplash License.

## Repository map

```
core/         users and roles, permissions, audit log, job queue, holidays, dashboard, settings, list framework
crm/          companies and contacts (client details restricted by role)
properties/   properties, parcels, spaces, rent roll, asking-price history, charges, facts with verification
deals/        deals, stages, parties, representation, key dates (keydates.py), prices, deposits, events, contract terms, activity
documents/    database tables only (kept so older records stay valid); there is no upload
deadlines/    engine.py (pure rules), services (revisions, preview), reminders, calendar export
checklists/   templates (acquisition, disposition, lease, land, business asset) and conditional checklist items
commissions/  brokerage expected / received per deal (simple.py) on top of agreements and the append-only ledger (ledger.py)
imports/      CSV/XLSX mapping, validation, duplicate detection, commit, safe reversal
reports/      volume and financial reports with drill-down to the source records
demo/         the demo seed (fictional data only)
tests/        focused tests and acceptance flows
```

## Operating notes

- **Enter only executed terms.** Key dates come from the executed contract. To record an amendment, change the value on the key dates form; the old value and the old date stay in history.
- **Deadlines come from rules.** Each deadline stores its trigger, period, day basis, trigger-day counting, holiday calendar, weekend rule (only if the contract establishes one), time and time zone, source clause, and revision history. A missing trigger shows "Awaiting Trigger", never a guessed date.
- **Commission status is derived** from the expected amount and immutable ledger entries (not received / partially received / received in full). Corrections are made by reversal.
- **Reports count deal-level consideration once** by actual closing date. Lease and business-asset consideration are always reported separately.
- **Drafted emails are never sent by the system.**

See [REQUIREMENTS.md](REQUIREMENTS.md) for the requirements checklist, and [docs/BACKUP_AND_RESTORE.md](docs/BACKUP_AND_RESTORE.md) for backups.

## Remaining dependencies

- **Email reminders** need SMTP settings. Until then they are recorded as failed delivery, and in-app reminders still go out.
- **Hosting:** DealDesk runs locally for a single user. Sharing it with the team would need a server and is not set up.
- **Real data:** your actual transaction records have not been loaded. Use Settings → Historical imports or manual entry.
