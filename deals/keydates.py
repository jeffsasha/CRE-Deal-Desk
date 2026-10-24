"""Key dates entered by hand from the executed contract.

The user enters the Effective Date and the contract periods; deadlines are computed by
the rule engine (deadlines/engine.py):
  sale / business: Feasibility Period ends = N days after the Effective Date, or a
                   fixed date written in the contract;
                   Closing Date = N days after the Feasibility Period ends, or a fixed
                   date. With the N-days form an extension of the Feasibility Period
                   moves the Closing Date too.
  lease:           Commencement Date (fixed date).
Days are calendar days and the starting day itself is not counted. A deadline that
falls on a weekend or holiday is moved to the next business day only when the user
says the contract provides for it. Superseded values stay in history.

"N days after the Feasibility Period ends" is kept as its own term and uses the
Feasibility deadline as its trigger, including any contractual weekend adjustment.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_noop

from core.models import HolidayCalendar
from deadlines.services import generate_standard_deadlines, recompute_deal, set_state

from . import services
from .models import DealEvent, DealTerm, log_activity

# Milestones shown on the dashboard timeline, per deal kind: (label, deadline template keys)
SALE_MILESTONES = [(gettext_noop("Feasibility Period ends"), ["feasibility_expiration", "feasibility_fixed"]),
                   (gettext_noop("Closing Date"), ["closing_fixed", "closing_offset"])]
LEASE_MILESTONES = [(gettext_noop("Commencement Date"), ["lease_commencement"])]
KEY_TEMPLATES = {"feasibility_expiration", "feasibility_fixed", "closing_fixed", "closing_offset", "lease_commencement"}
FEASIBILITY_TERMS = {"days": "feasibility_period_days", "date": "feasibility_end_date"}
CLOSING_AFTER = "closing_days_after_feasibility"


def milestone_spec(deal):
    return LEASE_MILESTONES if deal.is_lease else SALE_MILESTONES


def _term(terms, key, attr):
    return getattr(terms[key], attr) if key in terms else None


def current_values(deal):
    terms = deal.active_terms()
    ev = DealEvent.objects.filter(deal=deal, key="effective_date").first()
    key_deadlines = deal.deadlines.filter(template_key__in=KEY_TEMPLATES).exclude(state__in=["superseded", "cancelled"])
    eff = ev.occurred_on if ev else None
    feas_days = _term(terms, "feasibility_period_days", "value_int")
    values = {
        "effective_date": eff,
        "feasibility_mode": "date" if "feasibility_end_date" in terms else "days",
        "feasibility_days": feas_days,
        "feasibility_date": _term(terms, "feasibility_end_date", "value_date"),
        "closing_mode": "date" if "closing_date" in terms else "days",
        "closing_date": _term(terms, "closing_date", "value_date"),
        "closing_days": _term(terms, CLOSING_AFTER, "value_int"),
        "commencement_date": _term(terms, "commencement_date", "value_date"),
        "next_business_day": any(d.weekend_rule == "next_business_day" for d in key_deadlines),
    }
    # Older records: Closing written as days after the Effective Date. Show it as days
    # after the Feasibility Period, which lands on the same date.
    legacy = _term(terms, "closing_days_after_effective", "value_int")
    if values["closing_mode"] == "days" and values["closing_days"] is None and legacy is not None:
        feas_end = _feasibility_offset(values)
        feasibility = next((d for d in key_deadlines if d.template_key in ("feasibility_fixed", "feasibility_expiration")), None)
        closing = next((d for d in key_deadlines if d.template_key == "closing_offset"), None)
        if eff and feasibility and feasibility.current_date:
            feas_end = (feasibility.current_date - eff).days
        closing_offset = (closing.current_date - eff).days if closing and closing.current_date and eff else legacy
        if feas_end is not None and closing_offset >= feas_end:
            values["closing_days"] = closing_offset - feas_end
        elif eff:
            values["closing_mode"], values["closing_date"] = "date", eff + timedelta(days=legacy)
    return values


def _feasibility_offset(values):
    """Days from the Effective Date to the end of the Feasibility Period, as written."""
    if values.get("feasibility_mode") == "date":
        eff, end = values.get("effective_date"), values.get("feasibility_date")
        return (end - eff).days if eff and end else None
    return values.get("feasibility_days")


def _retire_term(deal, key, actor):
    term = deal.terms.filter(key=key, status=DealTerm.STATUS_ACTIVE).first()
    if term:
        term.status = DealTerm.STATUS_SUPERSEDED
        term.superseded_at = timezone.now()
        term.save(update_fields=["status", "superseded_at"])
        log_activity(deal, f"Contract term no longer used: {term.label}", actor=actor)


def _set(deal, key, value, actor):
    if value is None:
        _retire_term(deal, key, actor)
    else:
        services.set_term(deal, key, value, actor, note="Entered on the key dates form", recompute=False)


@transaction.atomic
def save(deal, data, actor):
    """Apply the key-dates form. Returns the deal's key deadlines after recomputation."""
    eff = data.get("effective_date")
    existing = DealEvent.objects.filter(deal=deal, key="effective_date").first()
    if eff and (not existing or existing.occurred_on != eff or existing.status != DealEvent.STATUS_CONFIRMED):
        services.record_event(deal, "effective_date", eff, actor, evidence_note="Entered on the key dates form")
    elif not eff and existing:
        services.clear_event(deal, "effective_date", actor, "Cleared on the key dates form")

    if deal.is_lease:
        _set(deal, "commencement_date", data.get("commencement_date"), actor)
    else:
        fmode = data.get("feasibility_mode") or "days"
        _set(deal, FEASIBILITY_TERMS[fmode], data.get("feasibility_date") if fmode == "date" else data.get("feasibility_days"), actor)
        _retire_term(deal, FEASIBILITY_TERMS["days" if fmode == "date" else "date"], actor)
        if (data.get("closing_mode") or "days") == "date":
            _set(deal, "closing_date", data.get("closing_date"), actor)
            _retire_term(deal, CLOSING_AFTER, actor)
            _retire_term(deal, "closing_days_after_effective", actor)
        else:
            _set(deal, CLOSING_AFTER, data.get("closing_days"), actor)
            _retire_term(deal, "closing_date", actor)
            _retire_term(deal, "closing_days_after_effective", actor)

    _rebuild(deal, data, actor)
    services.sync_deal(deal, actor)
    return key_deadlines(deal)


