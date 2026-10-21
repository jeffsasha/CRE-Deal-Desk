from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from core.dashboard import TOPICS
from core.listing import Column, Filter, Listing
from core.models import User
from core.permissions import require, require_edit_on_post, require_perm
from deals.models import Deal

from .forms import ChecklistItemForm, TemplateItemForm
from .models import OPEN_STATUSES, STATUSES, ChecklistItem, ChecklistTemplate, TemplateItem
from .services import update_item


@require_perm("view")
def checklist_list(request):
    today = timezone.localdate()
    qs = ChecklistItem.objects.filter(deal__archived_at__isnull=True).select_related("deal", "owner", "outside_party", "deadline")
    listing = Listing(
        request, qs, area="tasks",
        columns=[
            Column("title", "Item", lambda i: i.title, sort="title"),
            Column("deal", "Deal", lambda i: format_html('<a href="{}?tab=checklist">{}</a>', i.deal.get_absolute_url(), i.deal.name), sort="deal__name"),
            Column("category", "Category", lambda i: i.category, sort="category"),
            Column("status", "Status", lambda i: i.get_status_display(), sort="status"),
            Column("owner", "Owner", lambda i: i.owner or "—"),
            Column("party", "Outside party", lambda i: i.outside_party or i.outside_party_note or "—", default=False),
            Column("due", "Due", lambda i: i.due_date.strftime("%b %-d") if i.due_date else "—", sort="due_date"),
            Column("follow", "Follow-up", lambda i: i.follow_up_on.strftime("%b %-d") if i.follow_up_on else "—", sort="follow_up_on"),
            Column("received", "Received", lambda i: i.received_on.strftime("%b %-d") if i.received_on else "", default=False),
            Column("approved", "Approved", lambda i: i.approved_on.strftime("%b %-d") if i.approved_on else "", default=False),
            Column("issues", "Unresolved", lambda i: i.unresolved_issues[:80], default=False),
        ],
        search_fields=["title", "category", "deal__name", "notes", "unresolved_issues"],
        filters=[
            Filter("open", "Open only", [("1", "Open items only")], lambda qs, v: qs.filter(status__in=OPEN_STATUSES)),
            Filter("status", "Status", STATUSES, lambda qs, v: qs.filter(status=v)),
            Filter("bucket", "When", [("overdue", "Overdue or follow-up past"), ("followup", "Follow-up due today or earlier")],
                   lambda qs, v: qs.filter(status__in=OPEN_STATUSES).filter(
                       Q(due_date__lt=today) | Q(follow_up_on__lt=today) if v == "overdue" else Q(follow_up_on__lte=today))),
            Filter("topic", "Topic", [(k, v[0]) for k, v in TOPICS.items()], lambda qs, v: qs.filter(TOPICS[v][1])),
            Filter("owner", "Owner", [(str(u.pk), u.display_name) for u in User.objects.exclude(role="read_only")],
                   lambda qs, v: qs.filter(owner_id=v)),
        ],
        default_sort="due_date",
        row_url=lambda i: reverse("checklist_item_edit", args=[i.pk]),
        row_class=lambda i: "row-alert" if (i.status == "blocked" or i.is_overdue) else ("row-warn" if i.is_follow_up_due else ""),
    )
    if request.GET.get("export") == "csv":
        return listing.export_csv("tasks")
    return render(request, "core/list_page.html", {"listing": listing, "title": "Tasks & Checklists",
                                                   "subtitle": "Checklist items across all deals. Received ≠ reviewed ≠ approved.",
                                                   "actions": [("Templates", reverse("template_list"))]})


@require_edit_on_post
def item_form(request, pk=None, deal_pk=None):
    item = get_object_or_404(ChecklistItem, pk=pk) if pk else None
    deal = item.deal if item else get_object_or_404(Deal, pk=deal_pk)
    if request.method == "GET" and item is None:
        require(request.user, "edit")
    old_status = item.status if item else "not_started"
    form = ChecklistItemForm(request.POST or None, instance=item, deal=deal)
    back = f"{deal.get_absolute_url()}?tab=checklist"
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.deal = deal
        try:
            update_item(obj, request.user, old_status, note=request.POST.get("change_note", ""))
            form.save_m2m()
            messages.success(request, "Checklist item saved.")
            return redirect(back)
        except ValidationError as exc:
            form.add_error(None, " ".join(exc.messages))
    history = item.history.select_related("changed_by") if item else []
    return render(request, "checklists/item.html", {"form": form, "item": item, "deal": deal, "back_url": back,
                                                    "history": history})


@require_perm("view")
def template_list(request):
    return render(request, "checklists/templates.html", {"templates": ChecklistTemplate.objects.prefetch_related("items")})


@require_edit_on_post
def template_item(request, tpl_pk, pk=None):
    require(request.user, "settings.manage")
    tpl = get_object_or_404(ChecklistTemplate, pk=tpl_pk)
    item = get_object_or_404(TemplateItem, pk=pk, template=tpl) if pk else None
    form = TemplateItemForm(request.POST or None, instance=item)
    if request.method == "POST":
        if request.POST.get("delete") and item:
            item.delete()
            return redirect("template_list")
        if form.is_valid():
            obj = form.save(commit=False)
            obj.template = tpl
            obj.save()
            return redirect("template_list")
    return render(request, "form.html", {"form": form, "title": f"{tpl.name} — template item", "back_url": reverse("template_list"),
                                         "delete_allowed": bool(item)})
