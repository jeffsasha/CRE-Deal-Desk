from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from checklists.models import CONDITIONS, ChecklistTemplate
from checklists.services import apply_template, template_for
from core.audit import audit, diff, snapshot
from core.listing import Column, Filter, Listing
from core.money import format_cents
from core.permissions import has_perm, require, require_edit_on_post, require_perm

from . import drafts as draft_templates
from . import services
from .catalog import event_label
from .forms import (
    ActivityForm,
    CloseDealForm,
    DealForm,
    DealLinkForm,
    DepositForm,
    DraftForm,
    EventForm,
    IssueForm,
    IssueStatementForm,
    ManualTermForm,
    PartyForm,
    PriceEventForm,
    RepresentationForm,
    StageChangeForm,
)
from .models import (
    CommunicationDraft,
    Deal,
    DealEvent,
    DealLink,
    DealParty,
    Deposit,
    Issue,
    PriceEvent,
    Representation,
    Stage,
    log_activity,
)

TRACKED = ["name", "transaction_type", "client", "lease_total_consideration_cents", "lease_area_sf", "description"]


CLOSED_LAST = {"closed": 1, "terminated": 2, "lost": 2, "archived": 3}


@require_perm("view")
def deal_list(request):
    """One table: open deals first (furthest along first), then closed, then
    terminated / lost. A deal is its address; there is no separate property list."""
    from commissions import simple

    from . import keydates, listing, stats

    q = request.GET.get("q", "").strip()
    deals = Deal.objects.active().select_related("stage").prefetch_related("representations")
    if q:
        deals = deals.filter(Q(name__icontains=q) | Q(internal_id__icontains=q) | Q(client__name__icontains=q)
                             | Q(deal_properties__property__street__icontains=q)).distinct()
    today = timezone.localdate()
    show_money = has_perm(request.user, "commission.view")
    rows = []
    for d in deals:
        group = CLOSED_LAST.get(d.stage.category, 0)
        tl = keydates.timeline(d, today=today) if group == 0 else None
        if d.is_lease:
            amount = d.lease_total_consideration_cents
        elif d.actual_closing_price_cents is not None:
            amount = d.actual_closing_price_cents
        else:
            amount = d.executed_contract_price_cents
        rows.append({
            "deal": d, "group": group, "next": tl["next"] if tl else None,
            "amount": amount, "asking": listing.asking_display(d) if group == 0 and amount is None else None,
            "sides": [r.get_side_display() for r in d.representations.all() if r.is_skw],
            "skw": simple.for_deal(d) if show_money else None,
        })
    far = today.replace(year=today.year + 100)
    rows.sort(key=lambda r: (
        r["group"],
        r["deal"].stage.category == "on_hold",  # on hold after the deals that are moving
        -r["deal"].stage.order if r["group"] == 0 else 0,
        r["next"]["date"] if r["next"] else far,
        -(r["deal"].actual_closing_date or today).toordinal() if r["group"] else 0,
    ))
    period = request.GET.get("period") or str(today.year)
    year = int(period) if period.isdigit() else None
    totals = stats.totals(year, with_commission=show_money)
    years = sorted(set(totals.years) | {today.year}, reverse=True)
    return render(request, "deals/list.html", {"rows": rows, "q": q, "totals": totals,
                                               "period": period if year else "all", "years": years})


