from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.views.decorators.vary import vary_on_headers
from django.utils.translation import gettext_lazy

from deadlines.models import Reminder
from deadlines.reminders import acknowledge, deliver
from deals.models import Deal, Stage
from properties.models import Property

from . import dashboard as dash
from .audit import audit
from .forms import HolidayForm, ReminderDefaultsForm, StageForm, UserCreateForm, UserEditForm
from .listing import Column, Filter, Listing
from .models import AuditLog, HolidayCalendar, Job, Notification, SavedView, User, WorkspaceSetting
from .permissions import has_perm, require, require_perm
from .templatetags.desk import d as format_day


def safe_next(request, fallback):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return nxt
    return fallback


@require_perm("view")
def hero(request):
    """Opening page: animated skyline, the owner's badge and a few headline numbers."""
    from deals import stats

    today = timezone.localdate()
    year = stats.totals(today.year, with_commission=has_perm(request.user, "commission.view"))
    open_deals = Deal.objects.active().filter(stage__category__in=[Stage.CATEGORY_ACTIVE, Stage.CATEGORY_ON_HOLD]).count()
    cutout = _brand_photo_path(cutout=True)
    return render(request, "core/hero.html", {
        "year": year, "this_year": today.year, "open_deals": open_deals, "has_photo": cutout is not None,
        "photo_is_cutout": bool(cutout and cutout.name.startswith("photo-cutout")),
        "handle": "@" + settings.OWNER_GITHUB.rstrip("/").rsplit("/", 1)[-1]})


def _brand_photo_path(cutout=False):
    """The owner's photo in var/brand; the badge prefers the cut-out made by
    scripts/make_badge_photo.py and falls back to the original."""
    names = ["photo-cutout.png"] if cutout else []
    names += [f"photo.{ext}" for ext in ("webp", "jpg", "jpeg", "png")]
    for name in names:
        path = Path(settings.BRAND_DIR) / name
        if path.exists():
            return path
    return None


@require_perm("view")
def brand_photo(request):
    from django.http import FileResponse, Http404

    path = _brand_photo_path(cutout=request.GET.get("v") == "cutout")
    if path is None:
        raise Http404("No photo in var/brand/")
    response = FileResponse(open(path, "rb"))
    response["Cache-Control"] = "private, max-age=3600"
    return response


@vary_on_headers("X-Workspace-Navigation")
@require_perm("view")
def dashboard(request):
    data = dash.build(request.user, request.GET)
    return render(request, "core/dashboard.html", data)


@require_perm("view")
def search(request):
    q = request.GET.get("q", "").strip()
    results = {}
    if q:
        results["Deals"] = Deal.objects.filter(
            Q(name__icontains=q) | Q(internal_id__icontains=q) | Q(description__icontains=q)
        ).select_related("stage")[:25]
        results["Properties"] = Property.objects.filter(
            Q(name__icontains=q) | Q(street__icontains=q) | Q(city__icontains=q) | Q(parcels__parcel_id__icontains=q)
        ).distinct()[:25]
    return render(request, "core/search.html", {"q": q, "results": results})


@require_perm("view")
def quick_search(request):
    """JSON results for the command palette (same permission rules as search)."""
    from django.http import JsonResponse

    q = request.GET.get("q", "").strip()
    out = []
    if len(q) >= 2:
        for d in Deal.objects.active().filter(Q(name__icontains=q) | Q(internal_id__icontains=q)).select_related("stage")[:6]:
            out.append({"group": str(_("Deals")), "label": d.name, "hint": f"{d.internal_id} · {d.stage.name}", "url": d.get_absolute_url(), "icon": "deal_list"})
        for p in Property.objects.active().filter(Q(name__icontains=q) | Q(street__icontains=q))[:5]:
            out.append({"group": str(_("Properties")), "label": p.name, "hint": p.city, "url": p.get_absolute_url(), "icon": "property_list"})
    return JsonResponse({"results": out})


@require_perm("view")
def notifications(request):
    if request.method == "POST":
        Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
        return redirect("notifications")
    items = request.user.notifications.select_related("reminder")[:200]
    return render(request, "core/notifications.html", {"items": items})


@require_POST
@require_perm("view")
def notification_read(request, pk):
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    n.read_at = n.read_at or timezone.now()
    n.save(update_fields=["read_at"])
    if request.POST.get("acknowledge") and n.reminder_id:
        acknowledge(n.reminder, request.user)
        messages.info(request, gettext_lazy("Reminder acknowledged. The deadline itself is still open until it is marked satisfied."))
    return redirect(safe_next(request, n.url or reverse("notifications")))


@require_POST
@require_perm("view")
def save_view(request):
    area = request.POST.get("area", "")[:40]
    name = request.POST.get("name", "").strip()[:120]
    if area and name:
        SavedView.objects.update_or_create(user=request.user, area=area, name=name,
                                           defaults={"query_string": request.POST.get("query_string", "")})
        messages.success(request, _("Saved view '%(name)s'.") % {"name": name})
    return HttpResponseRedirect(safe_next(request, reverse("dashboard")))


