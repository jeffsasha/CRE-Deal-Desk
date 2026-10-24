"""Localized deadline display. Never modifies rules, dates, or audit history."""
from dataclasses import replace

from django.utils.translation import get_language, gettext as _, gettext_noop

from core.templatetags.desk import d
from deals.catalog import term_label
from . import services
from .models import Deadline

STANDARD_NAMES = (
    gettext_noop('Earnest money deposit due'),
    gettext_noop('Feasibility period expires'),
    gettext_noop('Title commitment delivery deadline'),
    gettext_noop('Survey delivery deadline'),
    gettext_noop('Title and survey objection deadline'),
    gettext_noop('Financing contingency expires'),
    gettext_noop('Closing date'),
    gettext_noop('Outside closing date'),
    gettext_noop('Lease commencement date'),
)


def deadline_name(deadline):
    """Only translate untouched names of generated deadlines, preserving custom names."""
    templates = services.STANDARD_SALE_DEADLINES + services.STANDARD_LEASE_DEADLINES
    if any(t['template_key'] == deadline.template_key and t['name'] == deadline.name for t in templates):
        return _(deadline.name)
    return deadline.name


def trigger_rows(deadline, events=None):
    rows = services.build_triggers(deadline, events if events is not None else services._event_triggers(deadline.deal))
    localized = []
    for row in rows:
        if row.key.startswith('deadline:'):
            other = Deadline.objects.filter(pk=row.key.split(':', 1)[1]).first()
            label = _('Deadline: %(name)s') % {'name': deadline_name(other) if other else row.key}
        else:
            label = _(row.label)
        localized.append(replace(row, label=label))
    return localized


def current_note(deadline):
    """Explain today's rule inputs without rewriting the stored English calculation."""
    if not (get_language() or '').startswith('zh'):
        return deadline.computation_note
    terms = services._term_values(deadline.deal)
    events = services._event_triggers(deadline.deal)
    rule = services.build_rule(deadline, terms)
    result = services.evaluate(deadline, terms=terms, events=events)
    triggers = trigger_rows(deadline, events)
    parts = []
    if rule.rule_type in {'fixed', 'fixed_term'}:
        parts.append(_('Fixed date: %(date)s.') % {'date': d(rule.fixed_date)})
        if deadline.fixed_date_term_key:
            parts.append(_('Approved contract term: %(term)s.') % {'term': _(term_label(deadline.fixed_date_term_key))})
        if rule.fixed_date is None:
            parts.append(_('The fixed date is missing or has no approved contract value.'))
    else:
        parts.append(_('%(rule)s: %(days)s %(basis)s; %(counting)s.') % {
            'rule': deadline.get_rule_type_display(),
            'days': rule.offset_days if rule.offset_days is not None else _('Not entered'),
            'basis': deadline.get_day_basis_display(),
            'counting': _('trigger day counted as day 1') if rule.include_trigger_day else _('trigger day excluded'),
        })
        if deadline.offset_term_key:
            parts.append(_('Approved contract term: %(term)s.') % {'term': _(term_label(deadline.offset_term_key))})
        if rule.offset_days is None:
            parts.append(_('The period has no approved value; no default period is applied.'))
        if not triggers:
            parts.append(_('No trigger event is selected.'))
        for trigger in triggers:
            status = _('Not recorded') if trigger.on is None else _('Confirmed') if trigger.confirmed else _('unconfirmed')
            parts.append(_('%(event)s: %(date)s (%(status)s).') % {
                'event': trigger.label, 'date': d(trigger.on), 'status': status,
            })
        if any(t.on is None for t in triggers):
            parts.append(_('Awaiting actual trigger dates; no date can be relied on yet.'))
        if any(t.on is not None and not t.confirmed for t in triggers):
            parts.append(_('Recorded trigger dates are unconfirmed; review them before relying on a date.'))
    parts.append(_('Weekend / holiday adjustment: %(rule)s.') % {'rule': deadline.get_weekend_rule_display()})
    if result.on is not None:
        parts.append(_('Calculated result: %(date)s.') % {'date': d(result.on)})
    else:
        parts.append(_('No date computed: %(status)s.') % {'status': _(dict(Deadline._meta.get_field('computation').choices).get(result.status, result.status))})
    # Report the saved current value separately if inputs have changed since the last recompute.
    if result.on != deadline.current_date or result.status != deadline.computation:
        parts.append(_('Saved current date: %(date)s; recompute to update the saved result.') % {'date': d(deadline.current_date)})
    return ' '.join(parts)


STANDARD_NOTES = (
    gettext_noop("U.S. federal holidays (observed)"),
    gettext_noop("No holidays"),
    gettext_noop("Contract provides for it (entered on the key dates form)"),
    gettext_noop("Generated from approved contract term; confirm against the contract."),
    gettext_noop("Deadline created"),
    gettext_noop("Key dates updated"),
    gettext_noop("Recomputed"),
    gettext_noop("Triggered by updated contract terms"),
)
