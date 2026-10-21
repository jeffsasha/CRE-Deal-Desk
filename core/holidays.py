"""Holiday calendar generation.

Holiday calendars only matter for deadlines whose rule says business days count, or
whose contract establishes a weekend/holiday adjustment. They never move a deadline
on their own.
"""
from datetime import date, timedelta


def _nth_weekday(year, month, weekday, n):
    d = date(year, month, 1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year, month, weekday):
    d = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def _observed(d):
    """Federal observance: Saturday holidays are observed Friday, Sunday holidays Monday."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def us_federal_holidays(year):
    """Observed U.S. federal holidays (5 U.S.C. 6103) for a year."""
    mon, thu = 0, 3
    fixed = [
        (date(year, 1, 1), "New Year's Day"),
        (date(year, 6, 19), "Juneteenth National Independence Day"),
        (date(year, 7, 4), "Independence Day"),
        (date(year, 11, 11), "Veterans Day"),
        (date(year, 12, 25), "Christmas Day"),
    ]
    floating = [
        (_nth_weekday(year, 1, mon, 3), "Birthday of Martin Luther King, Jr."),
        (_nth_weekday(year, 2, mon, 3), "Washington's Birthday"),
        (_last_weekday(year, 5, mon), "Memorial Day"),
        (_nth_weekday(year, 9, mon, 1), "Labor Day"),
        (_nth_weekday(year, 10, mon, 2), "Columbus Day"),
        (_nth_weekday(year, 11, thu, 4), "Thanksgiving Day"),
    ]
    out = []
    for d, name in fixed:
        obs = _observed(d)
        out.append((obs, name if obs == d else f"{name} (observed)"))
    out.extend(floating)
    return sorted(out)


def ensure_default_calendars(years=range(2018, 2036)):
    from .models import Holiday, HolidayCalendar

    cal, _ = HolidayCalendar.objects.get_or_create(
        code="us-federal",
        defaults={
            "name": "U.S. federal holidays (observed)",
            "description": "Generated from 5 U.S.C. 6103 observance rules. Add or remove dates if a contract defines holidays differently.",
        },
    )
    if not cal.holidays.exists():
        Holiday.objects.bulk_create(
            [Holiday(calendar=cal, date=d, name=n) for y in years for d, n in us_federal_holidays(y)],
            ignore_conflicts=True,
        )
    HolidayCalendar.objects.get_or_create(
        code="none",
        defaults={"name": "No holidays (weekends only)", "description": "Business days are Monday through Friday."},
    )
    return cal