@require_perm("view")
def deposit_list(request):
    qs = Deposit.objects.filter(deal__archived_at__isnull=True).select_related("deal", "holder", "due_deadline")
    listing = Listing(
        request, qs, area="deposits",
        columns=[
            Column("deal", gettext_lazy("Deal"), lambda d: d.deal.name, sort="deal__name"),
            Column("kind", gettext_lazy("Deposit"), lambda d: d.get_kind_display(), sort="kind"),
            Column("amount", gettext_lazy("Amount"), lambda d: format_cents(d.amount_cents), cls="num", sort="amount_cents"),
            Column("holder", gettext_lazy("Held by"), lambda d: d.holder or "—"),
            Column("due", gettext_lazy("Due"), lambda d: (d.due_deadline.current_date.strftime("%b %-d, %Y") if d.due_deadline and d.due_deadline.current_date
                                             else (d.due_deadline.get_computation_display() if d.due_deadline else "No deadline linked"))),
            Column("status", gettext_lazy("Status"), lambda d: _(d.status)),
            Column("refund", gettext_lazy("Refundability"), lambda d: d.get_refundability_display(), default=False),
        ],
        filters=[Filter("awaiting", gettext_lazy("Status"), [("1", "Awaiting receipt confirmation")],
                        lambda qs, v: qs.filter(receipt_confirmed_on__isnull=True, released_on__isnull=True))],
        row_url=lambda d: f"{d.deal.get_absolute_url()}?tab=contract",
        row_class=lambda d: "row-warn" if d.awaiting else "",
    )
    if not request.GET:
        listing = Listing(request, qs.filter(receipt_confirmed_on__isnull=True, released_on__isnull=True,
                                             deal__stage__category="active"),
                          listing.columns, area="deposits", filters=listing.filters, row_url=listing.row_url,
                          row_class=listing.row_class)
    if request.GET.get("export") == "csv":
        return listing.export_csv("deposits")
    return render(request, "core/list_page.html", {"listing": listing, "title": gettext_lazy("Earnest money & deposits"),
                                                   "subtitle": gettext_lazy("Deposits on active deals not yet confirmed received by the holder. Refundability is never inferred from a feasibility date.")})


@require_edit_on_post
def deal_create(request):
    from .forms import CLIENT_LABELS, KIND_CHOICES, NewDealForm, SIDE_CHOICES

    require(request.user, "edit")
    form = NewDealForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        deal = services.create_guided_deal(request.user, form.cleaned_data)
        from . import listing

        if listing.section(deal) == "listing":
            messages.success(request, _("Deal %(id)s created. Enter the listing details.") % {"id": deal.internal_id})
            return redirect("deal_listing", pk=deal.pk)
        messages.success(request, _("Deal %(id)s created. Enter its key dates.") % {"id": deal.internal_id})
        return redirect("deal_key_dates", pk=deal.pk)
    return render(request, "deals/new.html", {
        "form": form, "kinds": KIND_CHOICES, "sides": SIDE_CHOICES, "client_labels": CLIENT_LABELS,
        "kind": form.data.get("kind") or form.initial.get("kind") or "",
        "side": form.data.get("side") or "",
    })


@require_edit_on_post
def deal_edit(request, pk):
    deal = get_object_or_404(Deal, pk=pk)
    require(request.user, "edit")
    before = snapshot(deal, TRACKED)
    form = DealForm(request.POST or None, instance=deal)
    if request.method == "POST" and form.is_valid():
        deal = form.save()
        changes = diff(deal, before, TRACKED)
        if changes:
            audit(request.user, "deal.updated", deal, changes)
            log_activity(deal, "Deal details updated: " + ", ".join(changes), actor=request.user)
        return redirect(deal)
    return render(request, "form.html", {"form": form, "title": f"Edit {deal.name}", "back_url": deal.get_absolute_url()})


TABS = [("overview", gettext_lazy("Overview")), ("parties", gettext_lazy("Parties")), ("checklist", gettext_lazy("Checklist")),
        ("activity", gettext_lazy("Activity")), ("closing", gettext_lazy("Closing"))]


