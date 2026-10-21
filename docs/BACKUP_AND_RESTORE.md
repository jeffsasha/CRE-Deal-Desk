# Backup and restoration

## What a backup contains

`manage.py backup` writes `DEALDESK_DATA_DIR/backups/dealdesk-YYYYMMDD-HHMMSS.tar.gz` (mode 600) containing:

- `database.sqlite3` (taken with SQLite's online backup API, safe while running), **or** `database.pgdump` (PostgreSQL custom format from `pg_dump`)
- `private_storage/`: every original uploaded file and import file
- `BACKUP_INFO.txt`: timestamp, database engine, demo flag

Schedule it daily, for example with cron:

```
15 2 * * *  cd /srv/SKW-DealDesk && .venv/bin/python manage.py backup
```

Copy the archives off the machine (for example to encrypted cloud storage), and test a restore at least quarterly.

## Restore procedure

1. Stop the web server and the worker.
2. Unpack the archive into a temporary folder: `tar -xzf dealdesk-YYYYMMDD-HHMMSS.tar.gz -C /tmp/restore`
3. Restore the database:
   - **SQLite:** move the current `var/dealdesk.sqlite3` aside, then copy `/tmp/restore/database.sqlite3` to `var/dealdesk.sqlite3`.
   - **PostgreSQL:** `createdb dealdesk_restored && pg_restore -d dealdesk_restored /tmp/restore/database.pgdump`, then point `DATABASE_URL` at it, or rename databases during a maintenance window.
4. Restore files: move the current `var/private_storage` aside and copy `/tmp/restore/private_storage` into its place.
5. Run `manage.py migrate`. This is a no-op unless the code is newer than the backup.
6. Start the app and the worker. Check that the dashboard loads, open a document, and confirm the audit log shows the latest expected entries.

## Recoverable archiving vs. deletion

Day-to-day "delete" in the app is **archiving**. Records are hidden but kept, and can be restored from Settings → Archived records. Ledger entries are never edited or deleted; corrections are reversals. Import batches can be reverted, which removes only records the batch created that nobody has since edited or used.
