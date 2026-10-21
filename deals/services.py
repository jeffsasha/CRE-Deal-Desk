import re
from datetime import date, datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.audit import audit
from core.money import MoneyParseError, parse_cents

from .catalog import event_label, term_label, term_type
from .models import Deal, DealEvent, DealTerm, PriceEvent, Stage, log_activity

DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b. %d, %Y"]


def parse_date(text):
    if isinstance(text, date):
        return text
    text = (text or "").strip().replace("  ", " ")
    text = re.sub(r"(\d)(st|nd|rd|th)", r"\1", text)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Not a recognizable date: {text!r}")


WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "fourteen": 14, "fifteen": 15, "twenty": 20, "thirty": 30,
    "forty": 40, "forty-five": 45, "sixty": 60, "ninety": 90, "one hundred twenty": 120,
}


def parse_days(text):
    if isinstance(text, int):
        return text
    text = (text or "").strip().lower()
    m = re.search(r"\((\d+)\)", text) or re.search(r"\b(\d+)\b", text)
    if m:
        return int(m.group(1))
    for word, n in sorted(WORD_NUMBERS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{word}\b", text):
            return n
    raise ValueError(f"Not a number of days: {text!r}")


def parse_term_value(key, text):
    """Convert reviewed text into the typed value for a term. Raises ValueError."""
    kind = term_type(key)
    if kind == "cents":
        try:
            cents = parse_cents(text)
        except MoneyParseError as exc:
            raise ValueError(str(exc)) from exc
        if cents is None:
            raise ValueError("Amount is blank.")
        return cents
    if kind == "date":
        return parse_date(text)
    if kind in {"days", "int"}:
        return parse_days(text)
    value = (text or "").strip()
    if not value:
        raise ValueError("Value is blank.")
    return value


def _assign(term, value):
    kind = term_type(term.key)
    term.value_type = kind
    term.value_text = term.value_date = term.value_int = term.value_cents = None
    term.value_text = ""
    if kind == "cents":
        term.value_cents = value
    elif kind == "date":
        term.value_date = value
    elif kind in {"days", "int"}:
        term.value_int = value
    else:
        term.value_text = value


@transaction.atomic
def set_term(deal, key, value, actor, *, source_version=None, source_field=None, page=None, section="", quote="",
             amendment=None, note="", recompute=True):
    """Approve a term value. Any active value for the key is superseded, not erased."""
    current = deal.terms.filter(key=key, status=DealTerm.STATUS_ACTIVE).first()
    term = DealTerm(
        deal=deal, key=key, source_version=source_version, source_field=source_field, source_page=page,
        source_section=section or "", source_quote=quote or "", amendment=amendment, approved_by=actor, note=note,
        version=(current.version + 1) if current else 1,
    )
    _assign(term, value)
    if current and current.value == term.value and amendment is None:
        return current
    term.save()
    if current:
        current.status = DealTerm.STATUS_SUPERSEDED
        current.superseded_by = term
        current.superseded_at = timezone.now()
        current.save()
    audit(actor, "term.approved", deal, {term_label(key): (current.display_value() if current else None, term.display_value())},
          note=note or (f"Amendment: {amendment}" if amendment else ""))
    log_activity(deal, f"Contract term {'updated' if current else 'approved'}: {term_label(key)} = {term.display_value()}",
                 actor=actor)
    sync_deal(deal, actor)
    if recompute:
        from deadlines.services import recompute_deal

        recompute_deal(deal, actor=actor, reason=f"Term approved: {term_label(key)}", amendment=amendment)
    return term


SYNC_FIELDS = ["effective_date", "contractual_closing_date", "executed_contract_price_cents"]


def sync_deal(deal, actor=None):
    """Keep denormalized deal fields in step with approved terms and confirmed events."""
    terms = deal.active_terms()
    ev = DealEvent.objects.filter(deal=deal, key="effective_date", status=DealEvent.STATUS_CONFIRMED).first()
    new = {
        "effective_date": ev.occurred_on if ev else None,
        "contractual_closing_date": terms["closing_date"].value_date if "closing_date" in terms else None,
        "executed_contract_price_cents": terms["purchase_price"].value_cents if "purchase_price" in terms else None,
    }
    if new["contractual_closing_date"] is None:
        closing = deal.deadlines.filter(category="closing", state="open", computation="computed", is_contractual=True)
        closing = closing.exclude(name__icontains="outside").order_by("current_date").first()
        if closing:
            new["contractual_closing_date"] = closing.current_date
    changes = {f: (getattr(deal, f), v) for f, v in new.items() if getattr(deal, f) != v}
    if changes:
        for f, (_old, v) in changes.items():
            setattr(deal, f, v)
        deal.save(update_fields=list(changes) + ["updated_at"])
        audit(actor, "deal.contract_fields_synced", deal, changes)
    return changes


@transaction.atomic
def record_event(deal, key, occurred_on, actor, *, status=DealEvent.STATUS_CONFIRMED, evidence_document=None,
                 evidence_note="", occurred_time=None):
    """Record an actual event date. Upload dates are never used as substitutes; the
    caller must supply the actual date the event occurred."""
    if occurred_on is None and status == DealEvent.STATUS_CONFIRMED:
        raise ValidationError("A confirmed event requires the actual date it occurred.")
    existing = DealEvent.objects.filter(deal=deal, key=key).first()
    old = (existing.occurred_on, existing.status) if existing else (None, None)
    ev, _ = DealEvent.objects.update_or_create(
        deal=deal, key=key,
        defaults={
            "occurred_on": occurred_on, "occurred_time": occurred_time, "status": status,
            "evidence_document": evidence_document, "evidence_note": evidence_note, "recorded_by": actor,
        },
    )
    audit(actor, "event.recorded", deal, {event_label(key): (f"{old[0]} ({old[1]})" if existing else None, f"{occurred_on} ({status})")})
    log_activity(deal, f"Event recorded: {event_label(key)} — {occurred_on or 'date unknown'} ({ev.get_status_display()})", actor=actor)
    sync_deal(deal, actor)
    from deadlines.services import recompute_deal

    recompute_deal(deal, actor=actor, reason=f"Event recorded: {event_label(key)}")
    return ev


@transaction.atomic
def clear_event(deal, key, actor, reason):
    ev = DealEvent.objects.filter(deal=deal, key=key).first()
    if not ev:
        return
    audit(actor, "event.cleared", deal, {event_label(key): (str(ev.occurred_on), None)}, note=reason)
    ev.delete()
    log_activity(deal, f"Event cleared: {event_label(key)} — {reason}", actor=actor)
    sync_deal(deal, actor)
    from deadlines.services import recompute_deal

    recompute_deal(deal, actor=actor, reason=f"Event cleared: {event_label(key)}")


TERMINAL_REASON_CATEGORIES = {Stage.CATEGORY_TERMINATED, Stage.CATEGORY_LOST}


@transaction.atomic
def change_stage(deal, stage, actor, reason=""):
    if stage.category == Stage.CATEGORY_CLOSED:
        raise ValidationError("Use the Closing tab to close a deal: it records the actual closing date and consideration.")
    if stage.category in TERMINAL_REASON_CATEGORIES and not (reason or deal.termination_reason):
        raise ValidationError(f"A reason is required to mark a deal {stage.name}.")
    old = deal.stage
    if old == stage:
        return deal
    deal.stage = stage
    if reason and stage.category in TERMINAL_REASON_CATEGORIES:
        deal.termination_reason = reason
    deal.save()
    audit(actor, "deal.stage_changed", deal, {"stage": (old.name, stage.name)}, note=reason)
    log_activity(deal, f"Stage changed: {old.name} → {stage.name}" + (f" ({reason})" if reason else ""), actor=actor,
                 kind="decision" if stage.category in TERMINAL_REASON_CATEGORIES else "system")
    return deal


@transaction.atomic
def close_deal(deal, actor, *, actual_closing_date, total_cents, allocations=None, note=""):
    """Close a deal. `total_cents` is deal-level consideration (None = unknown).
    `allocations` maps DealProperty id -> cents and, when given for a multi-property
    deal, must add up to the total so nothing is double-counted or lost."""
    if actual_closing_date is None:
        raise ValidationError("The actual closing date is required to close a deal.")
    if actual_closing_date > timezone.localdate():
        raise ValidationError("The actual closing date cannot be in the future. Proposed closings are not closed transactions.")
    links = {dp.pk: dp for dp in deal.deal_properties.all()}
    allocations = {k: v for k, v in (allocations or {}).items() if v is not None}
    if allocations:
        unknown = set(allocations) - set(links)
        if unknown:
            raise ValidationError("Allocation references a property that is not linked to this deal.")
        if total_cents is None:
            raise ValidationError("Enter the deal-level total before allocating it among properties.")
        if sum(allocations.values()) != total_cents:
            raise ValidationError(
                f"Property allocations total {sum(allocations.values()) / 100:,.2f} but the deal total is "
                f"{total_cents / 100:,.2f}. Allocations must add up to the deal-level consideration."
            )
    old = {"stage": deal.stage.name, "actual_closing_date": deal.actual_closing_date,
           "actual_closing_price_cents": deal.actual_closing_price_cents}
    deal.stage = Stage.objects.get(key="closed")
    deal.actual_closing_date = actual_closing_date
    if deal.is_lease:
        deal.lease_total_consideration_cents = total_cents if total_cents is not None else deal.lease_total_consideration_cents
    else:
        deal.actual_closing_price_cents = total_cents
    deal.save()
    for pk, cents in allocations.items():
        dp = links[pk]
        dp.allocated_price_cents = cents
        dp.save(update_fields=["allocated_price_cents"])
    if total_cents is not None and not deal.is_lease:
        PriceEvent.objects.create(deal=deal, kind="actual_closing", amount_cents=total_cents,
                                  event_date=actual_closing_date, created_by=actor, notes=note)
    DealEvent.objects.update_or_create(deal=deal, key="closing", defaults={
        "occurred_on": actual_closing_date, "status": DealEvent.STATUS_CONFIRMED, "recorded_by": actor,
        "evidence_note": note})
    audit(actor, "deal.closed", deal, {
        "stage": (old["stage"], "Closed"),
        "actual_closing_date": (old["actual_closing_date"], actual_closing_date),
        "total consideration": (old["actual_closing_price_cents"], total_cents),
    }, note=note)
    log_activity(deal, f"Deal closed on {actual_closing_date:%b %-d, %Y}", actor=actor, kind="decision", body=note)
    return deal


def create_deal(actor, *, properties=(), **fields):
    deal = Deal.objects.create(**fields)
    for i, prop in enumerate(properties):
        deal.deal_properties.create(property=prop, is_primary=(i == 0))
    audit(actor, "deal.created", deal, {"stage": deal.stage.name, "type": deal.get_transaction_type_display()})
    log_activity(deal, "Deal created", actor=actor)
    return deal
