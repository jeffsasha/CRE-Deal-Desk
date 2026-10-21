from django.core.management.base import BaseCommand

from deadlines.models import Deadline
from deadlines.reminders import deliver_due, sync_reminders


class Command(BaseCommand):
    help = "Schedule reminders for open deadlines (idempotent) and deliver those that are due."

    def handle(self, *args, **kwargs):
        scheduled = 0
        for d in Deadline.objects.filter(state="open", computation="computed"):
            scheduled += len(sync_reminders(d))
        delivered = deliver_due()
        failed = sum(1 for r in delivered if r.status == "failed")
        self.stdout.write(f"Scheduled {scheduled} new reminder(s); processed {len(delivered)}; {failed} failed.")
