# Demo mode

Demo mode runs against `var-demo/demo.sqlite3`, completely separate from the real database. A banner on every page says so. All records are fictional and labeled `SAMPLE` or `(Demo)`. None of them reflect SKW transactions.

```bash
./scripts/run_demo.sh            # migrates, seeds once, serves http://127.0.0.1:8017
rm -rf var-demo                  # start over
```

## Demo sign-in

The password for all four accounts is `dealdesk-demo-only`, unless `DEALDESK_DEMO_PASSWORD` was set when seeding. These are test accounts for the local demo database only.

| Username | Role |
|---|---|
| `demo-admin` | Administrator |
| `demo-broker` | Broker |
| `demo-coordinator` | Coordinator (no Commission access) |
| `demo-viewer` | Read-only |

## What the sample deals show

Dates are relative to the day the demo was seeded.

| Deal | Shows |
|---|---|
| SAMPLE Gessner office purchase | In the Feasibility Period: Feasibility = 30 days, Closing = 60 days after the Effective Date |
| SAMPLE Westpark retail center sale | Feasibility already ended (not counted as overdue); fixed Closing Date; contract moves weekend deadlines to the next business day |
| SAMPLE Kirby dental suite lease | Lease timeline: Effective Date → Commencement Date |
| SAMPLE Harbor Cafe business sale | Key dates and Commission not entered yet |
| SAMPLE Bayou warehouse purchase | On hold (listed last) |
| SAMPLE Westheimer retail pad sale | Listing: asking $2,450,000, listing expires in 20 days (shown in red) |
| SAMPLE Memorial office suite lease | Listing for lease: asking rent in $/SF/yr, Commission not entered |
| SAMPLE Katy flex building sale | Listing at the LOI stage (still a listing until Under Contract) |
| SAMPLE Medical office search | Buyer search, shown below the listings |
| SAMPLE Example Industrial sale | Closed; Commission received in two payments (Commissions → Closed); the same property also shows an earlier terminated deal |

Sign in as `demo-viewer` to see the read-only view: no edit controls and no Commission figures.
