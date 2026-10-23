"""Key dates entered by hand from the executed contract.

The user enters the Effective Date and the contract periods; deadlines are computed by
the rule engine (deadlines/engine.py) exactly as before:
  sale / business: Feasibility Period = N days after the Effective Date;
                   Closing Date = a fixed date, or N days after the Effective Date.
  lease:           Commencement Date (fixed date).
Days are calendar days and the Effective Date itself is not counted. A deadline that
falls on a weekend or holiday is moved to the next business day only when the user
says the contract provides for it. Superseded values stay in history.
"""
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_noop

from core.models import HolidayCalendar
from deadlines.services import generate_standard_deadlines, recompute, set_state

from . import services
from .models import DealEvent, DealTerm, log_activity

# Milestones shown on the dashboard timeline, per deal kind: (label, deadline template keys)
SALE_MILESTONES = [(gettext_noop("Feasibility Period ends"), ["feasibility_expiration"]),
                   (gettext_noop("Closing Date"), ["closing_fixed", "closing_offset"])]
LEASE_MILESTONES = [(gettext_noop("Commencement Date"), ["lease_commencement"])]
KEY_TEMPLATES = {"feasibility_expiration", "closing_fixed", "closing_offset", "lease_commencement"}
CLOSING_TERMS = {"date": "closing_date", "days": "closing_days_after_effective"}


def milestone_spec(deal):
    return LEASE_MILESTONES if deal.is_lease else SALE_MILESTONES


def current_values(deal):
    terms = deal.active_terms()
    ev = DealEvent.objects.filter(deal=deal, key="effective_date").first()
    key_deadlines = deal.deadlines.filter(template_key__in=KEY_TEMPLATES).exclude(state__in=["superseded", "cancelled"])
    return {
        "effective_date": ev.occurred_on if ev else None,
        "feasibility_days": terms["feasibility_period_days"].value_int if "feasibility_period_days" in terms else None,
        "closing_mode": "date" if "closing_date" in terms else "days",
        "closing_date": terms["closing_date"].value_date if "closing_date" in terms else None,
        "closing_days": terms["closing_days_after_effective"].value_int if "closing_days_after_effective" in terms else None,
        "commencement_date": terms["commencement_date"].value_date if "commencement_date" in terms else None,
        "next_business_day": any(d.weekend_rule == "next_business_day" for d in key_deadlines),
    }


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
        _set(deal, "feasibility_period_days", data.get("feasibility_days"), actor)
        mode = data.get("closing_mode") or "days"
        value = data.get("closing_date") if mode == "date" else data.get("closing_days")
        _set(deal, CLOSING_TERMS[mode], value, actor)
        _retire_term(deal, CLOSING_TERMS["days" if mode == "date" else "date"], actor)

    # Deadlines whose term is no longer active are cancelled (kept in history).
    active = deal.active_terms()
    for d in deal.deadlines.filter(template_key__in=KEY_TEMPLATES, state="open"):
        term_key = d.offset_term_key or d.fixed_date_term_key
        if term_key and term_key not in active:
            set_state(d, "cancelled", actor, "Contract term removed on the key dates form")

    generate_standard_deadlines(deal, actor=actor)

    business = HolidayCalendar.objects.filter(code="us-federal").first()
    for d in deal.deadlines.filter(template_key__in=KEY_TEMPLATES, state="open"):
        if data.get("next_business_day"):
            d.weekend_rule, d.holiday_calendar = "next_business_day", business
            d.weekend_rule_source = "Contract provides for it (entered on the key dates form)"
        else:
            d.weekend_rule, d.weekend_rule_source = "none", ""
        d.confirmation = "confirmed"
        d.save(update_fields=["weekend_rule", "holiday_calendar", "weekend_rule_source", "confirmation", "updated_at"])
    for d in deal.deadlines.filter(state="open"):
        recompute(d, actor=actor, reason="Key dates updated")
    services.sync_deal(deal, actor)
    return key_deadlines(deal)


def key_deadlines(deal):
    return list(deal.deadlines.filter(template_key__in=KEY_TEMPLATES, state="open").order_by("current_date"))


def timeline(deal, deadlines=None, today=None):
    """Dashboard timeline: Effective Date at the start, then each milestone. Positions
    are percentages of the span from the Effective Date to the last milestone."""
    today = today or timezone.localdate()
    if deadlines is None:
        deadlines = key_deadlines(deal)
    by_key = {d.template_key: d for d in deadlines}
    points = []
    for label, keys in milestone_spec(deal):
        d = next((by_key[k] for k in keys if k in by_key), None)
        points.append({"label": label, "date": d.current_date if d else None, "deadline": d,
                       "awaiting": bool(d and d.current_date is None)})
    start = deal.effective_date
    dated = [p["date"] for p in points if p["date"]]
    end = max(dated) if dated else None
    span = (end - start).days if start and end and end > start else None
    for p in points:
        p["pos"] = round(100 * (p["date"] - start).days / span) if span and p["date"] else None
        p["passed"] = bool(p["date"] and p["date"] < today)
        p["days_left"] = (p["date"] - today).days if p["date"] else None
    today_pos = None
    if span:
        today_pos = max(0, min(100, round(100 * (today - start).days / span)))
    upcoming = next((p for p in points if p["date"] and p["date"] >= today), None)
    marks, unplaced = _marks(start, points, upcoming, today)
    return {"start": start, "end": end, "points": points, "today_pos": today_pos,
            "complete": bool(start and all(p["date"] for p in points)), "next": upcoming,
            "marks": marks, "unplaced": unplaced, "has_above": any(m["above"] for m in marks)}


# Labels closer than this (percent of the track) would overlap, so the later one
# goes above the track instead.
MARK_GAP = 24


def _marks(start, points, upcoming, today):
    """Axis marks: the Effective Date and every milestone that has a position, each
    labelled at its own spot. Milestones without a position are listed separately."""
    marks = []
    if start:
        marks.append({"label": gettext_noop("Effective Date"), "date": start, "pos": 0,
                      "passed": start <= today, "next": False})
    unplaced = []
    for p in points:
        if p["pos"] is None:
            unplaced.append(p)
        else:
            marks.append({"label": p["label"], "date": p["date"], "pos": p["pos"],
                          "passed": p["passed"], "next": p is upcoming})
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
    return marks, unplaced
