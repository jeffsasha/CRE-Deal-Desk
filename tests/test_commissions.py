"""Commission arithmetic in integer cents; derived status; partial receipts; separate
designated-broker distributions; unknown stays unknown; reversals."""
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError

from commissions.ledger import summarize, tiered_amount
from commissions.models import CommissionAgreement, CommissionAllocation, CommissionInstallment, LedgerEntry
from commissions.services import record_entry, reverse_entry
from core.money import parse_cents, percent_of

from .base import DeskTestCase


class MoneyTests(DeskTestCase):
    def test_parse(self):
        self.assertEqual(parse_cents("$1,250,000.50"), 125000050)
        self.assertIsNone(parse_cents(""))
        self.assertIsNone(parse_cents("unknown"))
        self.assertEqual(parse_cents("0"), 0)
        self.assertEqual(parse_cents("(1,000.00)"), -100000)

    def test_percent_half_up(self):
        self.assertEqual(percent_of(333333, Decimal("3")), 10000)  # 9999.99 -> 10000
        self.assertEqual(percent_of(245000000, Decimal("3.0")), 7350000)
        self.assertEqual(percent_of(None, Decimal("3")), None)

    def test_tiered(self):
        tiers = [{"up_to_cents": 100000000, "rate_percent": "6"}, {"up_to_cents": None, "rate_percent": "4"}]
        # $1.5M: 6% of first $1M + 4% of $500k = 60,000 + 20,000
        self.assertEqual(tiered_amount(150000000, tiers), 8000000)
        self.assertEqual(tiered_amount(50000000, tiers), 3000000)


class LedgerTests(DeskTestCase):
    def setUp(self):
        self.broker = self.user("broker", is_designated_broker=True)
        self.deal = self.deal(stage="closed")
        self.a = CommissionAgreement.objects.create(deal=self.deal, title="A", represented_side="buyer", basis_type="percentage",
                                                    basis_amount_cents=245000000, rate_percent=Decimal("3"))
        CommissionAllocation.objects.create(agreement=self.a, level="payer", recipient_type="skw", recipient_name="SKW",
                                            method="percent_of_gross", percent=Decimal("50"))
        self.coop = CommissionAllocation.objects.create(agreement=self.a, level="payer", recipient_type="cooperating_broker",
                                                        recipient_name="Coop", method="percent_of_gross", percent=Decimal("50"),
                                                        paid_through_skw=False)
        self.db = CommissionAllocation.objects.create(agreement=self.a, level="internal", recipient_type="designated_broker",
                                                      recipient_name="DB", recipient_user=self.broker, method="percent_of_skw",
                                                      percent=Decimal("70"))
        self.inst = CommissionInstallment.objects.create(agreement=self.a, label="At closing", amount_cents=3675000,
                                                         earned_status="earned", earned_on=date(2026, 5, 1))

    def test_amounts(self):
        s = summarize(self.a)
        self.assertEqual(s.gross, 7350000)
        self.assertEqual(s.skw_share, 3675000)
        self.assertEqual(s.expected_receipt, 3675000)  # coop paid directly
        self.assertEqual(s.designated_broker_allocated, 2572500)
        self.assertEqual(s.status, "Earned — awaiting payment")

    def test_partial_receipts_and_distribution(self):
        record_entry(self.a, self.broker, entry_type="receipt", amount_cents=2000000, entry_date=date(2026, 5, 5))
        s = summarize(self.a)
        self.assertEqual(s.status, "Partially received")
        self.assertEqual(s.outstanding, 1675000)
        record_entry(self.a, self.broker, entry_type="distribution", amount_cents=1400000, entry_date=date(2026, 5, 10),
                     allocation=self.db)
        s = summarize(self.a)
        self.assertEqual(s.designated_broker_paid, 1400000)
        self.assertEqual(s.designated_broker_unpaid, 1172500)
        self.assertEqual(s.received, 2000000)  # SKW receipts are separate from distributions
        record_entry(self.a, self.broker, entry_type="receipt", amount_cents=1675000, entry_date=date(2026, 5, 20))
        self.assertEqual(summarize(self.a).status, "Received in full")

    def test_reversal_and_refund(self):
        e = record_entry(self.a, self.broker, entry_type="receipt", amount_cents=3675000, entry_date=date(2026, 5, 5))
        reverse_entry(e, self.broker, date(2026, 5, 6), "Wire recalled")
        s = summarize(self.a)
        self.assertEqual(s.received, 0)
        with self.assertRaises(ValidationError):
            reverse_entry(e, self.broker, date(2026, 5, 6), "again")
        with self.assertRaises(ValidationError):
            record_entry(self.a, self.broker, entry_type="refund", amount_cents=100, entry_date=date(2026, 5, 7))

    def test_distribution_requires_recipient(self):
        with self.assertRaises(ValidationError):
            record_entry(self.a, self.broker, entry_type="distribution", amount_cents=100, entry_date=date(2026, 5, 5))

    def test_no_assumed_split(self):
        a = CommissionAgreement.objects.create(deal=self.deal, title="B", represented_side="seller", basis_type="flat",
                                               flat_amount_cents=1000000)
        s = summarize(a)
        self.assertEqual(s.gross, 1000000)
        self.assertIsNone(s.skw_share)
        self.assertIsNone(s.designated_broker_allocated)
        self.assertTrue(any("SKW's share is unknown" in w for w in s.warnings))

    def test_unknown_basis_stays_unknown(self):
        a = CommissionAgreement.objects.create(deal=self.deal, title="C", represented_side="seller", basis_type="percentage",
                                               rate_percent=Decimal("3"))
        CommissionInstallment.objects.create(agreement=a, label="x", amount_cents=None, earned_status="earned", earned_on=date(2026, 1, 1))
        s = summarize(a)
        self.assertIsNone(s.gross)
        self.assertIsNone(s.outstanding)
        self.assertEqual(s.status, "Earned — amount unknown")

    def test_lease_installments(self):
        a = CommissionAgreement.objects.create(deal=self.deal, title="L", represented_side="tenant", basis_type="percentage",
                                               basis_amount_cents=76500000, rate_percent=Decimal("6"))
        CommissionAllocation.objects.create(agreement=a, level="payer", recipient_type="skw", recipient_name="SKW",
                                            method="percent_of_gross", percent=Decimal("100"))
        i1 = CommissionInstallment.objects.create(agreement=a, sequence=1, label="Execution", amount_cents=2295000,
                                                  earned_status="earned", earned_on=date(2026, 1, 1))
        CommissionInstallment.objects.create(agreement=a, sequence=2, label="Opening", amount_cents=2295000)
        record_entry(a, self.broker, entry_type="receipt", amount_cents=2295000, entry_date=date(2026, 1, 20), installment=i1)
        s = summarize(a)
        self.assertEqual(s.gross, 4590000)
        self.assertEqual(s.status, "Received to date — later installments pending")
        self.assertEqual(s.outstanding, 0)


