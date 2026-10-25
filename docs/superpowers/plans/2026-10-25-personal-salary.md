# Personal Salary Implementation Plan

> Execute inline using the existing Django patterns. Initially local only; the user subsequently authorized committing and pushing the implementation after verification.

**Goal:** A private My salary sidebar page with monthly net-pay columns and card-dialog entry/editing, populated from the user's supplied pay stubs.

**Architecture:** A small payroll app stores integer-cent paychecks scoped to the authenticated owner. The existing native editor dialog and workspace navigation are reused. Monthly columns are server-rendered HTML/CSS with explicit gaps for unrecorded months; pay-period month is independent of payment date.

**Global constraints:** Keep personal financial data only in local private storage/database; no image or real paycheck fixtures in source. Preserve uncommitted dashboard improvements. Do not combine wages with brokerage commissions. No external services or new chart dependencies.

- [x] Add regression checks for owner isolation, role permissions, exact money, duplicate checks, chart grouping by salary month, missing months and modal validation.
- [x] Implement paycheck model/migration, form, views, sidebar and theme-aware chart/table/modal integration.
- [x] Add Chinese labels while retaining existing business translations.
- [x] Back up the database, migrate and idempotently enter each distinct visible check for the local owner. Do not guess missing months or count duplicate visible stub sections.
- [x] Verify totals, create/edit/archive/restore behavior, browser chart and modal, and the complete test suite; request an independent review.

Ruling: follow the saved paycheck year after card submission so cross-year additions are visible. The user subsequently authorized committing and pushing source changes. Personal paycheck records, the supplied image and database backups remain local and excluded from Git.
