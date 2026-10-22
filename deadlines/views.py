import calendar
from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy

from core.audit import audit
from core.listing import Column, Filter, Listing
from core.models import User
from core.permissions import require, require_edit_on_post, require_perm
from deals.models import Deal

from . import services
from .forms import DeadlineForm, StateForm
from .models import CATEGORIES, COMPUTATION, Deadline


def _bucket(qs, bucket):
    today = timezone.localdate()
    computed = qs.filter(computation="computed", state="open")
    return {
        "overdue": computed.filter(current_date__lt=today).exclude(category="feasibility"),
        "today": computed.filter(current_date=today),
        "week": computed.filter(current_date__gte=today, current_date__lte=today + timedelta(days=7)),
        "next14": computed.filter(current_date__gte=today, current_date__lte=today + timedelta(days=14)),
        "next30": computed.filter(current_date__gte=today, current_date__lte=today + timedelta(days=30)),
        "awaiting": qs.filter(state="open", computation="awaiting_trigger"),
        "needs_review": qs.filter(state="open", computation="needs_review"),
        "open": qs.filter(state="open"),
        "closed": qs.exclude(state="open"),
    }.get(bucket, qs)


BUCKETS = [("overdue", "Overdue"), ("today", "Due today"), ("week", "Next 7 days"), ("next14", "Next 14 days"),
           ("next30", "Next 30 days"), ("awaiting", "Awaiting trigger"), ("needs_review", "Needs review"),
           ("open", "All open"), ("closed", "Satisfied / waived / closed")]


@require_perm("view")
def deadline_list(request):
    qs = Deadline.objects.filter(deal__archived_at__isnull=True).exclude(state__in=["superseded"]).select_related(
        "deal", "responsible_user")
    bucket = request.GET.get("bucket", "open")
    listing = Listing(
        request, qs, area="deadlines",
        columns=[
            Column("name", gettext_lazy("Deadline"), lambda d: d.name, sort="name"),
            Column("deal", gettext_lazy("Deal"), lambda d: format_html('<a href="{}">{}</a>', d.deal.get_absolute_url(), d.deal.name), sort="deal__name"),
            Column("date", gettext_lazy("Date"), lambda d: d.current_date.strftime("%a %b %-d, %Y") if d.current_date else d.get_computation_display(), sort="current_date"),
            Column("time", gettext_lazy("Time"), lambda d: f"{d.due_time:%-I:%M %p} {d.time_zone}" if d.due_time else "", default=False),
            Column("category", gettext_lazy("Category"), lambda d: d.get_category_display(), sort="category"),
            Column("kind", gettext_lazy("Kind"), lambda d: "Contractual" if d.is_contractual else "Internal target"),
            Column("rule", gettext_lazy("Rule"), lambda d: d.computation_note[:120], default=False),
            Column("confirmation", gettext_lazy("Rule"), lambda d: d.get_confirmation_display()),
            Column("responsible", gettext_lazy("Responsible"), lambda d: d.responsible_user or d.responsible_party or "—"),
            Column("state", gettext_lazy("Status"), lambda d: d.get_state_display() if d.state != "open" else d.get_computation_display(), sort="state"),
        ],
        search_fields=["name", "deal__name", "deal__internal_id", "source_clause"],
        filters=[
            Filter("bucket", gettext_lazy("Show"), BUCKETS, lambda qs, v: _bucket(qs, v)),
            Filter("category", gettext_lazy("Category"), CATEGORIES, lambda qs, v: qs.filter(category=v)),
            Filter("computation", gettext_lazy("Computation"), COMPUTATION, lambda qs, v: qs.filter(computation=v)),
            Filter("responsible", gettext_lazy("Responsible"), [(str(u.pk), u.display_name) for u in User.objects.exclude(role="read_only")],
                   lambda qs, v: qs.filter(responsible_user_id=v)),
            Filter("kind", gettext_lazy("Kind"), [("contract", "Contractual"), ("internal", "Internal targets")],
                   lambda qs, v: qs.filter(is_contractual=(v == "contract"))),
        ],
        default_sort="current_date",
        row_class=lambda d: "row-alert" if d.is_overdue else ("row-warn" if d.computation != "computed" and d.state == "open" else ("row-muted" if d.state != "open" else "")),
    )
    if "bucket" not in request.GET:
        request.GET = request.GET.copy()
        request.GET["bucket"] = "open"
        listing = Listing(request, qs, listing.columns, area="deadlines", search_fields=listing.search_fields,
                          filters=listing.filters, default_sort="current_date", row_class=listing.row_class)
    if request.GET.get("export") == "csv":
        return listing.export_csv("deadlines")
    return render(request, "deadlines/list.html", {"listing": listing, "bucket": bucket})


@require_perm("view")
def deadline_calendar(request):
    today = timezone.localdate()
    try:
        year = int(request.GET.get("y", today.year))
        month = int(request.GET.get("m", today.month))
        first = date(year, month, 1)
    except ValueError:
        first = today.replace(day=1)
    cal = calendar.Calendar(firstweekday=6)
    weeks = cal.monthdatescalendar(first.year, first.month)
    start, end = weeks[0][0], weeks[-1][-1]
    items = Deadline.objects.filter(current_date__gte=start, current_date__lte=end, deal__archived_at__isnull=True,
                                    computation="computed").exclude(state__in=["superseded", "cancelled"]).select_related("deal")
    by_day = {}
    for d in items:
        by_day.setdefault(d.current_date, []).append(d)
    prev_m = (first - timedelta(days=1)).replace(day=1)
    next_m = (first + timedelta(days=32)).replace(day=1)
    awaiting = Deadline.objects.filter(state="open", computation__in=["awaiting_trigger", "needs_review"],
                                       deal__archived_at__isnull=True).select_related("deal")
    return render(request, "deadlines/calendar.html", {
        "weeks": [[{"date": d, "items": by_day.get(d, []), "other": d.month != first.month} for d in w] for w in weeks],
        "first": first, "prev": prev_m, "next": next_m, "today": today, "awaiting": awaiting,
    })


