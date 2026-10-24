"""Bridges the pure deadline engine to the database: gathers triggers and approved
terms, records revisions, and keeps reminders in step with the current date."""
from django.db import transaction
from django.utils import timezone

from core.audit import audit
from deals.catalog import event_label, term_label
from deals.models import DealEvent, DealTerm

from . import engine
from .models import Deadline, DeadlineRevision


def _term_values(deal, overrides=None):
    values = {t.key: t.value for t in deal.terms.filter(status=DealTerm.STATUS_ACTIVE)}
    if overrides:
        values.update(overrides)
    return values


def _event_triggers(deal):
    return {e.key: e for e in DealEvent.objects.filter(deal=deal)}


def build_rule(deadline, terms):
    holidays = frozenset(deadline.holiday_calendar.dates()) if deadline.holiday_calendar_id else frozenset()
    offset = deadline.offset_days
    offset_source = ""
    if deadline.offset_term_key:
        offset = terms.get(deadline.offset_term_key)
        offset_source = f"contract term: {term_label(deadline.offset_term_key)}"
    fixed = deadline.fixed_date
    fixed_source = ""
    if deadline.rule_type == "fixed_term":
        fixed = terms.get(deadline.fixed_date_term_key)
        fixed_source = f"contract term: {term_label(deadline.fixed_date_term_key)}"
    return engine.Rule(
        rule_type=deadline.rule_type,
        fixed_date=fixed,
        offset_days=offset,
        day_basis=deadline.day_basis,
        include_trigger_day=deadline.include_trigger_day,
        holidays=holidays,
        weekend_rule=deadline.weekend_rule,
        due_time=deadline.due_time,
        time_zone=deadline.time_zone,
        offset_source=offset_source,
        fixed_source=fixed_source,
    )


def build_triggers(deadline, events, computed_overrides=None):
    triggers = []
    for key in deadline.trigger_keys or []:
        if key.startswith("deadline:"):
            other_id = int(key.split(":", 1)[1])
            if computed_overrides and other_id in computed_overrides:
                on = computed_overrides[other_id]
                name = Deadline.objects.filter(pk=other_id).values_list("name", flat=True).first() or key
            else:
                other = Deadline.objects.filter(pk=other_id).first()
                on = other.current_date if other and other.computation == engine.COMPUTED else None
                name = other.name if other else key
            triggers.append(engine.Trigger(key=key, label=f"Deadline '{name}'", on=on, confirmed=on is not None))
            continue
        ev = events.get(key)
        triggers.append(
            engine.Trigger(
                key=key,
                label=event_label(key),
                on=ev.occurred_on if ev else None,
                confirmed=bool(ev and ev.occurred_on and ev.status == DealEvent.STATUS_CONFIRMED),
            )
        )
    return triggers


def evaluate(deadline, terms=None, events=None, computed_overrides=None):
    terms = terms if terms is not None else _term_values(deadline.deal)
    events = events if events is not None else _event_triggers(deadline.deal)
    return engine.compute(build_rule(deadline, terms), build_triggers(deadline, events, computed_overrides))


def _ordered(deadlines):
    """Order so that chained deadlines are computed after the deadlines they reference."""
    by_id = {d.pk: d for d in deadlines}
    out, seen = [], set()

    def visit(d, stack=()):
        if d.pk in seen or d.pk in stack:
            return
        for key in d.trigger_keys or []:
            if key.startswith("deadline:"):
                ref = by_id.get(int(key.split(":", 1)[1]))
                if ref:
                    visit(ref, stack + (d.pk,))
        seen.add(d.pk)
        out.append(d)

    for d in deadlines:
        visit(d)
    return out