@require_perm("view")
def deal_detail(request, pk):
    deal = get_object_or_404(Deal.objects.select_related("stage", "client", "responsible_broker"), pk=pk)
    tab = request.GET.get("tab", "overview")
    tabs = TABS
    if tab not in dict(tabs):
        tab = "overview"
    today = timezone.localdate()
    deadlines = deal.deadlines.exclude(state__in=["superseded", "cancelled"]).select_related("responsible_user")
    open_items = deal.checklist_items.filter(status__in=["not_started", "requested", "in_progress", "received", "under_review", "blocked"])
    from commissions import simple

    from . import keydates, listing

    key = keydates.key_deadlines(deal)
    ctx = {
        "deal": deal, "tab": tab, "tabs": tabs, "today": today,
        "properties": deal.deal_properties.select_related("property", "space"),
        "deadlines": deadlines,
        "tl": keydates.timeline(deal, key, today),
        "other_deadlines": [d for d in deadlines if d.state == "open" and d.template_key not in keydates.KEY_TEMPLATES],
        "skw": simple.for_deal(deal) if has_perm(request.user, "commission.view") else None,
        # Closed deals keep the listing card only if listing details were recorded.
        "listing": {"show": listing.is_listing_side(deal) and (not deal.is_closed or bool(deal.listing_date)
                                                                or deal.asking_price_cents is not None),
                    "asking": listing.asking_display(deal),
                    "dom": listing.days_on_market(deal, today), "contract": listing.under_contract(deal)},
        "open_item_count": open_items.count(),
        "blocked_items": open_items.filter(status="blocked"),
        "stage_form": StageChangeForm(initial={"stage": deal.stage}),
    }
    if tab == "parties":
        ctx["parties"] = deal.parties.select_related("organization", "contact")
        ctx["representations"] = deal.representations.select_related("brokerage", "broker_user", "agreement_document")
        ctx["show_client_details"] = has_perm(request.user, "client.details")
    elif tab == "checklist":
        items = deal.checklist_items.select_related("owner", "outside_party", "deadline").prefetch_related("evidence")
        groups = {}
        for it in items:
            groups.setdefault(it.category, []).append(it)
        ctx["checklist_groups"] = groups
        ctx["template"] = template_for(deal)
        ctx["templates"] = ChecklistTemplate.objects.filter(enabled=True)
        ctx["conditions"] = CONDITIONS
        ctx["status_filter"] = request.GET.get("status", "")
    elif tab == "activity":
        ctx["activities"] = deal.activities.select_related("created_by", "document")[:300]
        ctx["drafts"] = deal.drafts.all()
        ctx["draft_templates"] = [(k, v[0]) for k, v in draft_templates.TEMPLATES.items()]
    elif tab == "closing":
        ctx["close_form"] = CloseDealForm(deal=deal, initial={
            "actual_closing_date": deal.actual_closing_date,
            "total": deal.actual_closing_price_cents if not deal.is_lease else deal.lease_total_consideration_cents})
        ctx["closing_items"] = deal.checklist_items.filter(category__in=["Closing", "Post-closing"])
        ctx["open_deadlines"] = deadlines.filter(state="open")
    return render(request, "deals/detail.html", ctx)


@require_POST
@require_perm("edit")
def deal_stage(request, pk):
    deal = get_object_or_404(Deal, pk=pk)
    form = StageChangeForm(request.POST)
    stage = Stage.objects.filter(key=request.POST.get("stage")).first() or (
        form.cleaned_data["stage"] if form.is_valid() else None)
    if stage is None:
        return HttpResponseBadRequest("Unknown stage.")
    try:
        services.change_stage(deal, stage, request.user, request.POST.get("reason", "").strip())
    except ValidationError as exc:
        if request.headers.get("X-Requested-With") == "fetch":
            return HttpResponseBadRequest(" ".join(exc.messages))
        messages.error(request, " ".join(exc.messages))
        return redirect(deal)
    if request.headers.get("X-Requested-With") == "fetch":
        return HttpResponse("ok")
    messages.success(request, f"Stage changed to {stage.name}.")
    return redirect(deal)