@require_perm("view")
def deadline_detail(request, pk):
    dl = get_object_or_404(Deadline.objects.select_related("deal", "holiday_calendar", "source_version__document"), pk=pk)
    return render(request, "deadlines/detail.html", {
        "dl": dl, "revisions": dl.revisions.select_related("changed_by", "amendment"),
        "reminders": dl.reminders.select_related("user").order_by("-target_revision", "remind_at"),
        "state_form": StateForm(initial={"state": dl.state}),
        "triggers": services.build_triggers(dl, services._event_triggers(dl.deal)),
        "dependents": [d for d in dl.deal.deadlines.all() if f"deadline:{dl.pk}" in (d.trigger_keys or [])],
        "checklist_items": dl.checklistitem_set.all(),
    })


@require_edit_on_post
def deadline_form(request, pk=None):
    require(request.user, "edit")
    dl = get_object_or_404(Deadline, pk=pk) if pk else None
    deal = dl.deal if dl else get_object_or_404(Deal, pk=request.GET.get("deal") or request.POST.get("deal_id"))
    before = dl.rule_snapshot() if dl else None
    form = DeadlineForm(request.POST or None, instance=dl, deal=deal,
                        initial=None if dl else {"time_zone": deal.time_zone, "responsible_user": deal.responsible_broker})
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if dl is None:
            obj.created_by = request.user
            obj.save()
            audit(request.user, "deadline.created", obj, {"rule": obj.rule_snapshot()})
            services.recompute(obj, actor=request.user, reason="Deadline created")
        else:
            obj.save()
            after = obj.rule_snapshot()
            if after != before:
                audit(request.user, "deadline.rule_changed", obj, {k: (before[k], after[k]) for k in after if before.get(k) != after[k]})
            services.recompute(obj, actor=request.user, reason="Rule edited")
            from .reminders import sync_reminders

            sync_reminders(obj)
        messages.success(request, gettext_lazy("Deadline saved and recomputed."))
        return redirect(obj)
    return render(request, "deadlines/form.html", {"form": form, "dl": dl, "deal": deal})


@require_edit_on_post
def deadline_state(request, pk):
    require(request.user, "edit")
    dl = get_object_or_404(Deadline, pk=pk)
    form = StateForm(request.POST)
    if form.is_valid():
        services.set_state(dl, form.cleaned_data["state"], request.user, form.cleaned_data["note"])
        messages.success(request, f"Marked {dl.get_state_display().lower()}.")
    else:
        messages.error(request, "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect(dl)


@require_edit_on_post
def deadline_recompute(request, pk):
    require(request.user, "edit")
    dl = get_object_or_404(Deadline, pk=pk)
    result, changed = services.recompute(dl, actor=request.user, reason="Manual recompute")
    messages.info(request, "Date changed." if changed else "No change.")
    return redirect(dl)


# --- Calendar export ----------------------------------------------------------

def _ics_escape(text):
    return str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics(deadlines, name):
    now = datetime.now(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//SKW DealDesk//Deadlines//EN", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{_ics_escape(name)}"]
    for d in deadlines:
        if not d.current_date:
            continue
        lines += ["BEGIN:VEVENT", f"UID:deadline-{d.pk}-r{d.revision}@dealdesk", f"DTSTAMP:{now}", f"SEQUENCE:{d.revision}"]
        if d.due_at:
            start = d.due_at.astimezone(dt_timezone.utc)
            lines += [f"DTSTART:{start:%Y%m%dT%H%M%SZ}", f"DTEND:{(start + timedelta(minutes=30)):%Y%m%dT%H%M%SZ}"]
        else:
            lines += [f"DTSTART;VALUE=DATE:{d.current_date:%Y%m%d}", f"DTEND;VALUE=DATE:{(d.current_date + timedelta(days=1)):%Y%m%d}"]
        kind = "" if d.is_contractual else " (internal target)"
        lines += [f"SUMMARY:{_ics_escape(d.name + kind + ' — ' + d.deal.name)}",
                  f"DESCRIPTION:{_ics_escape(d.computation_note)}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _visible_deadlines():
    return Deadline.objects.filter(state="open", computation="computed", deal__archived_at__isnull=True).select_related("deal")


@require_perm("view")
def deadline_ics(request):
    response = HttpResponse(_ics(_visible_deadlines(), "DealDesk deadlines"), content_type="text/calendar")
    response["Content-Disposition"] = 'attachment; filename="dealdesk-deadlines.ics"'
    return response


@require_perm("view")
def deal_ics(request, pk):
    deal = get_object_or_404(Deal, pk=pk)
    response = HttpResponse(_ics(_visible_deadlines().filter(deal=deal), deal.name), content_type="text/calendar")
    response["Content-Disposition"] = f'attachment; filename="{deal.internal_id}.ics"'
    return response


def calendar_feed(request, token):
    """Private, token-authenticated feed for calendar subscriptions (no session)."""
    user = User.objects.filter(calendar_token=token, is_active=True).first()
    if user is None:
        raise Http404
    return HttpResponse(_ics(_visible_deadlines(), f"DealDesk — {user.display_name}"), content_type="text/calendar")
