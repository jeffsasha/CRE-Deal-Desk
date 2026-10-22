"""Receipt-triggered deadlines, key dates entered by hand (calendar days, weekend rule
only when the contract provides it), changes with revision history and reminder
replacement."""
from datetime import date

from django.core.exceptions import ValidationError
from django.urls import reverse

from deadlines.models import Reminder
from deadlines.services import create_deadline, generate_standard_deadlines
from deals import keydates
from deals.models import DealEvent
from deals.services import record_event, set_term

from .base import DeskTestCase


class ReceiptTriggerTests(DeskTestCase):
    def setUp(self):
        self.broker = self.user("broker")
        self.deal = self.deal(actor=self.broker, responsible_broker=self.broker)
        set_term(self.deal, "title_objection_days", 10, self.broker)
        self.objection = create_deadline(actor=self.broker, deal=self.deal, name="Objection deadline", category="title",
                                         rule_type="later_of", trigger_keys=["title_commitment_received", "survey_received"],
                                         offset_term_key="title_objection_days")

    def test_awaiting_until_receipts_recorded(self):
        self.objection.refresh_from_db()
        self.assertEqual(self.objection.computation, "awaiting_trigger")
        self.assertIsNone(self.objection.current_date)
        record_event(self.deal, "title_commitment_received", date(2026, 3, 4), self.broker, evidence_note="email")
        self.objection.refresh_from_db()
        self.assertEqual(self.objection.computation, "awaiting_trigger")  # survey still missing
        record_event(self.deal, "survey_received", date(2026, 3, 9), self.broker, evidence_note="email")
        self.objection.refresh_from_db()
        self.assertEqual(self.objection.computation, "computed")
        self.assertEqual(self.objection.current_date, date(2026, 3, 19))

    def test_unconfirmed_receipt_needs_review(self):
        record_event(self.deal, "title_commitment_received", date(2026, 3, 4), self.broker, status="needs_review")
        record_event(self.deal, "survey_received", date(2026, 3, 9), self.broker, evidence_note="x")
        self.objection.refresh_from_db()
        self.assertEqual(self.objection.computation, "needs_review")
        self.assertIsNone(self.objection.current_date)

    def test_confirmed_event_requires_date(self):
        with self.assertRaises(ValidationError):
            record_event(self.deal, "survey_received", None, self.broker)


class GenerateDeadlinesTests(DeskTestCase):
    def test_only_approved_terms_generate_deadlines(self):
        broker = self.user("broker")
        deal = self.deal(actor=broker)
        set_term(deal, "feasibility_period_days", 45, broker)
        created, skipped = generate_standard_deadlines(deal, broker)
        self.assertEqual([d.template_key for d in created], ["feasibility_expiration"])
        self.assertTrue(any("not approved" in s for s in skipped))
        self.assertEqual(created[0].computation, "awaiting_trigger")  # no effective date