@require_edit_on_post
def deal_close(request, pk):
    deal = get_object_or_404(Deal, pk=pk)
    require(request.user, "edit")
    form = CloseDealForm(request.POST or None, deal=deal)
    if request.method == "POST" and form.is_valid():
        try:
            services.close_deal(deal, request.user, actual_closing_date=form.cleaned_data["actual_closing_date"],
                                total_cents=form.cleaned_data["total"], allocations=form.allocations(),
                                note=form.cleaned_data["note"])
            messages.success(request, gettext_lazy("Deal closed."))
            return redirect(f"{deal.get_absolute_url()}?tab=closing")
        except ValidationError as exc:
            form.add_error(None, " ".join(exc.messages))
    return render(request, "form.html", {"form": form, "title": f"Close {deal.name}",
                                         "back_url": f"{deal.get_absolute_url()}?tab=closing",
                                         "notice": gettext_lazy("Closing records the actual date and deal-level consideration. A proposed or scheduled closing is not a closed transaction."),
                                         "submit_label": gettext_lazy("Close deal")})


@require_edit_on_post
def deal_archive(request, pk):
    deal = get_object_or_404(Deal, pk=pk)
    require(request.user, "edit")
    if request.method == "POST":
        deal.archived_at = timezone.now()
        deal.archived_by = request.user
        deal.save()
        audit(request.user, "deal.archived", deal, note=request.POST.get("reason", ""))
        messages.success(request, gettext_lazy("Deal archived. It can be restored from Settings → Archived records."))
        return redirect("deal_list")
    return render(request, "confirm.html", {"title": f"Archive {deal}", "back_url": deal.get_absolute_url(),
                                            "message": gettext_lazy("Archived deals are hidden from lists and excluded from reports. Nothing is deleted; you can restore it."),
                                            "reason_required": True, "submit_label": gettext_lazy("Archive deal"), "danger": True})


# --- Sub-record forms --------------------------------------------------------

SUBRECORDS = {
    "party": (DealParty, PartyForm, "parties", "Party", False),
    "representation": (Representation, RepresentationForm, "parties", "Representation", True),
    "price": (PriceEvent, PriceEventForm, "contract", "Price event", True),
    "deposit": (Deposit, DepositForm, "contract", "Deposit", True),
    "link": (DealLink, DealLinkForm, "overview", "Linked deal", True),
    "activity": (None, ActivityForm, "activity", "Activity", True),
}
AUDITED = {"price", "deposit", "representation"}


@require_edit_on_post
def deal_subrecord(request, pk, kind, item=None):
    require(request.user, "edit")
    deal = get_object_or_404(Deal, pk=pk)
    model, form_cls, tab, label, takes_deal = SUBRECORDS[kind]
    from .models import Activity

    model = model or Activity
    fk = "from_deal" if kind == "link" else "deal"
    instance = get_object_or_404(model, pk=item, **{fk: deal}) if item else None
    kwargs = {"deal": deal} if takes_deal else {}
    initial = {"occurred_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M")} if kind == "activity" and not instance else None
    form = form_cls(request.POST or None, instance=instance, initial=initial, **kwargs)
    back = f"{deal.get_absolute_url()}?tab={tab}"
    if request.method == "POST":
        if request.POST.get("delete") and instance:
            if kind in {"price", "activity"}:
                raise PermissionDenied(gettext_lazy("History records cannot be deleted."))
            audit(request.user, f"deal.{kind}_removed", deal, {label: str(instance)})
            log_activity(deal, f"{label} removed: {instance}", actor=request.user)
            instance.delete()
            return redirect(back)
        if form.is_valid():
            obj = form.save(commit=False)
            setattr(obj, fk, deal)
            if kind == "price":
                obj.created_by = request.user
            if kind == "activity":
                obj.created_by = request.user
            obj.save()
            if hasattr(form, "save_m2m"):
                form.save_m2m()
            if kind in AUDITED:
                audit(request.user, f"deal.{kind}_saved", deal, {label: str(obj)})
            if kind != "activity":
                log_activity(deal, f"{label} {'updated' if instance else 'added'}: {obj}", actor=request.user)
            return redirect(back)
    return render(request, "form.html", {"form": form, "title": f"{'Edit' if instance else 'Add'} {label.lower()} — {deal.name}",
                                         "back_url": back, "delete_allowed": bool(instance) and kind not in {"price", "activity"}})


