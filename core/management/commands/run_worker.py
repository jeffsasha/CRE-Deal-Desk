import time

from django.core.management.base import BaseCommand

from core.jobs import run_pending
from deadlines.reminders import deliver_due


class Command(BaseCommand):
    help = "Process queued background jobs (document processing) and deliver due reminders."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run one pass and exit (for cron).")
        parser.add_argument("--interval", type=int, default=30)

    def handle(self, *args, once=False, interval=30, **kwargs):
        while True:
            jobs = run_pending()
            reminders = deliver_due()
            if jobs or reminders:
                failed = sum(1 for r in reminders if r.status == "failed")
                self.stdout.write(f"jobs={len(jobs)} reminders={len(reminders)} reminder_failures={failed}")
            if once:
                return
            time.sleep(interval)
