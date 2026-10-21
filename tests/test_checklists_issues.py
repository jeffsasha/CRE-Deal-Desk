"""Checklist semantics and the issue register."""
from django.core.exceptions import ValidationError
from django.utils import timezone

from checklists.models import ChecklistTemplate
from checklists.services import apply_template, update_item
from deals.models import PriceEvent
from deals.services import set_term

from .base import DeskTestCase


class ChecklistTests(DeskTestCase):
    def setUp(self):
        self.broker = self.user("broker")
        self.deal = self.deal(actor=self.broker)
        apply_template(self.deal, ChecklistTemplate.objects.get(key="acquisition"), {"financing": False}, self.broker)
        self.items = {i.title: i for i in self.deal.checklist_items.all()}

    def test_title_and_insurance_items_are_separate(self):
        titles = set(self.items)
        for t in ["Title commitment received", "Final owner's title insurance policy received",
                  "Lender's title insurance policy received", "Property insurance binder issued"]:
            self.assertIn(t, titles)

    def test_conditional_items_not_applicable_with_reason(self):
        loan = self.items["Loan commitment received"]
        self.assertEqual(loan.status, "not_applicable")
        self.assertIn("condition not met", loan.not_applicable_reason)

    def test_received_is_not_reviewed(self):
        it = self.items["Survey received"]
        old = it.status
        it.status = "received"
        update_item(it, self.broker, old)
        it.refresh_from_db()
        self.assertEqual(it.status, "received")
        self.assertIsNotNone(it.received_on)
        self.assertIsNone(it.reviewed_on)
        self.assertIsNone(it.approved_on)
        self.assertTrue(it.is_open)

    def test_validation(self):
        it = self.items["Survey reviewed (encroachments, access, exceptions)"]
        it.status = "under_review"
        with self.assertRaises(ValidationError):
            update_item(it, self.broker, "not_started")
        it.status = "not_applicable"
        with self.assertRaises(ValidationError):
            update_item(it, self.broker, "not_started")
        it.status = "blocked"
        with self.assertRaises(ValidationError):
            update_item(it, self.broker, "not_started")


class IssueTests(DeskTestCase):
    def test_requested_credit_does_not_change_price(self):
        broker = self.user("broker")
        deal = self.deal(actor=broker)
        set_term(deal, "purchase_price", 285000000, broker)
        self.client.force_login(broker)
        resp = self.client.post(f"/issues/new/?deal={deal.pk}", {
            "title": "HVAC", "category": "hvac", "severity": "high", "status": "open", "requested_credit": "$45,000",
            "resolution_status": "proposed", "disclosure_finding": "not_found"})
        self.assertEqual(resp.status_code, 302)
        deal.refresh_from_db()
        self.assertEqual(deal.executed_contract_price_cents, 285000000)
        self.assertTrue(PriceEvent.objects.filter(deal=deal, kind="requested_credit", amount_cents=4500000).exists())
        self.assertFalse(PriceEvent.objects.filter(deal=deal, kind__in=["executed_contract", "amendment"]).exists())

    def test_executed_resolution_requires_document(self):
        broker = self.user("broker")
        deal = self.deal(actor=broker)
        self.client.force_login(broker)
        resp = self.client.post(f"/issues/new/?deal={deal.pk}", {
            "title": "Roof", "category": "roof", "severity": "high", "status": "open", "resolution_status": "executed",
            "disclosure_finding": "not_assessed"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "An executed resolution needs the executed document")


class TermHistoryTests(DeskTestCase):
    def test_superseded_terms_kept(self):
        broker = self.user("broker")
        deal = self.deal(actor=broker)
        set_term(deal, "closing_date", timezone.localdate(), broker)
        set_term(deal, "closing_date", timezone.localdate().replace(day=1), broker, note="correction")
        self.assertEqual(deal.terms.filter(key="closing_date").count(), 2)
        self.assertEqual(deal.terms.filter(key="closing_date", status="active").count(), 1)
