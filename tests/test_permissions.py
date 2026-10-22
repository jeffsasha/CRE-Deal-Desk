"""Server-side permission enforcement: read-only users cannot edit or see financial
data; coordinators cannot see commissions; client details are restricted."""

from django.urls import reverse

from commissions.models import CommissionAgreement
from crm.models import Contact, Organization
from deals.models import Stage

from .base import DeskTestCase


class ReadOnlyTests(DeskTestCase):
    def setUp(self):
        self.viewer = self.user("read_only")
        self.coord = self.user("coordinator")
        self.broker = self.user("broker")
        self.d = self.deal("Perm deal", actor=self.broker)
        self.agreement = CommissionAgreement.objects.create(deal=self.d, title="Secret commission", represented_side="buyer",
                                                            basis_type="flat", flat_amount_cents=123456)
        self.client.force_login(self.viewer)

    def test_can_view_operational_pages(self):
        for url in [reverse("dashboard"), reverse("deal_list"), reverse("deal_detail", args=[self.d.pk]),
                    reverse("deadline_list"), reverse("property_list"), reverse("report_index")]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_edits_forbidden(self):
        posts = [
            (reverse("deal_create"), {"name": "x", "transaction_type": "sale", "stage": Stage.objects.first().pk}),
            (reverse("deal_edit", args=[self.d.pk]), {"name": "hacked"}),
            (reverse("deal_stage", args=[self.d.pk]), {"stage": "lost", "reason": "x"}),
            (reverse("deal_close", args=[self.d.pk]), {"actual_closing_date": "2026-01-01"}),
            (reverse("deal_term", args=[self.d.pk]), {"key": "purchase_price", "value": "$1"}),
            (reverse("deal_event", args=[self.d.pk]), {"key": "effective_date", "occurred_on": "2026-01-01"}),
            (reverse("property_create"), {"name": "p"}),
            (reverse("deal_key_dates", args=[self.d.pk]), {"effective_date": "2026-01-01"}),
            (reverse("deal_commission", args=[self.d.pk]), {"expected": "1"}),
            (reverse("deal_receipt", args=[self.d.pk]), {"amount": "1", "entry_date": "2026-01-01"}),
            (reverse("issue_create") + f"?deal={self.d.pk}", {"title": "x"}),
            (reverse("deal_sub", args=[self.d.pk, "party"]), {"role": "buyer"}),
        ]
        for url, data in posts:
            self.assertEqual(self.client.post(url, data).status_code, 403, url)
        self.d.refresh_from_db()
        self.assertEqual(self.d.name, "Perm deal")
        self.assertNotEqual(self.d.stage.key, "lost")

    def test_get_create_forms_forbidden(self):
        for url in [reverse("deal_create"), reverse("property_create"), reverse("deal_key_dates", args=[self.d.pk])]:
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_no_financial_access(self):
        for url in [reverse("commission_list"), reverse("ledger_list"), reverse("commission_detail", args=[self.agreement.pk]),
                    reverse("report_detail", args=["receipts"]), reverse("report_detail", args=["designated"]),
                    reverse("report_detail", args=["outstanding"]), reverse("commission_create")]:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        resp = self.client.get(reverse("deal_detail", args=[self.d.pk]) + "?tab=commissions")
        self.assertNotContains(resp, "Secret commission")
        dash = self.client.get(reverse("dashboard"))
        self.assertNotIn("fin", dash.context)
        self.assertNotContains(self.client.get(reverse("report_index")), "Cash received by SKW")

    def test_audit_and_settings_forbidden(self):
        for url in [reverse("audit_log"), reverse("user_list"), reverse("jobs"), reverse("import_list")]:
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_coordinator_edits_but_no_commissions(self):
        self.client.force_login(self.coord)
        self.assertEqual(self.client.get(reverse("commission_list")).status_code, 403)
        resp = self.client.post(reverse("deal_edit", args=[self.d.pk]), {
            "name": "Renamed", "transaction_type": "purchase", "priority": "normal", "time_zone": "America/Chicago",
            "financing_status": "unknown"})
        self.assertEqual(resp.status_code, 302)

    def test_client_contact_details_masked(self):
        org = Organization.objects.create(name="Client Co", is_client=True, phone="555-0000")
        c = Contact.objects.create(first_name="Pat", last_name="Client", organization=org, email="pat@client.invalid", phone="555-1111")
        resp = self.client.get(reverse("contact_detail", args=[c.pk]))
        self.assertNotContains(resp, "pat@client.invalid")
        resp = self.client.get(reverse("contact_list"))
        self.assertNotContains(resp, "pat@client.invalid")
        self.assertEqual(self.client.get(reverse("contact_list") + "?export=csv").status_code, 403)
        self.client.force_login(self.broker)
        self.assertContains(self.client.get(reverse("contact_detail", args=[c.pk])), "pat@client.invalid")

    def test_anonymous_redirected(self):
        self.client.logout()
        resp = self.client.get(reverse("deal_list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp["Location"])
