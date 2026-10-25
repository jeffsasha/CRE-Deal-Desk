from django.conf import settings
from django.utils.translation import gettext_lazy as _

from .permissions import PERMISSIONS, has_perm

NAV = [
    ("dashboard", _("Dashboard"), "view"),
    ("deal_list", _("Deals"), "view"),
    ("commission_list", _("Commissions"), "commission.view"),
    ("settings_index", _("Settings"), "view"),
]
WORKSPACE_ROUTES = {"dashboard", "deal_list", "commission_list", "settings_index"}


def workspace(request):
    route = getattr(getattr(request, "resolver_match", None), "url_name", "")
    workspace_page = route if route in WORKSPACE_ROUTES else ""
    user = getattr(request, "user", None)
    perms = {}
    unread = 0
    if user is not None and user.is_authenticated:
        perms = {p.replace(".", "_"): has_perm(user, p) for p in PERMISSIONS}
        unread = user.notifications.filter(read_at__isnull=True).count()
    nav = [(name, label) for name, label, perm in NAV if perms.get(perm.replace(".", "_"))]
    return {
        "DEMO_MODE": settings.DEMO_MODE,
        "AUTO_LOGIN": settings.AUTO_LOGIN,
        "OWNER_NAME": settings.OWNER_NAME,
        "OWNER_GITHUB": settings.OWNER_GITHUB,
        "FIRM_NAME": settings.DEALDESK_FIRM_NAME,
        "can": perms,
        "nav_items": nav,
        "unread_notifications": unread,
        "workspace_page": workspace_page,
        "workspace_routes": WORKSPACE_ROUTES,
        "workspace_base": "workspace_fragment.html" if workspace_page and request.headers.get("X-Workspace-Navigation") == "1" else "base.html",
    }
