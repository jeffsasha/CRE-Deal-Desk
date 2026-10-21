from django.apps import AppConfig
from django.db.models.signals import post_migrate


def ensure_defaults(sender, **kwargs):
    from checklists.templates_data import ensure_default_templates
    from deals.models import ensure_default_stages

    from .holidays import ensure_default_calendars

    ensure_default_stages()
    ensure_default_calendars()
    ensure_default_templates()


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "DealDesk core"

    def ready(self):
        post_migrate.connect(ensure_defaults, sender=self)
