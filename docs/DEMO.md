# Demo mode

Demo mode runs against `var-demo/demo.sqlite3` and `var-demo/private_storage`, completely separate from the real database. A banner on every page says so. All records are fictional and labeled `SAMPLE` or `(Demo)`. None of them reflect SKW transactions.

```bash
./scripts/run_demo.sh            # migrates, seeds once, serves http://127.0.0.1:8017
rm -rf var-demo                  # start over
```

## Demo sign-in

The password for all four accounts is `dealdesk-demo-only`, unless `DEALDESK_DEMO_PASSWORD` was set when seeding. These are test accounts for the local demo database only.

| Username | Role |
|---|---|
| `demo-admin` | Administrator |
| `demo-broker` | Broker, flagged as designated broker (receives reminders) |
| `demo-coordinator` | Coordinator (no commission access) |
| `demo-viewer` | Read-only |

## Where to see each acceptance flow

| # | Flow | Where |
|---|---|---|
| 1 | One property, terminated deal then closed deal | Properties → SAMPLE 1200 Example Industrial Pkwy → Overview (deal history) |
| 2 | Imported closed deal: known price, unknown commission | Deals → SAMPLE Historical sale → Commissions tab; Reports → "Closed deals with unknown commission"; Settings → Historical imports (row rejected for missing closing date, LOI kept as LOI) |
| 3 | Scanned contract reviewed with page references | Documents → Review queue → SAMPLE Westpark purchase agreement (scanned) |
| 4 | Ambiguous effective date left unresolved | Deals → SAMPLE Westpark → Contract & Dates: every deadline is "Awaiting Trigger" |
| 5 | Receipt-triggered deadline | SAMPLE Gessner → "Title and survey objection deadline", computed from the later of two recorded receipts |
| 6 | Unsigned extension does not change the closing date | SAMPLE Gessner → amendment banner → Second Amendment (Proposed — not effective) |
| 7 | Executed amendment updates dates, keeps history | SAMPLE Gessner → First Amendment (Applied); Closing date revisions; superseded terms; cancelled reminders |
| 8 | Survey received but still under review | SAMPLE Gessner → Checklist → Survey |
| 9 | Title commitment, owner's policy and property insurance are separate items | SAMPLE Gessner → Checklist |
| 10 | Proposed HVAC credit does not change the contract price | SAMPLE Gessner → Issues; price stays $2,850,000 |
| 11 | Partial receipts and separate designated-broker distributions | Commissions → SAMPLE buyer-side commission — 1200 Example Industrial |
| 12 | Dashboard reconciles with the ledger | Dashboard → Commissions card → any total → drill-down lists the ledger entries |
| 13 | Multi-property closing counted once | Reports → Closed sales volume (two-pad portfolio counted once, allocations shown) |
| 14 | Read-only user restricted | Sign in as `demo-viewer`: no edit controls, no commissions, 403 on direct POSTs |
| 15 | Extraction and reminder failures | Review queue → Failed (unreadable scan, manual entry offered); Settings → Reminder delivery log (email failures, in-app delivered) |
