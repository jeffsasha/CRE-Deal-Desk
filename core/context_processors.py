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

THEME_OPTIONS = [
    ("blue-grey", _("Blue grey"), _("Calm"), _("Cool blues and neutral grey surfaces.")),
    ("ultraviolet", _("Ultraviolet original"), _("Original"), _("Original violet surfaces, pink light and crimson accents.")),
    ("sunset", _("Sunset"), _("Warm"), _("Warm orange accents with slate blue details.")),
    ("indigo", _("Indigo"), _("Elegant"), _("Indigo accents on crisp light or deep blue surfaces.")),
    ("minimal", _("Minimal mono"), _("Minimal"), _("Black and white, sharp corners and almost no shadow.")),
    ("ocean", _("Ocean mist"), _("Professional"), _("Soft ocean blues, slate surfaces and gentle corners.")),
    ("teal-gold", _("Teal and gold"), _("Crisp"), _("Deep teal with golden details and sharp corners.")),
    ("lemon", _("Lemon mono"), _("Playful"), _("Lemon yellow, black and white, with generous rounded corners.")),
    ("rose", _("Rose"), _("Soft"), _("Rose pink, gentle shadows and softly rounded corners.")),
    ("ice-orange", _("Ice and orange"), _("Retro"), _("Icy blues, warm orange details and a monospace feel.")),
    ("mint-violet", _("Mint and violet"), _("Fresh"), _("Mint surfaces, violet details and monospace typography.")),
    ("mecha", _("Crimson mecha"), _("Bold"), _("Deep charcoal, red and electric blue with sharp corners.")),
]


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
        "theme_options": THEME_OPTIONS,
        "workspace_base": "workspace_fragment.html" if workspace_page and request.headers.get("X-Workspace-Navigation") == "1" else "base.html",
    }
