"""Deadline rules: calendar vs business days, trigger-day inclusion, holidays,
weekend adjustment only when established, DST, missing and unconfirmed triggers."""
from datetime import date, time

from django.test import SimpleTestCase

from core.holidays import us_federal_holidays
from deadlines import engine
from deadlines.engine import AWAITING_TRIGGER, COMPUTED, NEEDS_REVIEW, Rule, Trigger


def trig(d, key="effective_date", confirmed=True):
    return Trigger(key=key, label=key, on=d, confirmed=confirmed)


class CalendarDayTests(SimpleTestCase):
    def test_trigger_day_excluded_by_default(self):
        r = engine.compute(Rule("offset", offset_days=10), [trig(date(2026, 3, 2))])
        self.assertEqual(r.status, COMPUTED)
        self.assertEqual(r.on, date(2026, 3, 12))
        self.assertIn("trigger day excluded", r.explanation)

    def test_trigger_day_included(self):
        r = engine.compute(Rule("offset", offset_days=10, include_trigger_day=True), [trig(date(2026, 3, 2))])
        self.assertEqual(r.on, date(2026, 3, 11))

    def test_sunday_deadline_not_moved_without_rule(self):
        # Mar 1 2026 is a Sunday: Feb 19 + 10 days.
        r = engine.compute(Rule("offset", offset_days=10), [trig(date(2026, 2, 19))])
        self.assertEqual(r.on, date(2026, 3, 1))
        self.assertEqual(r.on.weekday(), 6)
        self.assertIn("not moved", r.explanation)

    def test_sunday_moved_only_when_contract_rule_established(self):
        r = engine.compute(Rule("offset", offset_days=10, weekend_rule="next_business_day"), [trig(date(2026, 2, 19))])
        self.assertEqual(r.on, date(2026, 3, 2))

    def test_holiday_adjustment_uses_calendar(self):
        holidays = frozenset(d for d, _ in us_federal_holidays(2026))
        # July 4 2026 is a Saturday (observed Fri July 3); deadline lands on Fri Jul 3.
        r = engine.compute(Rule("offset", offset_days=2, weekend_rule="next_business_day", holidays=holidays),
                           [trig(date(2026, 7, 1))])
        self.assertEqual(r.on, date(2026, 7, 6))

    def test_previous_business_day_rule(self):
        r = engine.compute(Rule("offset", offset_days=10, weekend_rule="previous_business_day"), [trig(date(2026, 2, 19))])
        self.assertEqual(r.on, date(2026, 2, 27))


class BusinessDayTests(SimpleTestCase):
    def test_business_days_skip_weekends(self):
        # Thu Mar 5 2026 + 3 business days = Tue Mar 10.
        r = engine.compute(Rule("offset", offset_days=3, day_basis="business"), [trig(date(2026, 3, 5))])
        self.assertEqual(r.on, date(2026, 3, 10))

    def test_business_days_skip_holidays(self):
        holidays = frozenset(d for d, _ in us_federal_holidays(2026))
        # Fri Nov 20 2026 + 4 business days; Thanksgiving Nov 26 is skipped -> Fri Nov 27.
        r = engine.compute(Rule("offset", offset_days=4, day_basis="business", holidays=holidays), [trig(date(2026, 11, 20))])
        self.assertEqual(r.on, date(2026, 11, 27))

    def test_business_days_include_trigger(self):
        r = engine.compute(Rule("offset", offset_days=3, day_basis="business", include_trigger_day=True), [trig(date(2026, 3, 5))])
        self.assertEqual(r.on, date(2026, 3, 9))


class TriggerTests(SimpleTestCase):
    def test_missing_trigger_awaits(self):
        r = engine.compute(Rule("offset", offset_days=10), [trig(None)])
        self.assertEqual(r.status, AWAITING_TRIGGER)
        self.assertIsNone(r.on)

    def test_unconfirmed_trigger_needs_review(self):
        r = engine.compute(Rule("offset", offset_days=10), [trig(date(2026, 3, 1), confirmed=False)])
        self.assertEqual(r.status, NEEDS_REVIEW)
        self.assertIsNone(r.on)

    def test_missing_period_never_defaults(self):
        r = engine.compute(Rule("offset", offset_days=None, offset_source="contract term: Feasibility"), [trig(date(2026, 3, 1))])
        self.assertEqual(r.status, NEEDS_REVIEW)
        self.assertIsNone(r.on)
        self.assertIn("No default period", r.explanation)

    def test_later_of_two_events(self):
        r = engine.compute(Rule("later_of", offset_days=10),
                           [trig(date(2026, 3, 4), "title_commitment_received"), trig(date(2026, 3, 9), "survey_received")])
        self.assertEqual(r.on, date(2026, 3, 19))

    def test_later_of_waits_for_all_events(self):
        r = engine.compute(Rule("later_of", offset_days=10),
                           [trig(date(2026, 3, 4), "title_commitment_received"), trig(None, "survey_received")])
        self.assertEqual(r.status, AWAITING_TRIGGER)
        self.assertEqual(r.missing, ["survey_received"])

    def test_earlier_of(self):
        r = engine.compute(Rule("earlier_of", offset_days=5), [trig(date(2026, 3, 4), "a"), trig(date(2026, 3, 9), "b")])
        self.assertEqual(r.on, date(2026, 3, 9))

    def test_fixed_term_missing_needs_review(self):
        r = engine.compute(Rule("fixed_term", fixed_date=None, fixed_source="contract term: Closing date"), [])
        self.assertEqual(r.status, NEEDS_REVIEW)


class TimeZoneTests(SimpleTestCase):
    def test_dst_offsets(self):
        before = engine.compute(Rule("fixed", fixed_date=date(2026, 3, 6), due_time=time(17, 0)), [])
        after = engine.compute(Rule("fixed", fixed_date=date(2026, 3, 9), due_time=time(17, 0)), [])
        self.assertEqual(before.due_at.utcoffset().total_seconds(), -6 * 3600)  # CST
        self.assertEqual(after.due_at.utcoffset().total_seconds(), -5 * 3600)  # CDT after Mar 8 2026

    def test_other_time_zone(self):
        r = engine.compute(Rule("fixed", fixed_date=date(2026, 6, 1), due_time=time(17, 0), time_zone="America/New_York"), [])
        self.assertEqual(r.due_at.utcoffset().total_seconds(), -4 * 3600)

    def test_no_time_means_no_instant(self):
        r = engine.compute(Rule("fixed", fixed_date=date(2026, 6, 1)), [])
        self.assertIsNone(r.due_at)


class HolidayTests(SimpleTestCase):
    def test_observed_rules(self):
        h = dict(us_federal_holidays(2027))
        self.assertIn(date(2027, 12, 24), h)  # Christmas 2027 is Saturday -> Friday
        self.assertIn(date(2027, 7, 5), h)  # July 4 2027 is Sunday -> Monday
