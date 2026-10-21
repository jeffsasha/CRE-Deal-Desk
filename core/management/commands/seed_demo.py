from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from deals.models import Deal


class Command(BaseCommand):
    help = "Load fictional SAMPLE data into the isolated demo database (requires DEALDESK_DEMO=1)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Seed even if deals already exist in the demo database.")

    def handle(self, *args, force=False, **kwargs):
        if not settings.DEMO_MODE:
            raise CommandError("Refusing to load sample data: DEALDESK_DEMO is not set. Demo data must stay out of the real database.")
        if "demo" not in str(settings.DATABASES["default"]["NAME"]):
            raise CommandError("Refusing to seed: the active database is not the demo database.")
        if Deal.objects.exists() and not force:
            raise CommandError("The demo database already has deals. Delete var-demo/ to start over, or pass --force.")
        from demo.seed import seed

        with transaction.atomic():
            seed(log=lambda m: self.stdout.write(m))
        self.stdout.write(self.style.SUCCESS("Demo data loaded. Sign-in details: docs/DEMO.md"))
