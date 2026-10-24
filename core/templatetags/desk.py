from datetime import date, datetime

from django import template
from django.utils import timezone
from django.utils.translation import gettext, ngettext
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from core.choices import RATE_UNIT_SUFFIX
from core.money import Total, format_cents
from core.permissions import has_perm

register = template.Library()

_ASSET_VERSIONS = {}


@register.simple_tag
def asset(path):
    """Static URL with a content-based version so browsers never use a stale copy."""
    import hashlib
    from pathlib import Path

    from django.conf import settings
    from django.templatetags.static import static

    src = Path(settings.BASE_DIR) / "static" / path
    try:
        mtime = src.stat().st_mtime
    except OSError:
        return static(path)
    cached = _ASSET_VERSIONS.get(path)
    if not cached or cached[0] != mtime:
        cached = (mtime, hashlib.sha1(src.read_bytes()).hexdigest()[:10])
        _ASSET_VERSIONS[path] = cached
    return f"{static(path)}?v={cached[1]}"


@register.filter
def tr(value):
    """Translate a runtime string (stage names, computed statuses) if a translation exists."""
    from django.utils.translation import gettext

    return gettext(str(value)) if value else value


@register.filter
def money(cents, unknown="Unknown"):
    if isinstance(cents, Total):
        return cents.display()
    return format_cents(cents, unknown=unknown)


@register.filter
def money0(cents, unknown="Unknown"):
    if isinstance(cents, Total):
        text = format_cents(cents.known, show_cents=False)
        return text + (" + " + ngettext("%(count)s unknown", "%(count)s unknown", cents.unknown_count) % {"count": cents.unknown_count} if cents.unknown_count else "")
    return format_cents(cents, show_cents=False, unknown=unknown)


@register.filter
def rate(amount, unit):
    if amount is None:
        return gettext("Unknown")
    return f"${amount:,.2f}{RATE_UNIT_SUFFIX.get(unit, '')}"


@register.filter
def can(user, perm):
    return has_perm(user, perm)


def _zh():
    from django.utils.translation import get_language

    return (get_language() or "").startswith("zh")


WEEKDAYS_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


@register.filter
def d(value):
    """Compact date: 'Mar 4, 2026' (EN) or '2026年3月4日' (中)."""
    if not value:
        return "—"
    if isinstance(value, datetime):
        value = timezone.localtime(value)
        if _zh():
            return f"{value.year}年{value.month}月{value.day}日 {value:%H:%M}"
        return f"{value:%b} {value.day}, {value.year} {value:%-I:%M %p}"
    if isinstance(value, date):
        if _zh():
            return f"{value.year}年{value.month}月{value.day}日"
        return f"{value:%b} {value.day}, {value.year}"
    return value


@register.filter
def longdate(value):
    """'Thursday, October 22, 2026' (EN) or '2026年10月22日 星期四' (中)."""
    if not value:
        return ""
    if _zh():
        names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        return f"{value.year}年{value.month}月{value.day}日 {names[value.weekday()]}"
    return f"{value:%A}, {value:%B} {value.day}, {value.year}"


@register.filter
def dshort(value):
    if not value:
        return "—"
    if isinstance(value, datetime):
        value = timezone.localtime(value).date()
    if _zh():
        return f"{value.month}月{value.day}日 {WEEKDAYS_ZH[value.weekday()]}"
    return f"{value:%a} {value:%b} {value.day}"


@register.filter
def relday(value):
    from django.utils.translation import gettext as _, ngettext

    if not value:
        return ""
    if isinstance(value, datetime):
        value = timezone.localtime(value).date()
    delta = (value - timezone.localdate()).days
    if delta == 0:
        return _("today")
    if delta == 1:
        return _("tomorrow")
    if delta == -1:
        return _("yesterday")
    if delta > 0:
        return ngettext("in %(n)d day", "in %(n)d days", delta) % {"n": delta}
    return ngettext("%(n)d day ago", "%(n)d days ago", -delta) % {"n": -delta}


