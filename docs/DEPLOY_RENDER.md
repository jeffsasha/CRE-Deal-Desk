# Production deployment on Render

The root `render.yaml` creates a paid Docker web service, paid PostgreSQL 17
database, and a 1 GB private disk. Review the current resource prices and approve
them in Render before creating the Blueprint. No real transaction data or demo
accounts are copied from a local installation.

## First deployment

1. Connect Render to `jeffsasha/CRE-Deal-Desk` and create a Blueprint from `main`.
2. Review the service, database and disk charges, then deploy the Blueprint.
3. Wait for the web service to become Live. It automatically migrates the
   database, collects static assets and starts Gunicorn plus one document worker.
4. In the web service's Render Shell, run `python manage.py createsuperuser`.
   Choose a unique password there, not in a chat, Git commit or build log.
5. Open the service's HTTPS URL and sign in. Confirm English and Chinese pages,
   create a test deal, upload a non-confidential sample PDF, and verify processing.
6. Redeploy and verify that the test deal and document are still available.

The hostname and CSRF origin come from `RENDER_EXTERNAL_HOSTNAME`. For a custom
domain, also configure `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS`.
The trusted HTTPS proxy header is enabled only in the Render environment. Django
deploy checks may report the intentionally unset HSTS preload/include-subdomains
options; these are optional domain-wide policies, not needed for HTTPS sessions.
The SAMEORIGIN frame policy is intentional: the document viewer embeds authorized
files from the same site.

## Services and private data

- PostgreSQL holds records; `/var/data/private_storage` holds original uploads.
- Static files are collected under `/var/data/staticfiles` and served with
  WhiteNoise. Private files are never exposed by WhiteNoise.
- Web and worker run together because a Render disk cannot be shared by separate
  services. If either process exits the container exits, allowing Render to
  restart it. Keep one instance until storage is migrated to an object store.
- The smallest web plan is a starting point for light internal use. Monitor
  memory during real PDF OCR and increase the plan if needed. Migrations and
  restarts on this disk-backed service can briefly interrupt requests.
- Auto-deploy is initially off. Deploy a reviewed commit manually after tests.

## Integrations

Add `ANTHROPIC_API_KEY` in Render Environment to enable Claude extraction; never
commit it. The live Claude integration still needs an end-to-end API test. Without
the key, the labeled offline extractor runs. SMTP settings are optional; until
configured, only in-app reminders work. The image includes Tesseract and Poppler
for Linux OCR, plus PostgreSQL client tools for backups.

## Backups and existing local records

Render's paid database backups and disk snapshots protect separate resources;
they do not replace a verified coordinated restore. Run `python manage.py backup`
in Render Shell for a combined archive, store a copy outside the service and
follow [BACKUP_AND_RESTORE.md](BACKUP_AND_RESTORE.md). Set up a daily off-service
backup schedule before relying on the system for the only copy of real records.
Do not allow backup archives to fill the 1 GB disk; monitor usage and retention.

The first deployment starts empty. Existing `localhost:8020` records and uploaded
files are not Git-tracked and are **not** transferred by cloning or pushing.
Preserve the original installation and plan a separate data migration if needed.

## Local production-mode smoke test

Install `requirements.txt`, set production environment variables, migrate and
collect static assets, then run Gunicorn. For an HTTP-only local check set
`DJANGO_SECURE_SSL_REDIRECT=false` and request the login page and its stylesheet;
do not apply this override to the public deployment. Run the complete test suite
before each release. Building and testing the Docker image requires Docker;
the actual Render build and public URL must also be verified before reporting
the deployment complete.
