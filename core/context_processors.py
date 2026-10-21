from django.conf import settings

from .permissions import PERMISSIONS, has_perm

NAV = [
    ("dashboard", "Dashboard", "view"),
    ("property_list", "Properties", "view"),
    ("deal_list", "Deals", "view"),
    ("deadline_list", "Calendar & Deadlines", "view"),
    ("checklist_list", "Tasks & Checklists", "view"),
    ("document_list", "Documents", "view"),
    ("contact_list", "Contacts & Companies", "view"),
    ("commission_list", "Commissions", "commission.view"),
    ("report_index", "Reports", "view"),
    ("settings_index", "Settings", "view"),
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