PILL_TONES = {
    # deadlines
    "awaiting_trigger": "amber", "needs_review": "red", "computed": "blue",
    # checklist
    "not_started": "gray", "requested": "blue", "in_progress": "blue", "received": "violet",
    "under_review": "amber", "approved": "green", "waived": "gray", "not_applicable": "gray", "blocked": "red",
    # execution
    "unknown": "gray", "draft": "amber", "partially_signed": "amber", "appears_executed": "blue",
    "confirmed_executed": "green",
    # review
    "pending": "blue", "accepted": "green", "edited": "green", "rejected": "gray",
    # generic
    "open": "blue", "satisfied": "green", "superseded": "gray", "cancelled": "gray", "expired": "red",
    "active": "blue", "closed": "green", "on_hold": "amber", "terminated": "red", "lost": "gray", "archived": "gray",
    "proposed": "amber", "applied": "green", "verified": "green", "unverified": "gray", "marketing": "amber",
    "conflicting": "red", "delivered": "green", "failed": "red", "scheduled": "blue",
    "low": "gray", "medium": "amber", "high": "red", "critical": "red", "normal": "gray",
    "valid": "green", "invalid": "red", "committed": "green", "skipped": "gray", "reverted": "gray",
    "revert_blocked": "red",
}


@register.simple_tag
def pill(key, label=None, tone=None):
    from django.utils.translation import gettext

    tone = tone or PILL_TONES.get(key, "gray")
    if label:
        label = gettext(str(label))
    return format_html('<span class="pill pill-{}">{}</span>', tone, label if label is not None else key)


STATUS_LABELS = {"active": "Active", "closed": "Closed", "terminated": "Terminated"}


@register.simple_tag
def status_pill(deal):
    """The deal's status: Active, Closed or Terminated."""
    key = deal.status_key
    return pill(key, STATUS_LABELS[key], {"active": "blue", "closed": "green", "terminated": "gray"}[key])


@register.filter
def tone(key):
    return PILL_TONES.get(key, "gray")


@register.filter
def get(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def pct(value):
    if value is None:
        return "—"
    return f"{value:g}%"


@register.simple_tag(takes_context=True)
def url_with(context, **changes):
    request = context["request"]
    params = request.GET.copy()
    for k, v in changes.items():
        if v in (None, ""):
            params.pop(k, None)
        else:
            params[k] = v
    return "?" + params.urlencode()


@register.filter
def sf(value):
    if value is None:
        return "—"
    return f"{value:,.0f}" + gettext(" SF")


@register.simple_tag
def icon(name):
    paths = ICONS.get(name, "")
    return mark_safe(
        f'<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
        f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{paths}</svg>'
    )


ICONS = {
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M20.5 14.2A8.5 8.5 0 1 1 9.8 3.5a7 7 0 0 0 10.7 10.7z"/>',
    "monitor": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "logout": '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="M10 17l-5-5 5-5M5 12h11"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "dashboard": '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
    "property_list": '<path d="M3 21h18"/><path d="M5 21V7l7-4 7 4v14"/><path d="M9 21v-6h6v6"/>',
    "deal_list": '<path d="M4 7h16v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/>',
    "deadline_list": '<rect x="3" y="4" width="18" height="17" rx="2"/><path d="M3 9h18M8 2v4M16 2v4"/>',
    "checklist_list": '<path d="M9 6h11M9 12h11M9 18h11"/><path d="m3.5 6 1.5 1.5L7.5 5M3.5 12l1.5 1.5L7.5 11M3.5 18l1.5 1.5L7.5 17"/>',
    "document_list": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/>',
    "contact_list": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M21.5 20a6.5 6.5 0 0 0-4-6"/>',
    "commission_list": '<path d="M12 2v20"/><path d="M17 6H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
    "report_index": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    "settings_index": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "alert": '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    "lock": '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "upload": '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
}


@register.filter
def computation_label(value):
    labels = {"computed": gettext("Computed"), "awaiting_trigger": gettext("Awaiting trigger"),
              "needs_review": gettext("Needs review")}
    return labels.get(value, value)