# --- Settings ---------------------------------------------------------------

@vary_on_headers("X-Workspace-Navigation")
@require_perm("view")
def settings_index(request):
    from deadlines.reminders import default_reminder_days

    return render(request, "core/settings.html", {"reminder_days": default_reminder_days()})


@require_perm("users.manage")
def user_list(request):
    return render(request, "core/users.html", {"users": User.objects.all().order_by("username")})


@require_perm("users.manage")
def user_create(request):
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        audit(request.user, "user.created", user, {"role": user.role})
        messages.success(request, _("User %(username)s created.") % {"username": user.username})
        return redirect("user_list")
    return render(request, "form.html", {"form": form, "title": gettext_lazy("New user"), "back_url": reverse("user_list")})


@require_perm("users.manage")
def user_edit(request, pk):
    user = get_object_or_404(User, pk=pk)
    before = {"role": user.role, "is_active": user.is_active, "is_designated_broker": user.is_designated_broker}
    form = UserEditForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        if user == request.user and form.cleaned_data["role"] != "admin":
            form.add_error("role", gettext_lazy("You cannot remove your own administrator role."))
        else:
            user = form.save()
            changes = {k: (v, getattr(user, k)) for k, v in before.items() if getattr(user, k) != v}
            if changes:
                audit(request.user, "user.permissions_changed", user, changes)
            messages.success(request, gettext_lazy("User updated."))
            return redirect("user_list")
    return render(request, "form.html", {"form": form, "title": _("Edit %(username)s") % {"username": user.username}, "back_url": reverse("user_list")})


@require_perm("view")
def stage_list(request):
    return render(request, "core/stages.html", {"stages": Stage.objects.all()})


@require_perm("settings.manage")
def stage_edit(request, pk=None):
    stage = get_object_or_404(Stage, pk=pk) if pk else None
    form = StageForm(request.POST or None, instance=stage)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if not obj.key:
            from django.utils.text import slugify

            obj.key = slugify(obj.name)[:50]
        obj.save()
        audit(request.user, "stage.saved", obj)
        return redirect("stage_list")
    return render(request, "form.html", {"form": form, "title": gettext_lazy("Stage"), "back_url": reverse("stage_list")})


@require_perm("view")
def holiday_list(request):
    calendars = HolidayCalendar.objects.prefetch_related("holidays")
    year = int(request.GET.get("year", timezone.localdate().year))
    return render(request, "core/holidays.html", {"calendars": calendars, "year": year})


@require_perm("settings.manage")
def holiday_add(request, pk):
    cal = get_object_or_404(HolidayCalendar, pk=pk)
    form = HolidayForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        h = form.save(commit=False)
        h.calendar = cal
        h.save()
        audit(request.user, "holiday.added", cal, {"date": h.date, "name": h.name})
        _recompute_calendar_users(cal, request.user)
        return redirect("holiday_list")
    return render(request, "form.html", {"form": form, "title": _("Add holiday to %(calendar)s") % {"calendar": cal}, "back_url": reverse("holiday_list")})


def _recompute_calendar_users(cal, actor):
    from deadlines.models import Deadline
    from deadlines.services import recompute

    for d in Deadline.objects.filter(holiday_calendar=cal, state="open"):
        recompute(d, actor=actor, reason=f"Holiday calendar '{cal}' changed")


@require_perm("settings.manage")
def reminder_settings(request):
    from deadlines.reminders import default_reminder_days

    form = ReminderDefaultsForm(request.POST or None, initial={
        "reminder_days": ", ".join(str(x) for x in default_reminder_days())})
    if request.method == "POST" and form.is_valid():
        WorkspaceSetting.put("reminder_days", form.cleaned_data["reminder_days"])
        audit(request.user, "settings.reminder_days", None, {"reminder_days": form.cleaned_data["reminder_days"]})
        messages.success(request, gettext_lazy("Default reminder lead times saved. They apply to deadlines without their own schedule."))
        return redirect("settings_index")
    return render(request, "form.html", {"form": form, "title": gettext_lazy("Reminder defaults"), "back_url": reverse("settings_index")})


