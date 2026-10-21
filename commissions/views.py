from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.audit import audit, diff, snapshot
from core.listing import Column, Filter, Listing
from core.money import format_cents
from core.permissions import require, require_perm

from . import services
from .forms import AdjustmentForm, AgreementForm, AllocationForm, EntryForm, InstallmentForm, ReverseForm
from .ledger import summarize
from .models import CommissionAdjustment, CommissionAgreement, CommissionAllocation, CommissionInstallment, LedgerEntry

AGREEMENT_TRACKED = ["status", "basis_type", "basis_amount_cents", "rate_percent", "flat_amount_cents", "stated_gross_cents",
                     "represented_side", "payer_name", "legal_payee"]


@require_perm("commission.view")
def commission_list(request):
    qs = CommissionAgreement.objects.active().select_related("deal__stage", "payer")
    cache = {}

    def s(a):
        if a.pk not in cache:
            cache[a.pk] = summarize(a)
        return cache[a.pk]

    listing = Listing(
        request, qs, area="commissions",
        columns=[
            Column("title", "Agreement", lambda a: a.title, sort="title"),
            Column("deal", "Deal", lambda a: a.deal.name, sort="deal__name"),
            Column("side", "Side", lambda a: a.get_represented_side_display(), sort="represented_side"),
            Column("gross", "Gross", lambda a: format_cents(s(a).gross), cls="num"),
            Column("skw", "SKW share", lambda a: format_cents(s(a).skw_share), cls="num"),
            Column("earned", "Earned", lambda a: s(a).earned.display() if s(a).earned.count else "—", cls="num"),
            Column("received", "Received", lambda a: format_cents(s(a).received), cls="num"),
            Column("outstanding", "Outstanding", lambda a: format_cents(s(a).outstanding), cls="num"),
            Column("db", "Designated broker paid", lambda a: format_cents(s(a).designated_broker_paid), cls="num", default=False),
            Column("status", "Status", lambda a: s(a).status),
            Column("dist", "Distributions", lambda a: s(a).distribution_status, default=False),
        ],
        search_fields=["title", "deal__name", "payer_name", "payer__name"],
        filters=[Filter("status", "Agreement", CommissionAgreement.STATUSES, lambda qs, v: qs.filter(status=v))],
        default_sort="-created_at",
    )
    if request.GET.get("export") == "csv":
        return listing.export_csv("commissions")
    return render(request, "commissions/list.html", {"listing": listing})


@require_perm("commission.view")
def ledger_list(request):
    qs = LedgerEntry.objects.select_related("agreement__deal", "allocation", "installment", "reverses", "created_by")
    listing = Listing(
        request, qs, area="ledger",
        columns=[
            Column("date", "Date", lambda e: e.entry_date.strftime("%Y-%m-%d"), sort="entry_date"),
            Column("type", "Type", lambda e: e.get_entry_type_display().split(" —")[0], sort="entry_type"),
            Column("amount", "Amount", lambda e: format_cents(e.amount_cents), cls="num", sort="amount_cents"),
            Column("deal", "Deal", lambda e: e.agreement.deal.name),
            Column("recipient", "Recipient", lambda e: e.allocation.recipient_name if e.allocation else ""),
            Column("reference", "Reference", lambda e: e.reference),
            Column("rev", "Reversal", lambda e: f"Reverses #{e.reverses_id}" if e.reverses_id else ("Reversed" if e.is_reversed else "")),
            Column("by", "Entered by", lambda e: e.created_by or "Import", default=False),
            Column("id", "#", lambda e: e.pk, default=False),
        ],
        search_fields=["reference", "notes", "agreement__deal__name", "allocation__recipient_name"],
        filters=[Filter("type", "Type", LedgerEntry.TYPES, lambda qs, v: qs.filter(entry_type=v))],
        default_sort="-entry_date",
        row_url=lambda e: e.agreement.get_absolute_url(),
    )
    if request.GET.get("export") == "csv":
        return listing.export_csv("commission-ledger")
    return render(request, "core/list_page.html", {"listing": listing, "title": "Commission ledger",
                                                   "subtitle": "Every cash movement. Entries are never edited; corrections are reversals.",
                                                   "actions": [("Agreements", reverse("commission_list"))]})


