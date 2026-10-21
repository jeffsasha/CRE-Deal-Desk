"""Create a consistent backup of the database and private document storage.

SQLite: uses the online backup API (safe while the app is running).
PostgreSQL: runs pg_dump (custom format) — pg_dump must be on PATH.
See docs/BACKUP_AND_RESTORE.md for the restoration procedure.
"""
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Back up the database and private document storage to a timestamped .tar.gz."

    def add_arguments(self, parser):
        parser.add_argument("--dest", default=str(Path(settings.DATA_DIR) / "backups"))

    def handle(self, *args, dest, **kwargs):
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        stamp = timezone.now().strftime("%Y%m%d-%H%M%S")
        db = settings.DATABASES["default"]
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            if db["ENGINE"].endswith("sqlite3"):
                src = sqlite3.connect(str(db["NAME"]))
                out = sqlite3.connect(str(tmp / "database.sqlite3"))
                with out:
                    src.backup(out)
                src.close()
                out.close()
            elif db["ENGINE"].endswith("postgresql"):
                if not shutil.which("pg_dump"):
                    raise CommandError("pg_dump is not on PATH.")
                env = {**os.environ, "PGPASSWORD": db.get("PASSWORD", "")}
                subprocess.run(["pg_dump", "-Fc", "-h", db.get("HOST") or "localhost", "-p", db.get("PORT") or "5432",
                                "-U", db.get("USER", ""), "-f", str(tmp / "database.pgdump"), db["NAME"]],
                               check=True, env=env)
            else:
                raise CommandError(f"Unsupported database engine {db['ENGINE']}")
            (tmp / "BACKUP_INFO.txt").write_text(
                f"SKW DealDesk backup {stamp}\nengine={db['ENGINE']}\ndemo_mode={settings.DEMO_MODE}\n")
            archive = dest / f"dealdesk-{'demo-' if settings.DEMO_MODE else ''}{stamp}.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                for item in tmp.iterdir():
                    tar.add(item, arcname=item.name)
                tar.add(settings.PRIVATE_STORAGE_ROOT, arcname="private_storage")
        os.chmod(archive, 0o600)
        self.stdout.write(self.style.SUCCESS(f"Backup written to {archive}"))