@require_perm("view")
def reminder_log(request):
    qs = Reminder.objects.select_related("deadline__deal", "user", "checklist_item")
    if not has_perm(request.user, "settings.manage"):
        qs = qs.filter(user=request.user)
    if request.method == "POST":
        require(request.user, "edit")
        r = get_object_or_404(qs, pk=request.POST.get("reminder"))
        if r.status == "failed":
            deliver(r)
            messages.info(request, _("Retried: %(status)s.") % {"status": r.get_status_display()})
        return redirect(reverse("reminder_log") + "?" + request.GET.urlencode())
    listing = Listing(
        request, qs, area="reminders",
        columns=[
            Column("item", gettext_lazy("Reminder for"), lambda r: r.deadline or r.checklist_item),
            Column("deal", gettext_lazy("Deal"), lambda r: (r.deadline.deal if r.deadline_id else r.checklist_item.deal).internal_id),
            Column("user", gettext_lazy("Recipient"), lambda r: r.user),
            Column("channel", gettext_lazy("Channel"), lambda r: r.get_channel_display()),
            Column("lead", gettext_lazy("Lead"), lambda r: _("%(days)s d") % {"days": r.lead_days}, sort="lead_days", cls="num"),
            Column("rev", gettext_lazy("Deadline rev."), lambda r: r.target_revision, cls="num"),
            Column("at", gettext_lazy("Scheduled for"), lambda r: format_day(r.remind_at), sort="remind_at"),
            Column("status", gettext_lazy("Status"), lambda r: r.get_status_display(), sort="status"),
            Column("ack", gettext_lazy("Acknowledged"), lambda r: _("Yes") if r.acknowledged_at else ""),
            Column("note", gettext_lazy("Error / reason"), lambda r: r.last_error or r.cancelled_reason),
        ],
        filters=[Filter("status", gettext_lazy("Status"), Reminder.STATUSES, lambda qs, v: qs.filter(status=v))],
        default_sort="-remind_at",
        row_url=lambda r: r.deadline.get_absolute_url() if r.deadline_id else "",
        row_class=lambda r: "row-alert" if r.status == "failed" else ("row-muted" if r.status == "cancelled" else ""),
    )
    failed = qs.filter(status="failed")
    return render(request, "core/reminder_log.html", {"listing": listing, "failed": failed[:50]})


@require_perm("audit.view")
def audit_log(request):
    listing = Listing(
        request, AuditLog.objects.select_related("actor"), area="audit",
        columns=[
            Column("when", gettext_lazy("When"), lambda a: timezone.localtime(a.created_at).strftime("%Y-%m-%d %H:%M:%S"), sort="created_at"),
            Column("actor", gettext_lazy("User"), lambda a: a.actor or _("System")),
            Column("action", gettext_lazy("Action"), lambda a: a.action, sort="action"),
            Column("object", gettext_lazy("Record"), lambda a: a.object_repr),
            Column("type", gettext_lazy("Type"), lambda a: a.model_label, default=False),
            Column("changes", gettext_lazy("Changes"), lambda a: "; ".join(
                f"{k}: {v[0]} → {v[1]}" if isinstance(v, list) and len(v) == 2 else f"{k}: {v}" for k, v in a.changes.items())),
            Column("note", gettext_lazy("Note"), lambda a: a.note),
        ],
        search_fields=["action", "object_repr", "note", "actor__username"],
        filters=[Filter("action", gettext_lazy("Action"), [(x, x) for x in AuditLog.objects.values_list("action", flat=True).distinct().order_by("action")],
                        lambda qs, v: qs.filter(action=v))],
        default_sort="-created_at",
        row_url=lambda a: "",
    )
    if request.GET.get("export") == "csv":
        return listing.export_csv("audit-log")
    return render(request, "core/list_page.html", {"listing": listing, "title": gettext_lazy("Audit log"),
                                                   "subtitle": gettext_lazy("Meaningful changes to contract dates, execution status, deadline rules, prices, closings, commissions and permissions.")})


@require_perm("view")
def archived(request):
    from commissions.models import CommissionAgreement

    data = {
        "deals": Deal.objects.archived(),
        "properties": Property.objects.archived(),
        "agreements": CommissionAgreement.objects.archived() if has_perm(request.user, "commission.view") else [],
    }
    return render(request, "core/archived.html", data)


@require_POST
@require_perm("edit")
def restore(request, kind, pk):
    from commissions.models import CommissionAgreement

    models = {"deal": Deal, "property": Property, "agreement": CommissionAgreement}
    model = models.get(kind)
    if model is None:
        return redirect("archived")
    if kind == "agreement":
        require(request.user, "commission.edit")
    obj = get_object_or_404(model, pk=pk)
    obj.archived_at = None
    obj.archived_by = None
    obj.save()
    audit(request.user, f"{kind}.restored", obj)
    messages.success(request, _("Restored %(object)s.") % {"object": obj})
    return redirect("archived")


@require_perm("view")
def requirements(request):
    text = (Path(settings.BASE_DIR) / "REQUIREMENTS.md").read_text() if (Path(settings.BASE_DIR) / "REQUIREMENTS.md").exists() else ""
    return render(request, "core/requirements.html", {"text": text})


@require_perm("settings.manage")
def jobs(request):
    if request.method == "POST":
        from .jobs import run_job

        job = get_object_or_404(Job, pk=request.POST.get("job"))
        job.attempts = 0
        job.status = Job.STATUS_QUEUED
        job.save()
        run_job(job)
        messages.info(request, _("Job #%(number)s: %(status)s.") % {"number": job.pk, "status": job.get_status_display()})
        return redirect("jobs")
    return render(request, "core/jobs.html", {"jobs": Job.objects.order_by("-created_at")[:200]})