def _rebuild(deal, data, actor):
    # Deadlines whose term is no longer active are cancelled (kept in history).
    active = deal.active_terms()
    for d in deal.deadlines.filter(template_key__in=KEY_TEMPLATES, state="open"):
        term_key = d.offset_term_key or d.fixed_date_term_key
        if term_key and term_key not in active:
            set_state(d, "cancelled", actor, "Contract term removed on the key dates form")

    generate_standard_deadlines(deal, actor=actor)

    if CLOSING_AFTER in active:
        feasibility = deal.deadlines.filter(template_key__in=["feasibility_fixed", "feasibility_expiration"]).exclude(state__in=["cancelled", "superseded"]).first()
        for closing in deal.deadlines.filter(template_key="closing_offset", state="open"):
            closing.offset_term_key = CLOSING_AFTER
            closing.trigger_keys = [f"deadline:{feasibility.pk}"] if feasibility else ["feasibility_end"]
            closing.save(update_fields=["offset_term_key", "trigger_keys"])

    business = HolidayCalendar.objects.filter(code="us-federal").first()
    for d in deal.deadlines.filter(template_key__in=KEY_TEMPLATES, state="open"):
        if data.get("next_business_day"):
            d.weekend_rule, d.holiday_calendar = "next_business_day", business
            d.weekend_rule_source = "Contract provides for it (entered on the key dates form)"
        else:
            d.weekend_rule, d.weekend_rule_source = "none", ""
        d.confirmation = "confirmed"
        d.save(update_fields=["weekend_rule", "holiday_calendar", "weekend_rule_source", "confirmation", "updated_at"])
    recompute_deal(deal, actor=actor, reason="Key dates updated")


def key_deadlines(deal):
    return list(deal.deadlines.filter(template_key__in=KEY_TEMPLATES, state="open").order_by("current_date"))


def timeline(deal, deadlines=None, today=None):
    """Dashboard timeline: Effective Date at the start, then each milestone. A sale
    always shows three marks (Effective Date, Feasibility Period ends in the middle,
    Closing Date at the end) even before dates are entered; dates replaced by an
    extension stay on the track as extra marks. Positions are percentages of the span
    from the Effective Date to the last date."""
    today = today or timezone.localdate()
    if deadlines is None:
        deadlines = key_deadlines(deal)
    by_key = {d.template_key: d for d in deadlines}
    spec = milestone_spec(deal)
    points = []
    closing_after = None
    for label, keys in spec:
        d = next((by_key[k] for k in keys if k in by_key), None)
        awaiting = bool(d and d.current_date is None)
        if d is None and "closing_offset" in keys:
            # Written as days after the Feasibility Period, which has no date yet.
            if closing_after is None:
                closing_after = deal.terms.filter(key=CLOSING_AFTER, status=DealTerm.STATUS_ACTIVE).exists()
            awaiting = closing_after
        points.append({"label": label, "date": d.current_date if d else None, "deadline": d, "awaiting": awaiting})
    replaced = {}
    if not deal.is_lease:
        for ext in deal.extensions.all():
            replaced.setdefault(ext.milestone, []).append(ext.previous_date)
    for p, key in zip(points, EXTENSION_MILESTONES if not deal.is_lease else [None]):
        p["replaced"] = replaced.get(key, [])

    start = deal.effective_date
    dates = [p["date"] for p in points if p["date"]] + [d for p in points for d in p["replaced"]]
    end = max(dates) if dates else None
    span = None
    if start and end and end > start:
        span = (end - start).days
        if not points[-1]["date"]:
            span *= 2  # no end date yet: the latest known date sits in the middle
    # Where a milestone goes when it has no position of its own.
    slots = [round(100 * (i + 1) / len(points)) for i in range(len(points))]

    def pos(day):
        return max(0, min(100, round(100 * (day - start).days / span))) if span and day else None

    for p, slot in zip(points, slots):
        p["pos"] = pos(p["date"])
        p["slot"] = slot if p["pos"] is None else p["pos"]
        p["passed"] = bool(p["date"] and p["date"] < today)
        p["days_left"] = (p["date"] - today).days if p["date"] else None
    today_pos = max(0, min(100, round(100 * (today - start).days / span))) if span else None
    upcoming = next((p for p in points if p["date"] and p["date"] >= today), None)
    marks = _marks(start, points, upcoming, today, pos)
    return {"start": start, "end": end, "points": points, "today_pos": today_pos,
            "complete": bool(start and all(p["date"] for p in points)), "next": upcoming,
            "marks": marks, "has_above": any(m["above"] for m in marks)}