class KeyDatesTests(DeskTestCase):
    def setUp(self):
        self.broker = self.user("broker", email="b@example.invalid")
        self.deal = self.deal(name="Gessner", actor=self.broker, responsible_broker=self.broker)

    def save(self, **data):
        return keydates.save(self.deal, data, self.broker)

    def by_key(self):
        return {d.template_key: d for d in keydates.key_deadlines(self.deal)}

    def test_days_after_effective_date(self):
        # Mar 4, 2026 + 30 calendar days (the Effective Date is not counted) = Apr 3.
        self.save(effective_date=date(2026, 3, 4), feasibility_days=30, closing_mode="days", closing_days=60)
        d = self.by_key()
        self.assertEqual(d["feasibility_expiration"].current_date, date(2026, 4, 3))
        self.assertEqual(d["closing_offset"].current_date, date(2026, 5, 3))
        self.deal.refresh_from_db()
        self.assertEqual(self.deal.effective_date, date(2026, 3, 4))
        self.assertEqual(self.deal.contractual_closing_date, date(2026, 5, 3))

    def test_weekend_not_moved_unless_contract_says_so(self):
        # Mar 4 + 21 = Wed Mar 25; + 25 = Sun Mar 29.
        self.save(effective_date=date(2026, 3, 4), feasibility_days=25, closing_mode="days", closing_days=60)
        self.assertEqual(self.by_key()["feasibility_expiration"].current_date, date(2026, 3, 29))
        self.save(effective_date=date(2026, 3, 4), feasibility_days=25, closing_mode="days", closing_days=60,
                  next_business_day=True)
        self.assertEqual(self.by_key()["feasibility_expiration"].current_date, date(2026, 3, 30))

    def test_without_effective_date_nothing_is_invented(self):
        self.save(feasibility_days=30, closing_mode="days", closing_days=60)
        d = self.by_key()
        self.assertEqual({x.computation for x in d.values()}, {"awaiting_trigger"})
        self.assertFalse(any(x.current_date for x in d.values()))
        tl = keydates.timeline(self.deal)
        self.assertFalse(tl["complete"])
        self.assertTrue(all(p["awaiting"] for p in tl["points"]))

    def test_change_keeps_history_and_replaces_reminders(self):
        self.save(effective_date=date(2026, 3, 4), feasibility_days=30, closing_mode="date", closing_date=date(2026, 6, 1))
        closing = self.by_key()["closing_fixed"]
        before = set(Reminder.objects.filter(deadline=closing, status="scheduled").values_list("pk", flat=True))
        self.assertTrue(before)
        self.save(effective_date=date(2026, 3, 4), feasibility_days=30, closing_mode="date", closing_date=date(2026, 6, 15))
        closing.refresh_from_db()
        self.assertEqual(closing.current_date, date(2026, 6, 15))
        self.assertEqual(closing.original_date, date(2026, 6, 1))
        rev = closing.revisions.first()
        self.assertEqual((rev.previous_date, rev.new_date), (date(2026, 6, 1), date(2026, 6, 15)))
        self.assertEqual(self.deal.terms.get(key="closing_date", status="superseded").value_date, date(2026, 6, 1))
        old = Reminder.objects.filter(pk__in=before)
        self.assertEqual(old.count(), len(before))  # cancelled, not deleted
        self.assertTrue(all(r.status == "cancelled" for r in old))

    def test_switching_closing_basis_cancels_the_other_deadline(self):
        self.save(effective_date=date(2026, 3, 4), feasibility_days=30, closing_mode="days", closing_days=60)
        self.save(effective_date=date(2026, 3, 4), feasibility_days=30, closing_mode="date", closing_date=date(2026, 7, 1))
        self.assertEqual(self.deal.deadlines.get(template_key="closing_offset").state, "cancelled")
        self.assertEqual(self.by_key()["closing_fixed"].current_date, date(2026, 7, 1))
        self.assertFalse(self.deal.terms.filter(key="closing_days_after_effective", status="active").exists())

    def test_lease_commencement(self):
        lease = DeskTestCase.deal(self, name="Lease", actor=self.broker, transaction_type="lease")
        keydates.save(lease, {"effective_date": date(2026, 3, 4), "commencement_date": date(2026, 5, 1)}, self.broker)
        tl = keydates.timeline(lease, today=date(2026, 4, 1))
        self.assertEqual([(p["label"], p["date"]) for p in tl["points"]], [("Commencement Date", date(2026, 5, 1))])
        self.assertEqual(tl["next"]["date"], date(2026, 5, 1))

    def test_form_round_trip(self):
        self.client.force_login(self.broker)
        url = reverse("deal_key_dates", args=[self.deal.pk])
        resp = self.client.post(url, {"effective_date": "2026-03-04", "feasibility_days": "30", "closing_mode": "date",
                                      "closing_date": "2026-03-01"})
        self.assertContains(resp, "before the Effective Date")
        resp = self.client.post(url, {"effective_date": "2026-03-04", "feasibility_days": "30", "closing_mode": "days",
                                      "closing_days": "45"})
        self.assertRedirects(resp, self.deal.get_absolute_url())
        self.assertEqual(self.by_key()["closing_offset"].current_date, date(2026, 4, 18))
        self.assertTrue(DealEvent.objects.filter(deal=self.deal, key="effective_date").exists())
        page = self.client.get(self.deal.get_absolute_url())
        self.assertContains(page, "Feasibility Period ends")
