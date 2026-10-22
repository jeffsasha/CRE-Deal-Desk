"""End-to-end: load the demo sample data and check the main flows in the running
application (HTTP), the way a user would see them: key-date timelines on the
dashboard, SKW commission per deal, history kept on the property, read-only limits,
and every main page rendering in English and Chinese."""
from django.urls import reverse
from django.utils import timezone

from commissions import simple
from commissions.ledger import effective_entries
from commissions.models import LedgerEntry
from core import dashboard
from core.models import User
from deals.models import Deal
from properties.models import Property

from .base import DeskTestCase


class AcceptanceFlows(DeskTestCase):
    @classmethod
    def setUpTestData(cls):
        from demo.seed import seed

        cls.today = timezone.localdate()
        seed(log=lambda m: None)

    def setUp(self):
        self.broker = User.objects.get(username="demo-broker")
        self.viewer = User.objects.get(username="demo-viewer")
        self.client.force_login(self.broker)
        self.gessner = Deal.objects.get(name="SAMPLE Gessner office purchase")

    def test_property_keeps_terminated_and_closed_history(self):
        p = Property.objects.get(name="SAMPLE 1200 Example Industrial Pkwy")
        stages = sorted(link.deal.stage.key for link in p.deal_links.all())
        self.assertEqual(stages, ["closed", "terminated"])
        resp = self.client.get(reverse("property_detail", args=[p.pk]))
        self.assertContains(resp, "SAMPLE 2025 acquisition attempt")
        self.assertContains(resp, "SAMPLE Example Industrial sale")

    def test_dashboard_timelines(self):
        rows = {r["deal"].name: r for r in dashboard.deal_progress(with_commission=True)["rows"]}
        self.assertNotIn("SAMPLE Example Industrial sale", rows)  # closed deals are not open
        g = rows["SAMPLE Gessner office purchase"]["tl"]
        self.assertEqual([p["label"] for p in g["points"]], ["Feasibility Period ends", "Closing Date"])
        self.assertTrue(g["complete"])
        self.assertTrue(0 < g["today_pos"] < 100)
        self.assertEqual(g["next"]["label"], "Feasibility Period ends")
        lease = rows["SAMPLE Kirby dental suite lease"]["tl"]
        self.assertEqual([p["label"] for p in lease["points"]], ["Commencement Date"])
        harbor = rows["SAMPLE Harbor Cafe business sale"]
        self.assertIsNone(harbor["tl"]["start"])
        self.assertIsNone(harbor["skw"].expected)
        names = list(rows)
        self.assertEqual(names[-1], "SAMPLE Bayou warehouse purchase")  # on hold sorts last
        resp = self.client.get(reverse("dashboard"))
        self.assertContains(resp, "Feasibility Period ends")
        self.assertContains(resp, "Key dates not entered")
        self.assertNotContains(resp, "Upload")

    def test_passed_feasibility_is_not_overdue(self):
        westpark = Deal.objects.get(name="SAMPLE Westpark retail center sale")
        feas = westpark.deadlines.get(template_key="feasibility_expiration")
        self.assertLess(feas.current_date, self.today)
        self.assertFalse(feas.is_overdue)
        data = dashboard.build(self.broker, {})
        self.assertEqual(data["deadlines"]["overdue"][0], 0)

    def test_dashboard_commission_reconciles(self):
        data = dashboard.build(self.broker, {})
        open_deals = [r["deal"] for r in data["progress"]["rows"]]
        expected = [simple.for_deal(d).expected for d in open_deals]
        self.assertEqual(data["fin"]["expected"], sum(x for x in expected if x is not None))
        self.assertEqual(data["fin"]["expected_unknown"], 3)  # Harbor Cafe, Memorial lease, medical search
        receipts = sum(c for e, kind, c, _a in effective_entries(LedgerEntry.objects.all())
                       if kind == "receipt" and e.entry_date.year == self.today.year)
        self.assertEqual(data["fin"]["received_year"], receipts)

    def test_closed_deal_paid_in_full(self):
        d = Deal.objects.get(name="SAMPLE Example Industrial sale")
        c = simple.for_deal(d)
        self.assertEqual((c.expected, c.received, c.status), (9_600_000, 9_600_000, "full"))
        resp = self.client.get(reverse("commission_list") + "?show=closed")
        self.assertContains(resp, "SAMPLE Example Industrial sale")
        self.assertContains(resp, "Received in full")
        self.assertNotContains(resp, "Designated broker")

    def test_read_only_restricted(self):
        self.client.force_login(self.viewer)
        d = self.gessner
        self.assertEqual(self.client.post(reverse("deal_edit", args=[d.pk]), {"name": "x"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("deal_key_dates", args=[d.pk]), {}).status_code, 403)
        self.assertEqual(self.client.get(reverse("commission_list")).status_code, 403)
        resp = self.client.get(reverse("deal_detail", args=[d.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "SKW commission")
        self.assertNotIn("fin", dashboard.build(self.viewer, {}))

    def _pages(self):
        d = self.gessner
        p = Property.objects.get(name="SAMPLE 1200 Example Industrial Pkwy")
        urls = [reverse(n) for n in ["dashboard", "property_list", "deal_list", "deal_board", "deposit_list", "deadline_list",
                                     "deadline_calendar", "checklist_list", "contact_list", "commission_list", "ledger_list",
                                     "report_index", "settings_index", "notifications", "issue_list", "reminder_log",
                                     "audit_log", "archived", "requirements", "template_list", "holiday_list", "stage_list",
                                     "import_list", "deal_create"]]
        urls += [reverse("deal_detail", args=[d.pk]) + f"?tab={t}" for t in ["overview", "parties", "checklist", "activity", "closing"]]
        urls += [reverse("property_detail", args=[p.pk]) + f"?tab={t}" for t in ["overview", "facts", "pricing", "parcels"]]
        urls += [reverse("deal_edit", args=[d.pk]), reverse("deal_key_dates", args=[d.pk]),
                 reverse("deal_key_dates", args=[Deal.objects.get(name="SAMPLE Kirby dental suite lease").pk]),
                 d.deadlines.first().get_absolute_url(),
                 reverse("commission_detail", args=[d.commission_agreements.first().pk]),
                 reverse("search") + "?q=Sample", reverse("contact_list") + "?tab=companies"]
        for m in ["sales", "leases", "business", "pipeline", "unknown_commission", "expected", "earned", "receipts",
                  "designated", "distributions", "outstanding"]:
            urls.append(reverse("report_detail", args=[m]))
        return urls

    def test_all_main_pages_render(self):
        for u in self._pages():
            self.assertEqual(self.client.get(u).status_code, 200, u)

    def test_all_main_pages_render_in_chinese(self):
        self.client.post(reverse("set_language"), {"language": "zh-hans", "next": "/"})
        for u in self._pages():
            self.assertEqual(self.client.get(u).status_code, 200, u)
        d = self.gessner
        self.assertContains(self.client.get(reverse("dashboard")), "Feasibility Period 结束")
        self.assertContains(self.client.get(reverse("deal_detail", args=[d.pk])), "未收余额")
        self.assertContains(self.client.get(reverse("deal_key_dates", args=[d.pk])), "关键日期")
        self.assertContains(self.client.get(reverse("deal_edit", args=[d.pk])), "融资状态")  # form label
        self.assertContains(self.client.get(reverse("deal_detail", args=[d.pk])), "尽职调查")  # stage name


class ListingTests(DeskTestCase):
    def setUp(self):
        from datetime import date

        from deals.models import Representation

        self.date = date
        self.broker = self.user("broker")
        self.client.force_login(self.broker)
        self.listing = self.deal("Listing deal", stage="listed", transaction_type="sale", actor=self.broker)
        Representation.objects.create(deal=self.listing, side="seller", is_skw=True)
        self.buyer = self.deal("Buyer search", stage="touring", transaction_type="purchase", actor=self.broker)
        Representation.objects.create(deal=self.buyer, side="buyer", is_skw=True)
        self.contract = self.deal("Contract deal", stage="under_contract", transaction_type="sale", actor=self.broker)
        Representation.objects.create(deal=self.contract, side="seller", is_skw=True)

    def test_sections(self):
        p = dashboard.deal_progress()
        self.assertEqual([r["deal"].name for r in p["contract"]], ["Contract deal"])
        self.assertEqual([r["deal"].name for r in p["listings"]], ["Listing deal"])
        self.assertEqual([r["deal"].name for r in p["searches"]], ["Buyer search"])
        html = self.client.get(reverse("dashboard")).content.decode()
        self.assertLess(html.index("Under Contract"), html.index("Listings"))  # listings sit below

    def test_listing_form_creates_expiration_deadline(self):
        url = reverse("deal_listing", args=[self.listing.pk])
        resp = self.client.post(url, {"listing_date": "2026-03-01", "listing_expires_on": "2026-02-01",
                                      "asking_price": "", "asking_price_unit": "usd_total"})
        self.assertContains(resp, "cannot expire before it was listed")
        self.client.post(url, {"listing_date": "2026-03-01", "listing_expires_on": "2026-09-01",
                               "asking_price": "2,450,000", "asking_price_unit": "usd_total"})
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.asking_price_cents, 245_000_000)
        dl = self.listing.deadlines.get(template_key="listing_expiration")
        self.assertEqual((dl.current_date, dl.state), (self.date(2026, 9, 1), "open"))
        self.assertTrue(self.listing.price_events.filter(kind="asking", amount_cents=245_000_000).exists())
        # Moving the expiration recomputes the same deadline; clearing it cancels (keeps) it.
        self.client.post(url, {"listing_date": "2026-03-01", "listing_expires_on": "2026-12-01",
                               "asking_price": "2,450,000", "asking_price_unit": "usd_total"})
        dl.refresh_from_db()
        self.assertEqual(dl.current_date, self.date(2026, 12, 1))
        self.client.post(url, {"listing_date": "2026-03-01", "listing_expires_on": "",
                               "asking_price": "28.50", "asking_price_unit": "usd_sf_year"})
        dl.refresh_from_db()
        self.assertEqual(dl.state, "cancelled")
        from deals import listing

        self.listing.refresh_from_db()
        self.assertEqual(listing.asking_display(self.listing), "$28.50/SF/yr")

    def test_going_under_contract_moves_section(self):
        from deals.models import Stage

        self.listing.stage = Stage.objects.get(key="under_contract")
        self.listing.save()
        p = dashboard.deal_progress()
        self.assertIn("Listing deal", [r["deal"].name for r in p["contract"]])
        self.assertNotIn("Listing deal", [r["deal"].name for r in p["listings"]])

    def test_dates_survive_chinese_interface(self):
        """Date pickers need ISO values in every language, or saving clears the date."""
        from deals import keydates

        self.client.post(reverse("set_language"), {"language": "zh-hans", "next": "/"})
        self.listing.listing_date = self.date(2026, 3, 1)
        self.listing.save()
        keydates.save(self.contract, {"effective_date": self.date(2026, 3, 4), "feasibility_days": 30,
                                      "closing_mode": "days", "closing_days": 60}, self.broker)
        self.assertContains(self.client.get(reverse("deal_listing", args=[self.listing.pk])), 'value="2026-03-01"')
        self.assertContains(self.client.get(reverse("deal_key_dates", args=[self.contract.pk])), 'value="2026-03-04"')
        self.assertContains(self.client.get(reverse("deal_close", args=[self.contract.pk])), 'type="date"')
