"""Deals header distinguishes closing/signing volume from receipt-date cash."""
from datetime import date
from unittest.mock import patch

from django.urls import reverse

from commissions import simple
from commissions.models import CommissionAgreement
from commissions.services import record_entry, reverse_entry
from deals import stats
from deals.services import close_deal
from reports.services import cash_receipts, filters_from_params

from .base import DeskTestCase


class DealHeaderMetricsTests(DeskTestCase):
    def setUp(self):
        self.broker = self.user("broker")
        self.sale = self.deal("Closed sale", transaction_type="sale")
        close_deal(self.sale, self.broker, actual_closing_date=date(2024, 12, 20), total_cents=100_000_000)
        simple.set_expected(self.sale, 9_000_000, self.broker)
        self.agreement = CommissionAgreement.objects.get(deal=self.sale)

    def receipt(self, amount, year, agreement=None):
        return record_entry(agreement or self.agreement, self.broker, entry_type="receipt",
                            amount_cents=amount, entry_date=date(year, 3, 1))

    def test_cash_follows_receipt_year_including_active_deals(self):
        self.receipt(400_000, 2024)
        self.receipt(600_000, 2025)
        active = self.deal("Active sale", transaction_type="sale")
        simple.set_expected(active, 2_000_000, self.broker)
        active_agreement = CommissionAgreement.objects.get(deal=active)
        self.receipt(300_000, 2025, active_agreement)

        prior, current, all_time = stats.totals(2024), stats.totals(2025), stats.totals()
        self.assertEqual((prior.sales, prior.received), (100_000_000, 400_000))
        self.assertEqual((current.sales, current.count, current.received), (0, 0, 900_000))
        self.assertEqual((all_time.sales, all_time.received), (100_000_000, 1_300_000))
        self.assertEqual(current.years, [2025, 2024])

    def test_refunds_and_reversals_follow_their_own_entry_year(self):
        old = self.receipt(500_000, 2024)
        reverse_entry(old, self.broker, date(2025, 1, 15), "Returned")
        self.receipt(800_000, 2025)
        refund = record_entry(self.agreement, self.broker, entry_type="refund", amount_cents=100_000,
                              entry_date=date(2025, 4, 1))
        reverse_entry(refund, self.broker, date(2025, 4, 2), "Refund canceled")
        record_entry(self.agreement, self.broker, entry_type="refund", amount_cents=50_000,
                     entry_date=date(2025, 5, 1))
        self.assertEqual(stats.totals(2024).received, 500_000)
        self.assertEqual(stats.totals(2025).received, 250_000)
        self.assertEqual(stats.totals().received, 750_000)
        self.assertEqual(stats.totals(2025).received, cash_receipts(filters_from_params({"year": 2025}))["total"])

    def test_header_headline_shows_actual_cash_not_expected_commission(self):
        self.receipt(123_400, 2024)
        self.client.force_login(self.broker)
        response = self.client.get(reverse("deal_list"), {"period": 2024})
        hero = response.content.decode().split('<section class="hero-band"', 1)[1].split('</section>', 1)[0]
        self.assertIn("Sales transaction volume", hero)
        self.assertIn("Signed lease rent total", hero)
        self.assertIn("SKW commission received", hero)
        self.assertIn('data-odo="123400"', hero)
        self.assertNotIn('data-odo="9000000"', hero)
        self.assertNotIn("By actual closing year", hero)
        self.assertNotIn("By signed year", hero)
        self.assertNotIn("By receipt year, net of refunds and reversals", hero)
        self.assertNotIn('class="hero-sub"', hero)

    def test_permission_hides_cash_and_receipt_only_years(self):
        self.receipt(123_400, 2023)
        with patch("deals.stats.cash_receipts") as receipts:
            totals = stats.totals(2023, with_commission=False)
        receipts.assert_not_called()
        self.assertEqual((totals.received, totals.commission, totals.years), (0, 0, [2024]))
        self.client.force_login(self.user("read_only"))
        response = self.client.get(reverse("deal_list"), {"period": 2024})
        self.assertNotContains(response, "SKW commission received")
        self.assertNotContains(response, 'href="?period=2023"')
        self.assertNotContains(response, 'data-odo="123400"')