@transaction.atomic
def recompute(deadline, actor=None, reason="Recomputed", amendment=None):
    result = evaluate(deadline)
    changed = (
        result.on != deadline.current_date
        or result.status != deadline.computation
        or result.due_at != deadline.due_at
        or result.explanation != deadline.computation_note
    )
    if not changed:
        return result, False
    date_changed = result.on != deadline.current_date or result.status != deadline.computation
    previous_date, previous_comp = deadline.current_date, deadline.computation
    deadline.computation = result.status
    deadline.computation_note = result.explanation
    deadline.current_date = result.on
    deadline.due_at = result.due_at
    if deadline.original_date is None and result.on is not None:
        deadline.original_date = result.on
    if date_changed:
        deadline.revision += 1
        DeadlineRevision.objects.create(
            deadline=deadline,
            revision=deadline.revision,
            previous_date=previous_date,
            new_date=result.on,
            previous_computation=previous_comp,
            new_computation=result.status,
            reason=reason[:255],
            explanation=result.explanation,
            rule_snapshot=deadline.rule_snapshot(),
            amendment=amendment,
            changed_by=actor if getattr(actor, "is_authenticated", False) else None,
        )
        if previous_date is not None or previous_comp == engine.COMPUTED:
            audit(actor, "deadline.date_changed", deadline, {"date": (previous_date, result.on)}, note=reason)
    deadline.save()
    from .reminders import sync_reminders

    sync_reminders(deadline)
    return result, date_changed


def recompute_deal(deal, actor=None, reason="Recomputed", amendment=None):
    results = []
    deadlines = list(deal.deadlines.filter(state="open").select_related("holiday_calendar"))
    for d in _ordered(deadlines):
        d.refresh_from_db()
        results.append((d, *recompute(d, actor=actor, reason=reason, amendment=amendment)))
    from deals.services import sync_deal

    sync_deal(deal, actor)
    return results


def preview_deal(deal, term_overrides):
    """Compute what each open deadline would become if `term_overrides` were approved.
    Nothing is saved."""
    terms = _term_values(deal, term_overrides)
    events = _event_triggers(deal)
    deadlines = _ordered(list(deal.deadlines.filter(state="open").select_related("holiday_calendar")))
    computed = {}
    rows = []
    for d in deadlines:
        result = evaluate(d, terms=terms, events=events, computed_overrides=computed)
        if result.status == engine.COMPUTED:
            computed[d.pk] = result.on
        rows.append(
            {
                "deadline_id": d.pk,
                "name": d.name,
                "current_date": d.current_date.isoformat() if d.current_date else None,
                "current_status": d.computation,
                "new_date": result.on.isoformat() if result.on else None,
                "new_status": result.status,
                "changed": result.on != d.current_date or result.status != d.computation,
                "explanation": result.explanation,
            }
        )
    return rows


def set_state(deadline, state, actor, note=""):
    old = deadline.state
    deadline.state = state
    deadline.state_changed_at = timezone.now()
    deadline.state_changed_by = actor
    deadline.state_note = note
    deadline.save()
    audit(actor, "deadline.state_changed", deadline, {"state": (old, state)}, note=note)
    from .reminders import sync_reminders

    sync_reminders(deadline)


def create_deadline(actor=None, recompute_now=True, **fields):
    d = Deadline.objects.create(created_by=actor, **fields)
    audit(actor, "deadline.created", d, {"rule": d.rule_snapshot()})
    if recompute_now:
        recompute(d, actor=actor, reason="Deadline created")
    return d


