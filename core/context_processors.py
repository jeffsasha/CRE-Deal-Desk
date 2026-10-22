from django.conf import settings
from django.utils.translation import gettext_lazy as _

from .permissions import PERMISSIONS, has_perm

NAV = [
    ("dashboard", _("Dashboard"), "view"),
    ("deal_list", _("Deals"), "view"),
    ("deadline_list", _("Calendar & Deadlines"), "view"),
    ("commission_list", _("Commissions"), "commission.view"),
    ("property_list", _("Properties"), "view"),
    ("contact_list", _("Contacts & Companies"), "view"),
    ("settings_index", _("Settings"), "view"),
]


def workspace(request):
    user = getattr(request, "user", None)
    perms = {}
    unread = 0
    if user is not None and user.is_authenticated:
        perms = {p.replace(".", "_"): has_perm(user, p) for p in PERMISSIONS}
        unread = user.notifications.filter(read_at__isnull=True).count()
    nav = [(name, label) for name, label, perm in NAV if perms.get(perm.replace(".", "_"))]
    return {
        "DEMO_MODE": settings.DEMO_MODE,
        "FIRM_NAME": settings.DEALDESK_FIRM_NAME,
        "can": perms,
        "nav_items": nav,
        "unread_notifications": unread,
    }
