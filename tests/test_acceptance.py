"""End-to-end: load the demo sample data and check every acceptance flow in the
running application (HTTP), the way a user would see it."""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from commissions.ledger import summarize
from core import dashboard
from core.models import User
from deadlines.models import Reminder
from deals.models import Deal
from documents.models import Amendment, ExtractionRun
from imports.models import ImportRow
from properties.models import Property
from reports import services as r

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

    def test_01_property_keeps_terminated_and_closed_history(self):
        p = Property.objects.get(name="SAMPLE 1200 Example Industrial Pkwy")
        stages = sorted(link.deal.stage.key for link in p.deal_links.all())
        self.assertEqual(stages, ["closed", "terminated"])
        resp = self.client.get(reverse("property_detail", args=[p.pk]))
        self.assertContains(resp, "2025 acquisition attempt")
        self.assertContains(resp, "2026 sale to Sample Holdings Trust")
        self.assertContains(resp, "roof findings")

    def test_02_import_known_price_unknown_commission(self):
        d = Deal.objects.get(name__startswith="SAMPLE Historical sale")
        self.assertEqual(d.actual_closing_price_cents, 197500000)
        self.assertFalse(d.commission_agreements.exists())
        resp = self.client.get(reverse("deal_detail", args=[d.pk]) + "?tab=commissions")
        self.assertContains(resp, "unknown")
        self.assertTrue(ImportRow.objects.filter(status="invalid", errors__icontains="closing date").exists())
        self.assertEqual(Deal.objects.get(name__startswith="SAMPLE Proposal").stage.key, "loi")

    def test_03_scanned_contract_review_with_pages(self):
        run = ExtractionRun.objects.filter(version__document__title__icontains="Westpark").first()
        if run.status != "succeeded":
            self.skipTest("No OCR engine on this machine; manual-entry fallback was used")
        resp = self.client.get(reverse("extraction_review", args=[run.pk]))
        self.assertContains(resp, "Page 1")
        self.assertContains(resp, "Show in document")
        self.assertTrue(run.fields.filter(page__isnull=False, quote_verified=True).exists())

    def test_04_ambiguous_effective_date_no_invented_deadlines(self):
        d = Deal.objects.get(name="SAMPLE Westpark retail center acquisition")
        self.assertIsNone(d.effective_date)
        self.assertTrue(d.deadlines.exists())
        self.assertFalse(d.deadlines.filter(current_date__isnull=False).exists())
        self.assertTrue(all(x.computation == "awaiting_trigger" for x in d.deadlines.all()))

    def test_05_receipt_triggered_deadline(self):
        d = Deal.objects.get(name="SAMPLE Gessner warehouse acquisition")
        obj = d.deadlines.get(template_key="title_survey_objection")
        self.assertEqual(obj.current_date, self.today - timedelta(days=3) + timedelta(days=10))
        first = obj.revisions.order_by("revision").first()
        self.assertEqual((first.previous_computation, first.new_computation), ("awaiting_trigger", "computed"))

    def test_06_and_07_amendments(self):
        d = Deal.objects.get(name="SAMPLE Gessner warehouse acquisition")
        from demo.samples import offsets

        o = offsets(self.today)
        self.assertEqual(d.contractual_closing_date, o["d_amended_closing"])
        self.assertEqual(Amendment.objects.get(deal=d, status="proposed").version.execution_status, "draft")
        self.assertEqual(Amendment.objects.get(deal=d, status="applied").deal, d)
        closing = d.deadlines.get(template_key="closing_fixed")
        self.assertEqual(closing.original_date, o["d_closing"])
        self.assertTrue(d.terms.filter(key="closing_date", status="superseded").exists())
        self.assertTrue(Reminder.objects.filter(deadline=closing, status="cancelled").exists())
        resp = self.client.get(reverse("deal_detail", args=[d.pk]))
        self.assertContains(resp, "Amendment pending")

    def test_08_survey_received_under_review(self):
        d = Deal.objects.get(name="SAMPLE Gessner warehouse acquisition")
        self.assertEqual(d.checklist_items.get(title="Survey received").status, "received")
        self.assertEqual(d.checklist_items.get(title__startswith="Survey reviewed").status, "under_review")

    def test_09_title_and_insurance_separate(self):
        d = Deal.objects.get(name="SAMPLE Gessner warehouse acquisition")
        titles = set(d.checklist_items.values_list("title", flat=True))
        self.assertTrue({"Title commitment received", "Final owner's title insurance policy received",
                         "Property insurance binder issued"} <= titles)

    def test_10_hvac_credit_not_a_price_change(self):
        d = Deal.objects.get(name="SAMPLE Gessner warehouse acquisition")
        self.assertEqual(d.executed_contract_price_cents, 285000000)
        self.assertTrue(d.issues.filter(requested_credit_cents=4500000).exists())

    def test_11_partial_receipts_and_designated_broker(self):
        d = Deal.objects.get(name__contains="2026 sale to Sample Holdings Trust")
        s = summarize(d.commission_agreements.get())
        self.assertEqual(s.received, 3675000)
        self.assertEqual(s.designated_broker_paid, 1400000)
        self.assertEqual(s.designated_broker_unpaid, 1172500)
        resp = self.client.get(reverse("commission_detail", args=[d.commission_agreements.get().pk]))
        self.assertContains(resp, "$14,000.00")

    def test_12_dashboard_reconciles_with_ledger(self):
        data = dashboard.build(self.broker, {"period": "year"})
        f = r.filters_from_params({"year": self.today.year})
        self.assertEqual(data["fin"]["receipts"]["total"], r.cash_receipts(f)["total"])
        resp = self.client.get(reverse("report_detail", args=["receipts"]) + f"?year={self.today.year}")
        self.assertEqual(resp.context["result"]["total"], data["fin"]["receipts"]["total"])
        self.assertEqual(sum(row["cents"] for row in resp.context["result"]["rows"]), data["fin"]["receipts"]["total"])

    def test_13_multi_property_not_double_counted(self):
        f = r.filters_from_params({"year": self.today.year})
        sales = r.closed_sales_volume(f)
        portfolio = Deal.objects.get(name="SAMPLE two-pad portfolio sale")
        self.assertIn(portfolio, sales["deals"])
        self.assertEqual(sales["total"].known, 245000000 + 310000000)

    def test_14_read_only_restricted(self):
        self.client.force_login(self.viewer)
        d = Deal.objects.get(name="SAMPLE Gessner warehouse acquisition")
        self.assertEqual(self.client.post(reverse("deal_edit", args=[d.pk]), {"name": "x"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("commission_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("deal_detail", args=[d.pk])).status_code, 200)

    def test_15_failures_recovered(self):
        failed = ExtractionRun.objects.get(version__document__title__icontains="unreadable")
        self.assertEqual(failed.status, "failed")
        resp = self.client.get(reverse("review_queue") + "?failed=1")
        self.assertContains(resp, "Enter manually")
        self.assertTrue(Reminder.objects.filter(status="failed", channel="email").exists())
        resp = self.client.get(reverse("reminder_log"))
        self.assertContains(resp, "failed to deliver")

    def test_all_main_pages_render(self):
        d = Deal.objects.get(name="SAMPLE Gessner warehouse acquisition")
        urls = [reverse(n) for n in ["dashboard", "property_list", "deal_list", "deal_board", "deposit_list", "deadline_list",
                                     "deadline_calendar", "checklist_list", "document_list", "review_queue", "contact_list",
                                     "commission_list", "ledger_list", "report_index", "settings_index", "notifications",
                                     "issue_list", "reminder_log", "audit_log", "archived", "requirements", "template_list",
                                     "holiday_list", "stage_list", "import_list"]]
        urls += [reverse("deal_detail", args=[d.pk]) + f"?tab={t}" for t in
                 ["overview", "parties", "contract", "checklist", "documents", "issues", "activity", "commissions", "closing"]]
        urls += [x.get_absolute_url() for x in d.deadlines.all()[:2]] + [a.get_absolute_url() for a in d.amendments.all()]
        urls += [reverse("search") + "?q=Sample", reverse("contact_list") + "?tab=companies"]
        for m in ["sales", "leases", "business", "pipeline", "unknown_commission", "expected", "earned", "receipts",
                  "designated", "distributions", "outstanding"]:
            urls.append(reverse("report_detail", args=[m]))
        for u in urls:
            self.assertEqual(self.client.get(u).status_code, 200, u)

    def test_dashboard_deal_progress(self):
        rows = dashboard.deal_progress()["rows"]
        by_name = {r["deal"].name: r for r in rows}
        gessner = by_name["SAMPLE Gessner warehouse acquisition"]
        self.assertEqual(gessner["deal"].stage.key, "due_diligence")
        self.assertEqual([s["state"] for s in gessner["steps"]].index("current"), gessner["stage_no"] - 1)
        self.assertEqual(sum(1 for s in gessner["steps"] if s["state"] == "done"), gessner["stage_no"] - 1)
        self.assertNotIn("SAMPLE two-pad portfolio sale", by_name)  # closed deals are not "open"
        leases = dashboard.deal_progress("lease")["rows"]
        self.assertTrue(all(r["deal"].is_lease for r in leases))
        resp = self.client.get(reverse("dashboard"))
        self.assertContains(resp, 'role="progressbar"')
        self.assertContains(resp, "step 7 of 9")
