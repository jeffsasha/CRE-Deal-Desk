"""Commission arithmetic and derived status. Integer cents throughout; unknown values
stay unknown (None) and are reported as such, never as zero."""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import ValidationError

from core.money import Total, percent_of


def _validated_tiers(tiers):
    """Validate tier shapes and return [(upper_cents|None, rate)] sorted by
    threshold (open-ended tiers last), preserving the original order among
    equal thresholds. Raises ValidationError for any malformed tier."""
    parsed = []
    for tier in tiers:
        if not isinstance(tier, dict):
            raise ValidationError(f"Invalid commission tier: {tier!r}")
        upper = tier.get("up_to_cents")
        if upper in (None, ""):
            upper = None
        else:
            try:
                upper = int(upper)
            except (TypeError, ValueError):
                raise ValidationError(f"Invalid commission tier threshold: {tier!r}") from None
        if "rate_percent" not in tier:
            raise ValidationError(f"Invalid commission tier (missing rate_percent): {tier!r}")
        try:
            rate = Decimal(str(tier["rate_percent"]))
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError(f"Invalid commission tier rate: {tier!r}") from None
        if not rate.is_finite():
            raise ValidationError(f"Invalid commission tier rate: {tier!r}")
        parsed.append((upper, rate))
    parsed.sort(key=lambda p: float("inf") if p[0] is None else p[0])
    return parsed


def tiered_amount(basis_cents, tiers):
    """Marginal tiers: [{'up_to_cents': int|None, 'rate_percent': '6'}, ...] sorted by
    threshold. Each rate applies to the slice of the basis inside its band."""
    if basis_cents is None or not tiers:
        return None
    total = Decimal(0)
    lower = 0
    for upper, rate in _validated_tiers(tiers):
        top = basis_cents if upper is None else min(basis_cents, upper)
        if top > lower:
            total += Decimal(top - lower) * rate / Decimal(100)
        lower = upper if upper is not None else lower
        if upper is None or basis_cents <= upper:
            break
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def base_gross(agreement):
    t = agreement.basis_type
    if t == "percentage":
        return percent_of(agreement.basis_amount_cents, agreement.rate_percent)
    if t == "flat":
        return agreement.flat_amount_cents
    if t == "tiered":
        return tiered_amount(agreement.basis_amount_cents, agreement.tiers)
    if t == "custom":
        return agreement.stated_gross_cents
    return None


def gross_commission(agreement):
    base = base_gross(agreement)
    if base is None:
        return None
    return base + sum(a.amount_cents for a in agreement.adjustments.all())


def allocation_amount(alloc, gross, skw_share):
    if alloc.method == "percent_of_gross":
        return percent_of(gross, alloc.percent)
    if alloc.method == "percent_of_skw":
        return percent_of(skw_share, alloc.percent)
    if alloc.method == "flat":
        return alloc.amount_cents
    return None


def effective_entries(entries):
    """Yield (entry, effective_type, signed_cents). A reversal carries the type of the
    entry it reverses with the opposite sign; a refund is a negative receipt."""
    for e in entries:
        if e.entry_type == "reversal":
            original = e.reverses
            if original is None:
                continue
            kind = "receipt" if original.entry_type == "refund" else original.entry_type
            sign = 1 if original.entry_type == "refund" else -1
            yield e, kind, sign * e.amount_cents, original.allocation_id
        elif e.entry_type == "refund":
            yield e, "receipt", -e.amount_cents, e.allocation_id
        else:
            yield e, e.entry_type, e.amount_cents, e.allocation_id


@dataclass
class AllocationLine:
    allocation: object
    allocated: int | None
    paid: int = 0

    @property
    def unpaid(self):
        return None if self.allocated is None else self.allocated - self.paid


@dataclass
class Summary:
    gross: int | None
    skw_share: int | None
    expected_receipt: int | None
    earned: Total
    received: int
    outstanding: int | None
    payer_lines: list = field(default_factory=list)
    internal_lines: list = field(default_factory=list)
    designated_broker_allocated: int | None = None
    designated_broker_paid: int = 0
    status: str = ""
    distribution_status: str = ""
    warnings: list = field(default_factory=list)

    @property
    def designated_broker_unpaid(self):
        if self.designated_broker_allocated is None:
            return None
        return self.designated_broker_allocated - self.designated_broker_paid