def agreement_form(request, pk=None):
    require(request.user, "commission.edit")
    obj = get_object_or_404(CommissionAgreement, pk=pk) if pk else None
    before = snapshot(obj, AGREEMENT_TRACKED) if obj else {}
    initial = {"deal": request.GET.get("deal")} if not obj else None
    form = AgreementForm(request.POST or None, instance=obj, initial=initial)
    if request.method == "POST" and form.is_valid():
        a = form.save()
        audit(request.user, "commission.agreement_saved", a, diff(a, before, AGREEMENT_TRACKED) if obj else {"created": a.title})
        if not obj:
            messages.info(request, "Agreement saved. Next, record the division of the gross commission (including SKW's share) and the installments.")
        return redirect(a)
    return render(request, "form.html", {"form": form, "title": "Edit commission agreement" if obj else "New commission agreement",
                                         "back_url": obj.get_absolute_url() if obj else reverse("commission_list")})


@require_perm("commission.view")
def agreement_detail(request, pk):
    a = get_object_or_404(CommissionAgreement.objects.select_related("deal", "document", "payer"), pk=pk)
    s = summarize(a)
    entries = a.ledger_entries.select_related("allocation", "installment", "reverses", "created_by", "proof_document")
    return render(request, "commissions/detail.html", {
        "a": a, "s": s, "entries": entries, "installments": a.installments.all(), "adjustments": a.adjustments.all(),
        "entry_form": EntryForm(agreement=a, initial={"entry_date": timezone.localdate()}),
    })


SUBFORMS = {
    "allocation": (CommissionAllocation, AllocationForm, "Allocation"),
    "installment": (CommissionInstallment, InstallmentForm, "Installment"),
    "adjustment": (CommissionAdjustment, AdjustmentForm, "Adjustment"),
}


def agreement_sub(request, pk, kind, item=None):
    require(request.user, "commission.edit")
    a = get_object_or_404(CommissionAgreement, pk=pk)
    model, form_cls, label = SUBFORMS[kind]
    instance = get_object_or_404(model, pk=item, agreement=a) if item else None
    form = form_cls(request.POST or None, instance=instance)
    if request.method == "POST":
        if request.POST.get("delete") and instance:
            if kind != "adjustment" and instance.ledgerentry_set.exists():
                messages.error(request, f"This {label.lower()} has ledger entries and cannot be removed.")
                return redirect(a)
            audit(request.user, f"commission.{kind}_removed", a, {label: str(instance)})
            instance.delete()
            return redirect(a)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.agreement = a
            obj.save()
            audit(request.user, f"commission.{kind}_saved", a, {label: str(obj)})
            return redirect(a)
    return render(request, "form.html", {"form": form, "title": f"{label} — {a.title}", "back_url": a.get_absolute_url(),
                                         "delete_allowed": bool(instance)})


def entry_create(request, pk):
    require(request.user, "commission.edit")
    a = get_object_or_404(CommissionAgreement, pk=pk)
    form = EntryForm(request.POST or None, agreement=a)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            services.record_entry(a, request.user, entry_type=d["entry_type"], amount_cents=d["amount"],
                                  entry_date=d["entry_date"], installment=d["installment"], allocation=d["allocation"],
                                  reference=d["reference"], proof_document=d["proof_document"], notes=d["notes"])
            messages.success(request, "Ledger entry recorded.")
            return redirect(a)
        except ValidationError as exc:
            form.add_error(None, " ".join(exc.messages))
    return render(request, "form.html", {"form": form, "title": f"Record ledger entry — {a.title}", "back_url": a.get_absolute_url()})


def entry_reverse(request, pk):
    require(request.user, "commission.edit")
    entry = get_object_or_404(LedgerEntry, pk=pk)
    form = ReverseForm(request.POST or None, initial={"entry_date": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        try:
            services.reverse_entry(entry, request.user, form.cleaned_data["entry_date"], form.cleaned_data["reason"])
            messages.success(request, "Reversal recorded. The original entry is unchanged.")
            return redirect(entry.agreement)
        except ValidationError as exc:
            form.add_error(None, " ".join(exc.messages))
    return render(request, "form.html", {"form": form, "title": f"Reverse entry #{entry.pk}", "back_url": entry.agreement.get_absolute_url(),
                                         "notice": f"Reversing: {entry}. The original stays in the ledger; a reversal entry offsets it."})


def agreement_archive(request, pk):
    require(request.user, "commission.edit")
    a = get_object_or_404(CommissionAgreement, pk=pk)
    if request.method == "POST":
        a.archived_at = timezone.now()
        a.archived_by = request.user
        a.save()
        audit(request.user, "commission.agreement_archived", a, note=request.POST.get("reason", ""))
        return redirect("commission_list")
    return render(request, "confirm.html", {"title": f"Archive {a}", "back_url": a.get_absolute_url(), "reason_required": True,
                                            "message": "Archived agreements are excluded from reports but kept with their ledger; they can be restored."})