@require_edit_on_post
def deal_event(request, pk):
    require(request.user, "edit")
    deal = get_object_or_404(Deal, pk=pk)
    key = request.GET.get("key") or request.POST.get("key")
    instance = DealEvent.objects.filter(deal=deal, key=key).first() if key else None
    form = EventForm(request.POST or None, instance=instance, deal=deal, initial={"key": key} if key else None)
    back = f"{deal.get_absolute_url()}?tab=contract"
    if request.method == "POST":
        if request.POST.get("clear") and instance:
            services.clear_event(deal, instance.key, request.user, request.POST.get("evidence_note") or "Cleared by user")
            return redirect(back)
        if form.is_valid():
            d = form.cleaned_data
            services.record_event(deal, d["key"], d["occurred_on"], request.user, status=d["status"],
                                  evidence_note=d["evidence_note"],
                                  occurred_time=d["occurred_time"])
            messages.success(request, f"{event_label(d['key'])} recorded. Dependent deadlines were recomputed.")
            return redirect(back)
    return render(request, "form.html", {"form": form, "title": f"Record event — {deal.name}", "back_url": back,
                                         "notice": gettext_lazy("Deadlines that depend on this event are computed from the date you enter here. Never substitute the date a file was uploaded.")})


@require_edit_on_post
def deal_term(request, pk):
    require(request.user, "edit")
    deal = get_object_or_404(Deal, pk=pk)
    form = ManualTermForm(request.POST or None, deal=deal, initial={"key": request.GET.get("key")})
    back = f"{deal.get_absolute_url()}?tab=contract"
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        services.set_term(deal, d["key"], d["typed"], request.user, note=d.get("note") or "Entered manually")
        messages.success(request, gettext_lazy("Contract term approved. Dependent deadlines were recomputed."))
        return redirect(back)
    return render(request, "form.html", {"form": form, "title": f"Enter contract term — {deal.name}", "back_url": back,
                                         "notice": gettext_lazy("Manual entry is always available. Enter only values stated in an executed agreement; superseded values are kept in history."),
                                         "submit_label": gettext_lazy("Approve term")})


@require_POST
@require_perm("edit")
def deal_generate_deadlines(request, pk):
    from deadlines.services import generate_standard_deadlines

    deal = get_object_or_404(Deal, pk=pk)
    created, skipped = generate_standard_deadlines(deal, actor=request.user)
    if created:
        messages.success(request, f"Created {len(created)} deadline(s) from approved terms. Confirm each rule against the contract.")
    for s in skipped:
        messages.info(request, s)
    return redirect(f"{deal.get_absolute_url()}?tab=contract")


@require_POST
@require_perm("edit")
def deal_apply_checklist(request, pk):
    deal = get_object_or_404(Deal, pk=pk)
    tpl = get_object_or_404(ChecklistTemplate, pk=request.POST.get("template"))
    conditions = {key: bool(request.POST.get(f"cond_{key}")) for key, _ in CONDITIONS}
    n = apply_template(deal, tpl, conditions, request.user)
    messages.success(request, f"Added {n} checklist items. Items whose condition was not met are Not Applicable with a reason and can be reopened.")
    return redirect(f"{deal.get_absolute_url()}?tab=checklist")


@require_POST
@require_perm("edit")
def deal_draft(request, pk):
    deal = get_object_or_404(Deal, pk=pk)
    key = request.POST.get("template")
    if key not in draft_templates.TEMPLATES:
        return HttpResponseBadRequest("Unknown template")
    data = draft_templates.TEMPLATES[key][1](deal)
    draft = CommunicationDraft.objects.create(deal=deal, generated_from=key, created_by=request.user, **data)
    return redirect("draft_edit", pk=draft.pk)


