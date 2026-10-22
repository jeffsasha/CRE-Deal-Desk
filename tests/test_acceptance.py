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
        self.assertEqual(data["fin"]["expected_unknown"], 1)
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