def summarize(agreement, today=None):
    from django.utils import timezone

    today = today or timezone.localdate()
    gross = gross_commission(agreement)
    allocations = list(agreement.allocations.select_related("recipient_user"))
    payer_allocs = [a for a in allocations if a.level == "payer"]
    internal_allocs = [a for a in allocations if a.level == "internal"]

    skw_allocs = [a for a in payer_allocs if a.recipient_type == "skw"]
    skw_share = None
    if skw_allocs:
        amounts = [allocation_amount(a, gross, None) for a in skw_allocs]
        skw_share = None if any(x is None for x in amounts) else sum(amounts)

    payer_lines = [AllocationLine(a, allocation_amount(a, gross, skw_share)) for a in payer_allocs]
    internal_lines = [AllocationLine(a, allocation_amount(a, gross, skw_share)) for a in internal_allocs]

    expected_receipt = None
    through = [ln for ln in payer_lines if ln.allocation.paid_through_skw]
    if through and all(ln.allocated is not None for ln in through):
        expected_receipt = sum(ln.allocated for ln in through)

    earned = Total()
    for inst in agreement.installments.all():
        if inst.earned_status == "earned":
            earned.add(inst.amount_cents, inst)

    received = 0
    paid_by_alloc = {}
    entries = agreement.ledger_entries.select_related("reverses").all()
    for _entry, kind, cents, alloc_id in effective_entries(entries):
        if kind == "receipt":
            received += cents
        elif kind in {"distribution", "direct_payment"} and alloc_id:
            paid_by_alloc[alloc_id] = paid_by_alloc.get(alloc_id, 0) + cents
    for ln in payer_lines + internal_lines:
        ln.paid = paid_by_alloc.get(ln.allocation.pk, 0)

    warnings = []
    if gross is None:
        warnings.append("Gross commission is unknown (calculation basis incomplete).")
    if not payer_allocs:
        warnings.append("No division of the gross commission is recorded; SKW's share is unknown.")
    if gross is not None and payer_allocs and all(ln.allocated is not None for ln in payer_lines):
        allocated_total = sum(ln.allocated for ln in payer_lines)
        if allocated_total != gross:
            warnings.append(
                f"Payer-level allocations total {allocated_total / 100:,.2f}, which differs from gross {gross / 100:,.2f}."
            )
    if skw_share is not None and internal_lines and all(ln.allocated is not None for ln in internal_lines):
        internal_total = sum(ln.allocated for ln in internal_lines)
        if internal_total > skw_share:
            warnings.append("Internal distributions exceed SKW's share.")

    outstanding = None
    if earned.is_complete:
        outstanding = earned.known - received

    # Designated broker (separately from SKW's gross receipts).
    db_lines = [ln for ln in internal_lines + payer_lines if ln.allocation.is_designated_broker]
    db_allocated = None
    if db_lines and all(ln.allocated is not None for ln in db_lines):
        db_allocated = sum(ln.allocated for ln in db_lines)
    db_paid = sum(ln.paid for ln in db_lines)

    status = _status(agreement, gross, expected_receipt, earned, received, today)
    dist_lines = [ln for ln in payer_lines + internal_lines if ln.allocation.recipient_type != "skw"]
    distribution_status = _distribution_status(dist_lines, received)

    return Summary(
        gross=gross,
        skw_share=skw_share,
        expected_receipt=expected_receipt,
        earned=earned,
        received=received,
        outstanding=outstanding,
        payer_lines=payer_lines,
        internal_lines=internal_lines,
        designated_broker_allocated=db_allocated,
        designated_broker_paid=db_paid,
        status=status,
        distribution_status=distribution_status,
        warnings=warnings,
    )


def _status(agreement, gross, expected, earned, received, today):
    if agreement.status == "void":
        return "Void"
    if agreement.status == "draft":
        return "Agreement not executed"
    if agreement.status == "disputed":
        return "Disputed"
    if gross is None and expected is None and earned.count == 0:
        return "Commission unknown"
    if earned.count == 0:
        return "Received before earned — reconcile" if received > 0 else "Not yet earned"
    if not earned.is_complete:
        return "Earned — amount unknown"
    if received == 0:
        overdue = any(
            inst.due_date and inst.due_date < today for inst in earned.sources if inst.earned_status == "earned"
        )
        return "Earned — past due" if overdue else "Earned — awaiting payment"
    if received < earned.known:
        return "Partially received"
    if received > earned.known:
        return "Received more than earned — reconcile"
    if expected is not None and received < expected:
        return "Received to date — later installments pending"
    return "Received in full"


def _distribution_status(lines, received):
    if not lines:
        return "No distributions recorded"
    unknown = [ln for ln in lines if ln.allocated is None]
    if unknown:
        return "Distribution amounts unknown"
    unpaid = [ln for ln in lines if ln.unpaid and ln.unpaid > 0]
    if not unpaid:
        return "Fully distributed"
    if received == 0:
        return "Awaiting receipt"
    return "Distributions outstanding"