@require_edit_on_post
def draft_edit(request, pk):
    require(request.user, "edit")
    draft = get_object_or_404(CommunicationDraft, pk=pk)
    form = DraftForm(request.POST or None, instance=draft)
    back = f"{draft.deal.get_absolute_url()}?tab=activity"
    if request.method == "POST":
        action = request.POST.get("action", "save")
        if form.is_valid():
            draft = form.save()
        if action == "mark_sent":
            draft.status = "marked_sent"
            draft.marked_sent_by = request.user
            draft.marked_sent_at = timezone.now()
            draft.save()
            from .models import Activity

            Activity.objects.create(deal=draft.deal, kind="email", direction="outbound", summary=draft.subject,
                                    body=f"To: {draft.to}\n\n{draft.body}", created_by=request.user,
                                    counterparties=draft.to)
            messages.success(request, gettext_lazy("Recorded as sent by you. DealDesk did not send anything."))
            return redirect(back)
        if action == "discard":
            draft.status = "discarded"
            draft.save()
            return redirect(back)
        messages.success(request, gettext_lazy("Draft saved."))
    return render(request, "deals/draft.html", {"form": form, "draft": draft, "back_url": back})


# --- Issues -------------------------------------------------------------------

@require_edit_on_post
def issue_form(request, pk=None):
    require(request.user, "edit")
    issue = get_object_or_404(Issue, pk=pk) if pk else None
    deal = issue.deal if issue else (Deal.objects.filter(pk=request.GET.get("deal")).first())
    from properties.models import Property

    prop = issue.property if issue else Property.objects.filter(pk=request.GET.get("property")).first()
    before = snapshot(issue, ["status", "resolution_status", "requested_credit_cents", "severity"]) if issue else {}
    form = IssueForm(request.POST or None, instance=issue, deal=deal)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.deal = deal
        obj.property = prop
        obj.save()
        changes = diff(obj, before, ["status", "resolution_status", "requested_credit_cents", "severity"]) if issue else {"created": obj.title}
        if changes:
            audit(request.user, "issue.saved", obj, changes)
        if deal:
            log_activity(deal, f"Issue {'updated' if issue else 'recorded'}: {obj.title}", actor=request.user)
            if obj.requested_credit_cents and (not issue or before.get("requested_credit_cents") != obj.requested_credit_cents):
                PriceEvent.objects.create(deal=deal, kind="requested_credit", amount_cents=obj.requested_credit_cents,
                                          event_date=timezone.localdate(), issue=obj, created_by=request.user,
                                          notes="Requested credit — not an approved price change.")
        return redirect(obj)
    back = issue.get_absolute_url() if issue else (f"{deal.get_absolute_url()}?tab=issues" if deal else (prop.get_absolute_url() if prop else "/"))
    return render(request, "form.html", {"form": form, "title": gettext_lazy("Edit issue") if issue else "Record issue", "back_url": back})


@require_perm("view")
def issue_detail(request, pk):
    issue = get_object_or_404(Issue.objects.select_related("deal", "property", "responsible", "resolution_document"), pk=pk)
    return render(request, "deals/issue.html", {"issue": issue, "statements": issue.statements.select_related("document"),
                                                "documents": issue.document_links.select_related("document"),
                                                "statement_form": IssueStatementForm()})


@require_POST
@require_perm("edit")
def issue_statement(request, pk):
    issue = get_object_or_404(Issue, pk=pk)
    form = IssueStatementForm(request.POST)
    if form.is_valid():
        st = form.save(commit=False)
        st.issue = issue
        st.recorded_by = request.user
        st.save()
        if issue.deal:
            log_activity(issue.deal, f"Statement recorded on issue '{issue.title}' from {st.party}", actor=request.user)
    else:
        messages.error(request, "Statement not saved: " + "; ".join(f"{k}: {v[0]}" for k, v in form.errors.items()))
    return redirect(issue)