# Standard deadlines generated only from *approved* contract terms. No default
# periods: a deadline whose term is not approved is not generated.
STANDARD_SALE_DEADLINES = [
    {
        "template_key": "earnest_money_deposit",
        "name": "Earnest money deposit due",
        "category": "earnest_money",
        "rule_type": "offset",
        "trigger_keys": ["effective_date"],
        "offset_term_key": "earnest_money_deposit_days",
    },
    {
        "template_key": "feasibility_expiration",
        "name": "Feasibility period expires",
        "category": "feasibility",
        "rule_type": "offset",
        "trigger_keys": ["effective_date"],
        "offset_term_key": "feasibility_period_days",
    },
    {
        "template_key": "feasibility_fixed",
        "name": "Feasibility period expires",
        "category": "feasibility",
        "rule_type": "fixed_term",
        "fixed_date_term_key": "feasibility_end_date",
    },
    {
        "template_key": "title_commitment_delivery",
        "name": "Title commitment delivery deadline",
        "category": "title",
        "rule_type": "offset",
        "trigger_keys": ["effective_date"],
        "offset_term_key": "title_commitment_delivery_days",
    },
    {
        "template_key": "survey_delivery",
        "name": "Survey delivery deadline",
        "category": "survey",
        "rule_type": "offset",
        "trigger_keys": ["effective_date"],
        "offset_term_key": "survey_delivery_days",
    },
    {
        "template_key": "title_survey_objection",
        "name": "Title and survey objection deadline",
        "category": "title",
        "rule_type": "later_of",
        "trigger_keys": ["title_commitment_received", "survey_received"],
        "offset_term_key": "title_objection_days",
    },
    {
        "template_key": "financing_contingency",
        "name": "Financing contingency expires",
        "category": "financing",
        "rule_type": "offset",
        "trigger_keys": ["effective_date"],
        "offset_term_key": "financing_contingency_days",
    },
    {
        "template_key": "closing_fixed",
        "name": "Closing date",
        "category": "closing",
        "rule_type": "fixed_term",
        "fixed_date_term_key": "closing_date",
    },
    {
        "template_key": "closing_offset",
        "name": "Closing date",
        "category": "closing",
        "rule_type": "offset",
        "trigger_keys": ["effective_date"],
        "offset_term_key": "closing_days_after_effective",
    },
    {
        "template_key": "outside_closing",
        "name": "Outside closing date",
        "category": "closing",
        "rule_type": "fixed_term",
        "fixed_date_term_key": "outside_closing_date",
    },
]

STANDARD_LEASE_DEADLINES = [
    {
        "template_key": "lease_commencement",
        "name": "Lease commencement date",
        "category": "lease",
        "rule_type": "fixed_term",
        "fixed_date_term_key": "commencement_date",
    },
]


def generate_standard_deadlines(deal, actor=None):
    """Create standard deadlines for which an approved term exists. Returns
    (created, skipped) where skipped explains each deadline not generated."""
    terms = _term_values(deal)
    templates = STANDARD_LEASE_DEADLINES if deal.is_lease else STANDARD_SALE_DEADLINES
    existing = set(deal.deadlines.exclude(state__in=["superseded", "cancelled"]).values_list("template_key", flat=True))
    created, skipped = [], []
    for tpl in templates:
        if tpl["template_key"] == "closing_offset" and "closing_days_after_feasibility" in terms:
            feasibility = deal.deadlines.filter(template_key__in=["feasibility_fixed", "feasibility_expiration"]).exclude(state__in=["cancelled", "superseded"]).first()
            tpl = {**tpl, "offset_term_key": "closing_days_after_feasibility",
                   "trigger_keys": [f"deadline:{feasibility.pk}"] if feasibility else ["feasibility_end"]}
        term_key = tpl.get("offset_term_key") or tpl.get("fixed_date_term_key")
        if tpl["template_key"] in existing:
            skipped.append(f"{tpl['name']}: already exists.")
            continue
        if terms.get(term_key) in (None, ""):
            skipped.append(f"{tpl['name']}: contract term '{term_label(term_key)}' is not approved; not generated.")
            continue
        fields = dict(tpl)
        fields.setdefault("trigger_keys", [])
        fields["deal"] = deal
        fields["time_zone"] = deal.time_zone
        fields["responsible_user"] = deal.responsible_broker
        fields["source_clause"] = "Generated from approved contract term; confirm against the contract."
        created.append(create_deadline(actor=actor, **fields))
    return created, skipped
