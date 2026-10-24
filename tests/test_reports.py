"""Reporting totals: consideration counted once, leases separate, dashboard equals
ledger, every total traceable, unknown never zero."""
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from commissions.models import CommissionAgreement, CommissionAllocation, CommissionInstallment, LedgerEntry
from commissions.services import record_entry, reverse_entry
from core import dashboard
from deals.models import Representation
from deals.services import close_deal
from reports import services as r

from .base import DeskTestCase


class VolumeTests(DeskTestCase):
    def setUp(self):
        self.broker = self.user("broker", is_designated_broker=True)
        self.year = timezone.localdate().year
        self.f = r.filters_from_params({"year": self.year})
        self.closing = timezone.localdate() - timedelta(days=10)

    def test_multi_property_counted_once(self):
        p1, p2 = self.prop("Pad A"), self.prop("Pad B")
        deal = self.deal("Portfolio", transaction_type="sale", stage="preparing_to_close", properties=[p1, p2])
        Representation.objects.create(deal=deal, side="seller")
        Representation.objects.create(deal=deal, side="buyer")  # dual representation: still one transaction
        links = list(deal.deal_properties.order_by("id"))
        close_deal(deal, self.broker, actual_closing_date=self.closing, total_cents=310000000,
                   allocations={links[0].pk: 170000000, links[1].pk: 140000000})
        sales = r.closed_sales_volume(self.f)
        self.assertEqual(sales["total"].known, 310000000)
        self.assertEqual(sales["total"].count, 1)
        # Filtering by side does not duplicate it either.
        self.assertEqual(r.closed_sales_volume(r.filters_from_params({"year": self.year, "side": "seller"}))["total"].known, 310000000)

    def test_allocations_must_add_up(self):
        p1, p2 = self.prop("Pad C"), self.prop("Pad D")
        deal = self.deal("Portfolio 2", transaction_type="sale", stage="preparing_to_close", properties=[p1, p2])
        links = list(deal.deal_properties.order_by("id"))
        with self.assertRaises(ValidationError):
            close_deal(deal, self.broker, actual_closing_date=self.closing, total_cents=310000000,
                       allocations={links[0].pk: 170000000, links[1].pk: 150000000})

    def test_future_closing_rejected(self):
        deal = self.deal("Future")
        with self.assertRaises(ValidationError):
            close_deal(deal, self.broker, actual_closing_date=timezone.localdate() + timedelta(days=3), total_cents=100)

    def test_leases_and_business_assets_separate(self):
        sale = self.deal("Sale", transaction_type="sale")
        close_deal(sale, self.broker, actual_closing_date=self.closing, total_cents=100000000)
        lease = self.deal("Lease", transaction_type="lease")
        close_deal(lease, self.broker, actual_closing_date=self.closing, total_cents=50000000)
        biz = self.deal("Biz", transaction_type="business_asset")
        close_deal(biz, self.broker, actual_closing_date=self.closing, total_cents=20000000)
        self.assertEqual(r.closed_sales_volume(self.f)["total"].known, 100000000)
        self.assertEqual(r.executed_leases(self.f)["consideration"].known, 50000000)
        self.assertEqual(r.closed_business_asset_volume(self.f)["total"].known, 20000000)

    def test_unknown_price_not_zero(self):
        deal = self.deal("Unknown price", transaction_type="sale")
        close_deal(deal, self.broker, actual_closing_date=self.closing, total_cents=None)
        total = r.closed_sales_volume(self.f)["total"]
        self.assertEqual(total.known, 0)
        self.assertEqual(total.unknown_count, 1)
        self.assertIn("1 unknown", total.display())

    def test_period_uses_actual_closing_date(self):
        deal = self.deal("Last year", transaction_type="sale")
        close_deal(deal, self.broker, actual_closing_date=date(self.year - 1, 12, 31), total_cents=500)
        self.assertEqual(r.closed_sales_volume(self.f)["total"].count, 0)
        self.assertEqual(r.closed_sales_volume(r.filters_from_params({"year": self.year - 1}))["total"].known, 500)

    def test_proposed_or_lost_deals_not_volume(self):
        self.deal("LOI deal", stage="loi", transaction_type="sale")
        self.deal("Lost deal", stage="lost", transaction_type="sale")
        self.assertEqual(r.closed_sales_volume(self.f)["total"].count, 0)