@require_perm("view")
def issue_list(request):
    qs = Issue.objects.select_related("deal", "property", "responsible")
    listing = Listing(
        request, qs, area="issues",
        columns=[
            Column("title", gettext_lazy("Issue"), lambda i: i.title, sort="title"),
            Column("deal", gettext_lazy("Deal / property"), lambda i: i.deal or i.property or "—"),
            Column("category", gettext_lazy("Category"), lambda i: i.get_category_display(), sort="category"),
            Column("severity", gettext_lazy("Severity"), lambda i: i.get_severity_display(), sort="severity"),
            Column("status", gettext_lazy("Status"), lambda i: i.get_status_display(), sort="status"),
            Column("resolution", gettext_lazy("Resolution"), lambda i: i.get_resolution_status_display()),
            Column("credit", gettext_lazy("Requested credit"), lambda i: format_cents(i.requested_credit_cents, unknown="—"), cls="num"),
            Column("disclosure", gettext_lazy("Disclosure finding"), lambda i: i.get_disclosure_finding_display(), default=False),
        ],
        search_fields=["title", "description", "deal__name", "property__name"],
        filters=[Filter("status", gettext_lazy("Status"), Issue.STATUSES, lambda qs, v: qs.filter(status=v)),
                 Filter("category", gettext_lazy("Category"), Issue.CATEGORIES, lambda qs, v: qs.filter(category=v))],
        default_sort="-created_at",
    )
    if request.GET.get("export") == "csv":
        return listing.export_csv("issues")
    return render(request, "core/list_page.html", {"listing": listing, "title": gettext_lazy("Issues")})


# --- Key dates and SKW commission (simplified entry) --------------------------

@require_edit_on_post
def deal_key_dates(request, pk):
    from . import keydates
    from .forms import KeyDatesForm

    require(request.user, "edit")
    deal = get_object_or_404(Deal, pk=pk)
    form = KeyDatesForm(request.POST or None, deal=deal, initial=keydates.current_values(deal))
    if request.method == "POST" and form.is_valid():
        keydates.save(deal, form.cleaned_data, request.user)
        messages.success(request, gettext_lazy("Key dates saved. Deadlines were recomputed."))
        return redirect(deal)
    return render(request, "deals/key_dates.html", {"form": form, "deal": deal})


@require_POST
@require_perm("commission.edit")
def deal_commission(request, pk):
    from commissions import simple

    from .forms import SkwCommissionForm

    deal = get_object_or_404(Deal, pk=pk)
    form = SkwCommissionForm(request.POST)
    if form.is_valid():
        try:
            simple.set_expected(deal, form.cleaned_data["expected"], request.user)
            messages.success(request, gettext_lazy("SKW commission saved."))
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
    else:
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
    return redirect(deal)


@require_POST
@require_perm("commission.edit")
def deal_receipt(request, pk):
    from commissions import simple

    from .forms import ReceiptForm

    deal = get_object_or_404(Deal, pk=pk)
    form = ReceiptForm(request.POST)
    if form.is_valid():
        d = form.cleaned_data
        try:
            simple.record_receipt(deal, d["amount"], d["entry_date"], request.user, reference=d["reference"])
            messages.success(request, gettext_lazy("Payment recorded."))
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
    else:
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
    return redirect(deal)


@require_POST
@require_perm("commission.edit")
def deal_receipt_reverse(request, pk, entry):
    from commissions import simple
    from commissions.models import LedgerEntry

    deal = get_object_or_404(Deal, pk=pk)
    e = get_object_or_404(LedgerEntry, pk=entry)
    try:
        simple.reverse_receipt(deal, e, timezone.localdate(), request.POST.get("reason") or "Entered in error", request.user)
        messages.success(request, gettext_lazy("Payment reversed. The original entry is kept in the ledger."))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect(deal)


@require_edit_on_post
def deal_listing(request, pk):
    from . import listing
    from .forms import ListingForm

    require(request.user, "edit")
    deal = get_object_or_404(Deal, pk=pk)
    initial = {"listing_date": deal.listing_date, "listing_expires_on": deal.listing_expires_on,
               "asking_price": deal.asking_price_cents, "asking_price_unit": deal.asking_price_unit or "usd_total"}
    form = ListingForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        listing.save(deal, form.cleaned_data, request.user)
        messages.success(request, gettext_lazy("Listing details saved."))
        return redirect(deal)
    return render(request, "form.html", {"form": form, "title": _("Listing details"), "subtitle": deal.name,
                                         "back_url": deal.get_absolute_url(), "max_width": "640px"})
