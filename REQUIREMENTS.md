# Requirements checklist

Status: `[x]` done and covered by tests or the demo · `[~]` partial (see note) · `[ ]` not started.
Keep this file current so later stages don't silently drop off. It is also shown in the app under Settings → Requirements checklist.

## Stage 1 — Foundations
- [x] Separate entities: Property, Space/Suite, Deal, Organization, Contact, Document (versioned), Deadline, Checklist item, Commission agreement / installment / allocation / ledger entry
- [x] One property, many deals over time; one deal, many properties (with optional suites); multiple clients and parties
- [x] Linked transactions (depends on, related, business asset linked to lease, successor)
- [x] Navigation: Dashboard, Properties, Deals, Calendar & Deadlines, Tasks & Checklists, Documents, Contacts & Companies, Commissions, Reports, Settings
- [x] Table, board (drag to change stage) and calendar views; search, filters, sorting, column choice, saved views, CSV export
- [x] Property records: address/suite, type, county, parcels, legal description, areas, units, owner/vesting, rent roll, asking-price history, charges with explicit units, facts with source/verification/date (industrial, restaurant/retail, zoning/use, flood)
- [x] Marketing statements are labeled as unverified
- [x] Property history kept when deals end (terminated, lost, closed)
- [x] Deal records: type, configurable stages, priority, team, responsible broker, parties and roles, representation per side, distinct price history, effective / contract / target / actual dates, deposits with confirmation and refundability, financing, next action and owner, blockers, termination reason, related deals
- [x] Deal tabs: Overview, Parties, Contract & Dates, Checklist, Documents, Issues, Activity, Commissions, Closing
- [x] Chronological activity log (system changes, calls, emails, notes, decisions)
- [x] Document library: categories, tags, full-text search (including OCR text), OCR status, version history, preview, access level, links to many records, originals vs generated summaries
- [x] Historical import (CSV/XLSX): field mapping, preview, row validation, duplicate detection, property/organization matching, batches, error report, source references, review before commit, safe reversal
- [x] Unknown stays unknown (no zero substitution); LOIs, counteroffers and proposals are never imported as closed
- [x] Pasted historical notes stored as original documents

## Stage 2 — Contract review, deadlines, checklists, amendments
- [x] Upload PDF, scanned PDF, images, DOCX; original preserved (SHA-256); file signature validation
- [x] OCR: macOS Vision (offline) or Tesseract; graceful when unavailable
- [x] Apparent document type and execution status detection; user-confirmed execution with evidence
- [x] Side-by-side viewer and review panel; accept / edit / reject; manual entry always available
- [x] Each value keeps document version, page, section, supporting text, confidence, explicit/calculated, review status, reviewer, timestamp
- [x] Safeguards: no invented dates or default periods; signature date ≠ effective date; uploaded ≠ executed; proposed amendment ≠ effective; conflicts and missing values become "Needs Review"; quotes checked against page text
- [x] Document content treated as untrusted data (system prompt, no tools, proposals only)
- [~] Claude extraction implemented (structured output, PDF input, refusal fallback) — **not yet run against the live API** (no key configured here)
- [x] Deadline engine: fixed / fixed-from-term / days after event / later-of / earlier-of; calendar or business days; trigger-day inclusion; holiday calendars; weekend rule only if established (with clause); time and time zone (DST-correct); source clause; dependencies (chaining); responsible person; confirmation; reminder schedule; original/current date; revision history
- [x] Receipt-triggered deadlines require the actual event date (never the upload date); "Awaiting Trigger" otherwise
- [x] Contractual deadlines separate from internal targets
- [x] Amendments: compare with approved terms, preview affected deadlines, require confirmed execution, apply, keep superseded terms/dates/documents, replace pending reminders while keeping history
- [x] Editable checklist templates (acquisition, disposition, lease, land, business asset) with conditions → Not Applicable with reason
- [x] Checklist item fields: owner, outside party, due date, deadline link, dependency, statuses (Not Started … Blocked), requested/received/reviewed/approved dates, evidence, follow-up, notes, unresolved issues; Received ≠ Reviewed ≠ Approved
- [x] Title commitment, owner's policy, lender's policy and property insurance are separate items
- [~] Checklist dependencies are recorded and shown but do not block status changes
- [x] Issue register: severity, status, discovery date, party statements with document date vs delivery date and receipt evidence, requested remedy and credit, counterparty response, proposed vs executed resolution, financial impact, disclosure finding ("not found in reviewed materials" ≠ "never disclosed")
- [x] Communication drafts are never sent by the system; the user marks them sent

## Stage 3 — Commissions, reporting, reminders, reliability
- [x] Commission agreement: payer, legal payee, side, percentage / flat / tiered / custom basis, adjustments, earning conditions, documents
- [x] Allocations: gross divided among SKW, co-brokers and referrals (paid through SKW or direct); internal distribution of SKW's share; no assumed split for the designated broker
- [x] Installments (e.g. lease execution and occupancy) with earned status, invoice, due and expected dates
- [x] Append-only ledger: receipts, distributions, direct payments, refunds, reversals, references, proof
- [x] Status derived from records; integer-cent arithmetic
- [x] Reports: closed sales volume by actual closing date (deal-level, counted once), pipeline, executed lease metrics (separate), business-asset consideration (separate), earned, cash receipts by date, designated broker's receipts by date, distributions, outstanding balances, closed deals with unknown commission
- [x] Filters: year, quarter, month, client, property type, transaction type, represented side, broker, title company
- [x] Every total drills down to its source records; CSV export
- [x] In-app reminders with configurable lead times; email when SMTP is configured; ICS download and private calendar feed
- [x] Duplicate prevention, delivery failure log with retry, acknowledgment ≠ completion
- [x] Roles: administrator, broker, coordinator, read-only — enforced on the server; commission and client details restricted
- [x] Private storage, signed short-lived user-bound download links, audit log of key changes, recoverable archiving
- [x] Backups (`manage.py backup`) and a documented restoration procedure
- [x] Failed extraction never destroys the file or blocks manual entry
- [x] Relational database (SQLite, local single-user; PostgreSQL also supported)
- [x] Demo mode isolated in its own database, with fictional labeled data

## Open items / recommended next
- [ ] Load real historical records (your spreadsheets and documents)
- [ ] Configure `ANTHROPIC_API_KEY` and validate extraction on real contracts
- [ ] Configure SMTP for email reminders
- [x] Start DealDesk automatically at login (macOS LaunchAgent, `scripts/install_autostart.sh`)
- [x] Daily automatic backup at 20:00 into `var/backups/`
- [ ] Copy backups off this Mac automatically (external drive or private cloud folder)
- [ ] Two-factor sign-in and login rate limiting
- [ ] Texas state holiday calendar (federal calendar provided; contracts may define holidays differently)
- [ ] Photo gallery and thumbnails for property images
- [ ] Delete / rename saved views from the UI