# Labels closer than this (percent of the track) would overlap, so the later one
# goes above the track instead.
MARK_GAP = 24


def _marks(start, points, upcoming, today, pos):
    """Axis marks: the Effective Date, every milestone (at its date, or at its slot
    when not entered yet) and every date an extension replaced."""
    marks = [{"label": gettext_noop("Effective Date"), "date": start, "pos": 0, "kind": "start" if start else "missing",
              "passed": bool(start and start <= today), "next": False, "extended": False, "awaiting": False}]
    for p in points:
        marks.append({"label": p["label"], "date": p["date"], "pos": p["slot"],
                      "kind": "main" if p["date"] else "missing", "passed": p["passed"],
                      "next": p is upcoming, "extended": bool(p["replaced"]), "awaiting": p["awaiting"]})
        for was in p["replaced"]:
            if pos(was) is not None:
                marks.append({"label": gettext_noop("Before extension"), "date": was, "pos": pos(was), "kind": "was",
                              "passed": was < today, "next": False, "extended": False, "awaiting": False})
    marks.sort(key=lambda m: m["pos"])
    last_below = last_above = None
    for m in marks:
        m["align"] = "start" if m["pos"] < 12 else "end" if m["pos"] > 88 else "mid"
        if last_below is None or m["pos"] - last_below >= MARK_GAP:
            m["above"], last_below = False, m["pos"]
        elif last_above is None or m["pos"] - last_above >= MARK_GAP:
            m["above"], last_above = True, m["pos"]
        else:
            m["above"], last_below = False, m["pos"]
    return marks


# --- Extensions ----------------------------------------------------------------

EXTENSION_MILESTONES = ["feasibility", "closing"]  # same order as SALE_MILESTONES


class ExtensionError(ValueError):
    pass


def _current(deal, milestone):
    keys = dict(zip(EXTENSION_MILESTONES, [k for _, k in SALE_MILESTONES]))[milestone]
    by_key = {d.template_key: d for d in key_deadlines(deal)}
    d = next((by_key[k] for k in keys if k in by_key), None)
    return d.current_date if d else None


def _move(values, milestone, new_date):
    """Write the new date back in the contract's own form. A Closing Date extension
    always names a date, so the Closing Date becomes a fixed date."""
    eff = values["effective_date"]
    if milestone == "feasibility":
        if values["feasibility_mode"] == "date":
            values["feasibility_date"] = new_date
        else:
            values["feasibility_days"] = (new_date - eff).days
    else:
        values["closing_mode"], values["closing_date"] = "date", new_date


@transaction.atomic
def extend(deal, milestone, actor, new_date=None, days=None, note=""):
    """Extend the Feasibility Period or the Closing Date to new_date (or by `days`
    from the current date). When the Closing Date is written as N days after the
    Feasibility Period, a Feasibility extension moves it as well; a fixed Closing
    Date stays. Returns the DateExtension rows made."""
    from .models import DateExtension

    if deal.is_lease:
        raise ExtensionError(gettext_noop("Leases have no Feasibility Period or Closing Date to extend."))
    values = current_values(deal)
    if not values["effective_date"]:
        raise ExtensionError(gettext_noop("Enter the Effective Date first."))
    old = _current(deal, milestone)
    if not old:
        raise ExtensionError(gettext_noop("This date has not been entered yet. Enter it on the key dates form first."))
    new = new_date or old + timedelta(days=days)
    if new <= old:
        raise ExtensionError(gettext_noop("The new date must be later than the current date."))
    closing_before = _current(deal, "closing")
    _move(values, milestone, new)
    save(deal, values, actor)
    made = [(milestone, old, note)]
    closing_after = _current(deal, "closing")
    if milestone == "feasibility" and closing_before and closing_after and closing_after != closing_before:
        made.append(("closing", closing_before, "Moved with the Feasibility Period extension"))
    rows = []
    for key, was, why in made:
        landed = _current(deal, key)  # may differ if the contract moves weekend dates
        rows.append(DateExtension.objects.create(deal=deal, milestone=key, previous_date=was, new_date=landed,
                                                 note=why, created_by=actor))
        log_activity(deal, f"{dict(DateExtension.MILESTONES)[key]} extended: {was} -> {landed}", actor=actor)
    return rows
