"""Simplified per-deal commission view: what SKW expects to receive and what it has
received. Built on the same agreement and immutable ledger as the detailed view, so
totals reconcile with reports; broker splits are simply not shown.

A deal's "simple" agreement is a custom-basis agreement whose only allocation is SKW's
own share as a fixed amount. Deals with detailed agreements (several agreements, or
splits) show the same totals but cannot be edited from the simple form.
"""
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from core.audit import audit
from deals.models import log_activity

from .ledger import summarize
from .models import CommissionAgreement, CommissionAllocation
from .services import record_entry, reverse_entry

SIMPLE_TITLE = "SKW commission"


@dataclass
class SkwCommission:
    expected: int | None = None
    received: int = 0
    receipts: list = field(default_factory=list)
    editable: bool = True
    has_agreement: bool = False

    @property
    def outstanding(self):
        return None if self.expected is None else self.expected - self.received

    @property
    def status(self):
        if self.expected is None:
            return "partial" if self.received else "unknown"
        if self.received == 0:
            return "none"
        if self.received < self.expected:
            return "partial"
        if self.received > self.expected:
            return "over"
        return "full"

    @property
    def status_label(self):
        return {
            "unknown": _("Amount not entered"),
            "none": _("Not received"),
            "partial": _("Partially received"),
            "full": _("Received in full"),
            "over": _("Received more than expected — check"),
        }[self.status]

    @property
    def tone(self):
        return {"unknown": "gray", "none": "amber", "partial": "blue", "full": "green", "over": "red"}[self.status]

    @property
    def pct(self):
        if not self.expected or self.expected <= 0:
            return 0
        return max(0, min(100, round(100 * self.received / self.expected)))


def _skw_side(deal):
    rep = deal.representations.filter(is_skw=True).first()
    if rep:
        return rep.side
    return "tenant" if deal.is_lease else "buyer"


def simple_agreement(deal):
    """The deal's simple agreement, or None. Raises if the deal uses detailed agreements."""
    agreements = list(deal.commission_agreements.active())
    if not agreements:
        return None
    if len(agreements) == 1:
        a = agreements[0]
        allocs = list(a.allocations.all())
        if (a.basis_type == "custom" and len(allocs) == 1 and allocs[0].level == "payer"
                and allocs[0].recipient_type == "skw" and allocs[0].method == "flat"):
            return a
    raise ValidationError(_("This deal has a detailed commission agreement; edit it from the commission record."))


def for_deal(deal):
    agreements = list(deal.commission_agreements.active().prefetch_related("allocations", "ledger_entries"))
    result = SkwCommission(has_agreement=bool(agreements))
    try:
        simple_agreement(deal)
    except ValidationError:
        result.editable = False
    expected, unknown = 0, not agreements
    for a in agreements:
        s = summarize(a)
        value = s.expected_receipt if s.expected_receipt is not None else s.skw_share
        if value is None:
            unknown = True
        else:
            expected += value
        result.received += s.received
        reversed_ids = {e.reverses_id for e in a.ledger_entries.all() if e.entry_type == "reversal"}
        for e in a.ledger_entries.all():
            if e.entry_type in {"receipt", "refund"}:
                result.receipts.append({"entry": e, "reversed": e.pk in reversed_ids,
                                        "signed": e.amount_cents if e.entry_type == "receipt" else -e.amount_cents})
    result.expected = None if unknown else expected
    result.receipts.sort(key=lambda r: (r["entry"].entry_date, r["entry"].pk))
    return result


@transaction.atomic
def set_expected(deal, cents, actor):
    """Set SKW's expected commission for the deal (None = unknown)."""
    if cents is not None and cents < 0:
        raise ValidationError(_("The commission cannot be negative."))
    a = simple_agreement(deal)
    if a is None:
        a = CommissionAgreement.objects.create(
            deal=deal, title=SIMPLE_TITLE, status="active", represented_side=_skw_side(deal),
            basis_type="custom", stated_gross_cents=cents,
        )
        CommissionAllocation.objects.create(agreement=a, level="payer", recipient_type="skw",
                                            recipient_name="SKW Realty LLC", method="flat", amount_cents=cents)
        old = None
    else:
        alloc = a.allocations.get()
        old = alloc.amount_cents
        if old == cents:
            return a
        a.stated_gross_cents = cents
        a.save(update_fields=["stated_gross_cents", "updated_at"])
        alloc.amount_cents = cents
        alloc.save(update_fields=["amount_cents"])
    fmt = lambda v: None if v is None else v / 100  # noqa: E731
    audit(actor, "commission.skw_expected", a, {"SKW commission": (fmt(old), fmt(cents))})
    log_activity(deal, "SKW commission set to " + ("unknown" if cents is None else f"${cents / 100:,.2f}"), actor=actor)
    return a


@transaction.atomic
def record_receipt(deal, cents, entry_date, actor, reference="", notes=""):
    a = simple_agreement(deal)
    if a is None:
        a = set_expected(deal, None, actor)
    return record_entry(a, actor, entry_type="receipt", amount_cents=cents, entry_date=entry_date,
                        reference=reference, notes=notes)


def reverse_receipt(deal, entry, entry_date, reason, actor):
    if entry.agreement.deal_id != deal.pk or entry.entry_type not in {"receipt", "refund"}:
        raise ValidationError(_("This entry does not belong to the deal."))
    return reverse_entry(entry, actor, entry_date, reason)


