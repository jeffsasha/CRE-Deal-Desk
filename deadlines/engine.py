"""Deterministic deadline computation.

This module has no database access and no AI. Every date it produces comes with a
plain-English explanation of the rule that produced it. It never supplies a default
period, never substitutes a missing trigger, and never moves a weekend deadline
unless the rule says the contract establishes that adjustment.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

COMPUTED = "computed"
AWAITING_TRIGGER = "awaiting_trigger"
NEEDS_REVIEW = "needs_review"

WEEKDAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass
class Trigger:
    key: str
    label: str
    on: date | None = None
    confirmed: bool = False


@dataclass
class Rule:
    rule_type: str  # fixed | fixed_term | offset | later_of | earlier_of
    fixed_date: date | None = None
    offset_days: int | None = None
    day_basis: str = "calendar"  # calendar | business
    include_trigger_day: bool = False
    holidays: frozenset = frozenset()
    weekend_rule: str = "none"  # none | next_business_day | previous_business_day
    due_time: time | None = None
    time_zone: str = "America/Chicago"
    offset_source: str = ""  # human description of where offset_days came from
    fixed_source: str = ""


@dataclass
class Result:
    status: str
    on: date | None = None
    due_at: datetime | None = None
    explanation: str = ""
    missing: list = field(default_factory=list)


def fmt(d):
    return f"{WEEKDAY[d.weekday()]} {d:%b} {d.day}, {d.year}"


def is_business_day(d, holidays):
    return d.weekday() < 5 and d not in holidays


def add_calendar_days(start, n, include_trigger_day):
    if include_trigger_day:
        if n < 1:
            raise ValueError("When the trigger day counts as day 1, the period must be at least 1 day.")
        return start + timedelta(days=n - 1)
    return start + timedelta(days=n)


def add_business_days(start, n, include_trigger_day, holidays):
    if n < 0:
        raise ValueError("Business-day periods must not be negative.")
    current = start
    counted = 0
    if include_trigger_day and is_business_day(start, holidays):
        counted = 1
        if counted >= n:
            return start
    while counted < n:
        current += timedelta(days=1)
        if is_business_day(current, holidays):
            counted += 1
    return current


def adjust_for_weekend(d, weekend_rule, holidays):
    """Only applied when a rule establishes it. Returns (date, note)."""
    if weekend_rule == "none" or is_business_day(d, holidays):
        return d, ""
    original = d
    step = 1 if weekend_rule == "next_business_day" else -1
    while not is_business_day(d, holidays):
        d += timedelta(days=step)
    reason = "a weekend" if original.weekday() >= 5 else "a holiday"
    direction = "next" if step == 1 else "previous"
    return d, f" {fmt(original)} falls on {reason}; moved to the {direction} business day per the contract rule."


def to_aware(d, due_time, tz_name):
    """Attach the deadline's local time of day in its own time zone. zoneinfo handles
    daylight saving time; the stored value is an aware datetime."""
    if due_time is None:
        return None
    return datetime.combine(d, due_time, tzinfo=ZoneInfo(tz_name))


def compute(rule, triggers):
    """Compute a deadline. `triggers` are the events named by the rule."""
    if rule.rule_type in {"fixed", "fixed_term"}:
        if rule.fixed_date is None:
            src = rule.fixed_source or "fixed date"
            if rule.rule_type == "fixed_term":
                return Result(NEEDS_REVIEW, explanation=f"No approved value for {src}. Approve the contract term or enter the date.")
            return Result(NEEDS_REVIEW, explanation="No fixed date entered.")
        d, note = adjust_for_weekend(rule.fixed_date, rule.weekend_rule, rule.holidays)
        src = f" from {rule.fixed_source}" if rule.fixed_source else ""
        return Result(COMPUTED, d, to_aware(d, rule.due_time, rule.time_zone), f"Fixed date{src}: {fmt(rule.fixed_date)}.{note}")

    if not triggers:
        return Result(NEEDS_REVIEW, explanation="The rule names no trigger event.")
    if rule.offset_days is None:
        src = rule.offset_source or "the period length"
        return Result(NEEDS_REVIEW, explanation=f"No approved value for {src}. No default period is applied.")

    missing = [t for t in triggers if t.on is None]
    unconfirmed = [t for t in triggers if t.on is not None and not t.confirmed]
    if unconfirmed:
        names = ", ".join(t.label for t in unconfirmed)
        return Result(NEEDS_REVIEW, explanation=f"Trigger recorded but not confirmed: {names}. Resolve before relying on a date.",
                      missing=[t.key for t in unconfirmed])
    if missing:
        names = ", ".join(t.label for t in missing)
        return Result(AWAITING_TRIGGER, explanation=f"Awaiting trigger: {names}. No date is computed until the actual event date is recorded.",
                      missing=[t.key for t in missing])

    if rule.rule_type == "offset":
        anchor = triggers[0]
        anchor_desc = f"{anchor.label} {fmt(anchor.on)}"
    elif rule.rule_type in {"later_of", "earlier_of"}:
        pick = max if rule.rule_type == "later_of" else min
        anchor = pick(triggers, key=lambda t: t.on)
        which = "later" if rule.rule_type == "later_of" else "earlier"
        listed = "; ".join(f"{t.label} {fmt(t.on)}" for t in triggers)
        anchor_desc = f"the {which} of ({listed}) = {fmt(anchor.on)}"
    else:
        return Result(NEEDS_REVIEW, explanation=f"Unknown rule type {rule.rule_type!r}.")

    n = rule.offset_days
    try:
        if rule.day_basis == "business":
            d = add_business_days(anchor.on, n, rule.include_trigger_day, rule.holidays)
            basis = "business days"
        else:
            d = add_calendar_days(anchor.on, n, rule.include_trigger_day)
            basis = "calendar days"
    except ValueError as exc:
        return Result(NEEDS_REVIEW, explanation=str(exc))

    counting = "trigger day counted as day 1" if rule.include_trigger_day else "trigger day excluded"
    src = f" ({rule.offset_source})" if rule.offset_source else ""
    d2, note = adjust_for_weekend(d, rule.weekend_rule, rule.holidays)
    if rule.weekend_rule == "none" and not is_business_day(d, rule.holidays) and rule.day_basis == "calendar":
        note = f" Falls on a {'weekend' if d.weekday() >= 5 else 'holiday'}; not moved because no adjustment rule is established."
    explanation = f"{anchor_desc} + {n} {basis}{src}, {counting} = {fmt(d)}.{note}"
    return Result(COMPUTED, d2, to_aware(d2, rule.due_time, rule.time_zone), explanation)
