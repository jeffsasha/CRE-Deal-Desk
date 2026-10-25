from datetime import date

from django.urls import reverse

from .base import DeskTestCase


class SalaryTests(DeskTestCase):
    def setUp(self):
        self.owner = self.user("admin")
        self.client.force_login(self.owner)

    def record(self, owner=None, **changes):
        from payroll.models import Paycheck
        data = {"pay_month": date(2025, 12, 1), "paid_on": date(2026, 1, 15),
                "net_pay_cents": 123456, "employer": "Test Employer", "check_number": "TEST-1"}
        data.update(changes)
        return Paycheck.objects.create(owner=owner or self.owner, **data)

    def payload(self, **changes):
        data = {"pay_month": "2025-12", "paid_on": "2026-01-15", "net_pay": "1,234.56",
                "hours": "160.50", "employer": "Test Employer", "check_number": "TEST-1"}
        data.update(changes)
        return data

    def test_salary_sidebar_entry(self):
        self.assertContains(self.client.get(reverse("dashboard")), 'href="/salary/" data-workspace-nav')

    def test_new_salary_uses_existing_card_editor(self):
        response = self.client.get("/salary/new/?editor=1")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-editor-page")
        self.assertContains(response, 'name="net_pay"')
        self.assertNotContains(response, 'id="edit-dialog"')

    def test_values_are_exact_and_owned_by_current_user(self):
        from payroll.models import Paycheck
        other = self.user("broker")
        response = self.client.post(reverse("salary_create") + "?editor=1", self.payload(owner=other.pk))
        self.assertEqual(response.status_code, 302)
        row = Paycheck.objects.get()
        self.assertEqual(row.owner, self.owner)
        self.assertEqual(row.pay_month, date(2025, 12, 1))
        self.assertEqual(row.net_pay_cents, 123456)
        self.assertEqual(str(row.hours), "160.50")
        page = self.client.get(response.url)
        self.assertContains(page, "$1,234.56")

    def test_chart_groups_by_pay_period_and_missing_months_are_unknown(self):
        self.record(net_pay_cents=100001)
        self.record(net_pay_cents=200002, check_number="TEST-2")
        self.record(pay_month=date(2026, 1, 1), net_pay_cents=400004, check_number="TEST-3")
        response = self.client.get(reverse("salary_list"), {"year": "2025"})
        self.assertEqual(response.context["year_total"], 300003)
        self.assertEqual(response.context["all_total"], 700007)
        months = response.context["months"]
        self.assertEqual(len(months), 12)
        self.assertIsNone(months[0]["total"])
        self.assertEqual(months[11]["total"], 300003)
        self.assertEqual(response.context["recorded_months"], 1)

    def test_private_records_are_isolated_even_from_other_administrators(self):
        other = self.user("admin")
        hidden = self.record(owner=other, check_number="PRIVATE-CHECK")
        self.record(check_number="OWN-CHECK")
        response = self.client.get(reverse("salary_list"), {"year": "2025"})
        self.assertContains(response, "OWN-CHECK")
        self.assertNotContains(response, "PRIVATE-CHECK")
        self.assertEqual(response.context["all_total"], 123456)
        for name in ("salary_edit", "salary_archive"):
            url = reverse(name, args=[hidden.pk])
            self.assertEqual(self.client.post(url, self.payload()).status_code, 404)
        self.assertEqual(self.client.get(reverse("salary_edit", args=[hidden.pk])).status_code, 404)

    def test_duplicate_check_and_invalid_amount_stay_in_dialog(self):
        from payroll.models import Paycheck
        self.record()
        for payload in (self.payload(), self.payload(check_number="OTHER", net_pay="-1"),
                        self.payload(check_number="OTHER", net_pay="letters"), self.payload(check_number="OTHER", pay_month="2025-13")):
            response = self.client.post(reverse("salary_create") + "?editor=1", payload)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "data-editor-page")
            self.assertTrue(response.context["form"].errors)
        self.assertEqual(Paycheck.objects.count(), 1)

    def test_edit_recalculates_chart_and_archive_can_be_restored(self):
        row = self.record()
        response = self.client.post(reverse("salary_edit", args=[row.pk]) + "?editor=1", self.payload(net_pay="2,345.67"))
        self.assertEqual(response.status_code, 302)
        row.refresh_from_db()
        self.assertEqual(row.net_pay_cents, 234567)
        archive = reverse("salary_archive", args=[row.pk])
        self.assertEqual(self.client.get(archive).status_code, 405)
        self.client.post(archive, {"action": "archive"})
        self.assertEqual(self.client.get(reverse("salary_list")).context["all_total"], 0)
        self.client.post(archive, {"action": "restore"})
        self.assertEqual(self.client.get(reverse("salary_list")).context["all_total"], 234567)

    def test_salary_permissions_and_partial_navigation(self):
        response = self.client.get(reverse("salary_list"), HTTP_X_WORKSPACE_NAVIGATION="1")
        self.assertContains(response, 'data-workspace-page="salary_list"')
        self.assertNotContains(response, '<aside class="sidebar">')
        for role in ("coordinator", "read_only"):
            self.client.force_login(self.user(role))
            self.assertEqual(self.client.get(reverse("salary_list")).status_code, 403)
            self.assertEqual(self.client.post(reverse("salary_create"), self.payload()).status_code, 403)
            self.assertNotContains(self.client.get(reverse("dashboard")), 'href="/salary/"')
