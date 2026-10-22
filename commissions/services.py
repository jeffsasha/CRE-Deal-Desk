from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy

from core.audit import audit
from deals.models import log_activity

from .ledger import effective_entries, summarize
from .models import LedgerEntry


@transaction.atomic
def record_entry(agreement, actor, *, entry_type, amount_cents, entry_date, installment=None, allocation=None,
                 reference="", proof_document=None, notes="", import_batch=None):
    if entry_type == "reversal":
        raise ValidationError(gettext_lazy("Use reverse_entry() to record a reversal."))
    if amount_cents is None or amount_cents <= 0:
        raise ValidationError(gettext_lazy("Enter a positive amount; the entry type sets the direction."))
    if entry_type in {"distribution", "direct_payment"} and allocation is None:
        raise ValidationError(gettext_lazy("Distributions and direct payments must name the allocation (recipient) they pay."))
    if allocation is not None and allocation.agreement_id != agreement.pk:
        raise ValidationError(gettext_lazy("Allocation belongs to a different agreement."))
    if installment is not None and installment.agreement_id != agreement.pk:
        raise ValidationError(gettext_lazy("Installment belongs to a different agreement."))
    if entry_type == "distribution" and allocation is not None and allocation.recipient_type == "skw":
        raise ValidationError(gettext_lazy("SKW's own share is not distributed to itself; record receipts instead."))
    if entry_type == "refund":
        received = sum(c for _e, kind, c, _a in effective_entries(agreement.ledger_entries.all()) if kind == "receipt")
        if amount_cents > received:
            raise ValidationError(gettext_lazy("A refund cannot exceed net cash received."))
    entry = LedgerEntry.objects.create(
        agreement=agreement, entry_type=entry_type, amount_cents=amount_cents, entry_date=entry_date,
        installment=installment, allocation=allocation, reference=reference, proof_document=proof_document,
        notes=notes, created_by=actor, import_batch=import_batch,
    )
    audit(actor, f"ledger.{entry_type}", agreement, {"amount": entry.amount_cents / 100, "date": entry_date,
                                                      "recipient": str(allocation) if allocation else None,
                                                      "reference": reference})
    log_activity(agreement.deal, f"Commission ledger: {entry.get_entry_type_display().split(' —')[0]} "
                                 f"${amount_cents / 100:,.2f}" + (f" to {allocation.recipient_name}" if allocation else ""),
                 actor=actor)
    return entry


@transaction.atomic
def reverse_entry(entry, actor, entry_date, reason):
    if not reason.strip():
        raise ValidationError(gettext_lazy("A reason is required to reverse a ledger entry."))
    if entry.entry_type == "reversal":
        raise ValidationError(gettext_lazy("A reversal cannot itself be reversed; record a new entry instead."))
    if entry.is_reversed:
        raise ValidationError(gettext_lazy("This entry has already been reversed."))
    rev = LedgerEntry.objects.create(
        agreement=entry.agreement, entry_type="reversal", amount_cents=entry.amount_cents, entry_date=entry_date,
        reverses=entry, notes=reason, created_by=actor,
    )
    audit(actor, "ledger.reversal", entry.agreement, {"reversed_entry": entry.pk, "amount": entry.amount_cents / 100},
          note=reason)
    return rev


def audit_agreement_change(actor, agreement, action, changes, note=""):
    audit(actor, action, agreement, changes, note=note)


def agreement_summary(agreement):
    return summarize(agreement)