class SimpleCommissionTests(DeskTestCase):
    """The per-deal view: SKW expected vs received, on the same immutable ledger."""

    def setUp(self):
        from django.urls import reverse

        self.reverse = reverse
        self.broker = self.user("broker")
        self.d = self.deal(actor=self.broker)
        self.client.force_login(self.broker)

    def test_expected_received_and_reversal(self):
        from commissions import simple

        self.assertEqual(simple.for_deal(self.d).status, "unknown")
        self.client.post(self.reverse("deal_commission", args=[self.d.pk]), {"expected": "90,000"})
        c = simple.for_deal(self.d)
        self.assertEqual((c.expected, c.received, c.status), (9_000_000, 0, "none"))
        self.client.post(self.reverse("deal_receipt", args=[self.d.pk]),
                         {"amount": "40,000", "entry_date": "2026-03-04", "reference": "Wire 1"})
        c = simple.for_deal(self.d)
        self.assertEqual((c.received, c.outstanding, c.status), (4_000_000, 5_000_000, "partial"))
        entry = c.receipts[0]["entry"]
        self.client.post(self.reverse("deal_receipt_reverse", args=[self.d.pk, entry.pk]))
        c = simple.for_deal(self.d)
        self.assertEqual((c.received, c.status), (0, "none"))
        self.assertTrue(c.receipts[0]["reversed"])
        self.assertEqual(LedgerEntry.objects.filter(agreement__deal=self.d).count(), 2)  # original kept + reversal
        # Changing the expected amount updates the same agreement.
        self.client.post(self.reverse("deal_commission", args=[self.d.pk]), {"expected": "95,000.50"})
        self.assertEqual(simple.for_deal(self.d).expected, 9_500_050)
        self.assertEqual(self.d.commission_agreements.count(), 1)

    def test_blank_expected_is_unknown_not_zero(self):
        from commissions import simple

        self.client.post(self.reverse("deal_commission", args=[self.d.pk]), {"expected": ""})
        c = simple.for_deal(self.d)
        self.assertIsNone(c.expected)
        self.assertIsNone(c.outstanding)

    def test_detailed_agreement_is_not_overwritten(self):
        from commissions import simple

        a = CommissionAgreement.objects.create(deal=self.d, title="Detailed", represented_side="buyer",
                                               basis_type="percentage", basis_amount_cents=100_000_000, rate_percent=Decimal("3"))
        CommissionAllocation.objects.create(agreement=a, level="payer", recipient_type="skw", recipient_name="SKW",
                                            method="percent_of_gross", percent=Decimal("100"))
        self.assertFalse(simple.for_deal(self.d).editable)
        self.assertEqual(simple.for_deal(self.d).expected, 3_000_000)
        resp = self.client.post(self.reverse("deal_commission", args=[self.d.pk]), {"expected": "1"}, follow=True)
        self.assertContains(resp, "detailed commission agreement")
        a.refresh_from_db()
        self.assertEqual(a.basis_amount_cents, 100_000_000)

    def test_read_only_cannot_edit(self):
        viewer = self.user("read_only")
        self.client.force_login(viewer)
        resp = self.client.post(self.reverse("deal_commission", args=[self.d.pk]), {"expected": "1"})
        self.assertEqual(resp.status_code, 403)