class LedgerReconciliationTests(DeskTestCase):
    def test_dashboard_matches_ledger(self):
        broker = self.user("broker", is_designated_broker=True)
        today = timezone.localdate()
        deal = self.deal("Commission deal", stage="closed")
        a = CommissionAgreement.objects.create(deal=deal, title="A", represented_side="buyer", basis_type="flat",
                                               flat_amount_cents=1000000)
        CommissionAllocation.objects.create(agreement=a, level="payer", recipient_type="skw", recipient_name="SKW",
                                            method="flat", amount_cents=1000000)
        db = CommissionAllocation.objects.create(agreement=a, level="internal", recipient_type="designated_broker",
                                                 recipient_name="DB", recipient_user=broker, method="percent_of_skw", percent=Decimal("60"))
        CommissionInstallment.objects.create(agreement=a, label="x", amount_cents=1000000, earned_status="earned", earned_on=today)
        e1 = record_entry(a, broker, entry_type="receipt", amount_cents=400000, entry_date=today)
        record_entry(a, broker, entry_type="receipt", amount_cents=350000, entry_date=today)
        reverse_entry(e1, broker, today, "bounced")
        record_entry(a, broker, entry_type="distribution", amount_cents=210000, entry_date=today, allocation=db)
        data = dashboard.build(broker, {})
        ledger_receipts = sum(e.amount_cents for e in LedgerEntry.objects.filter(entry_type="receipt")) - sum(
            e.amount_cents for e in LedgerEntry.objects.filter(entry_type="reversal", reverses__entry_type="receipt"))
        self.assertEqual(data["fin"]["received_year"], ledger_receipts)
        self.assertEqual(data["fin"]["received_year"], 350000)
        f = r.filters_from_params({"year": today.year})
        self.assertEqual(r.designated_broker_receipts(f)["total"], 210000)
        self.assertEqual(r.outstanding_balances(f)["receivable"].known, 650000)
        self.assertEqual(r.earned_commissions(f)["total"].known, 1000000)
        # The drill-down page shows the same total and its source entries.
        self.client.force_login(broker)
        resp = self.client.get(reverse("report_detail", args=["receipts"]) + f"?year={today.year}")
        self.assertContains(resp, "$3,500.00")
        self.assertEqual(len(resp.context["result"]["rows"]), 3)  # two receipts and one reversal


class ClosedTotalsTests(DeskTestCase):
    """Deals page header: sales and lease consideration kept apart, each deal once,
    actual commission received in the period, regardless of closing year."""

    def test_totals_by_year(self):
        from commissions import simple
        from deals import stats

        broker = self.user("broker")
        sale = self.deal("Sale 2025", stage="under_contract", transaction_type="sale")
        close_deal(sale, broker, actual_closing_date=date(2025, 8, 19), total_cents=400_000_000)
        simple.set_expected(sale, 16_000_000, broker)
        simple.record_receipt(sale, 16_000_000, date(2025, 8, 19), broker)
        lease = self.deal("Lease 2025", stage="under_contract", transaction_type="lease")
        close_deal(lease, broker, actual_closing_date=date(2025, 9, 16), total_cents=15_459_100)
        simple.set_expected(lease, 309_182, broker)
        unknown = self.deal("Unknown price 2026", stage="under_contract", transaction_type="sale")
        close_deal(unknown, broker, actual_closing_date=date(2026, 1, 5), total_cents=None)
        self.deal("Open deal", stage="under_contract", transaction_type="sale")

        t = stats.totals(2025)
        self.assertEqual((t.count, t.sales, t.leases), (2, 400_000_000, 15_459_100))
        self.assertEqual((t.commission, t.received, t.commission_unknown), (16_309_182, 16_000_000, 0))
        t = stats.totals(None)
        self.assertEqual((t.count, t.sales, t.sales_unknown, t.commission_unknown), (3, 400_000_000, 1, 1))
        self.assertEqual(t.years, [2026, 2025])

        self.client.force_login(broker)
        resp = self.client.get(reverse("deal_list") + "?period=2025")
        self.assertContains(resp, 'data-odo="400000000"')
        self.assertContains(resp, 'data-odo="16000000"')
        resp = self.client.get(reverse("deal_detail", args=[sale.pk]))
        self.assertContains(resp, "SKW commission earned")
        self.assertContains(resp, "$4,000,000")
