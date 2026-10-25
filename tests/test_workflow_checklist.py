from django.test import Client
from django.urls import reverse
from django.utils.translation import override

from checklists.models import ChecklistItem
from checklists.workflow import build
from deadlines.models import Deadline
from deals.models import Representation, TRANSACTION_TYPES
from .base import DeskTestCase


class WorkflowChecklistTests(DeskTestCase):
    def setUp(self):
        self.broker = self.user("broker")
        self.client.force_login(self.broker)
        self.record = self.deal(actor=self.broker)
        self.rep = Representation.objects.create(deal=self.record, side="buyer", is_skw=True)

    def rows(self, panel=None):
        return [row for stage in (panel or build(self.record, self.broker))["stages"] for row in stage["items"]]

    def post(self, key, state):
        return self.client.post(reverse("workflow_checklist_update", args=[self.record.pk, key]), {"state": state})

    def test_checklist_unfolds_inside_key_dates_card(self):
        response = self.client.get(self.record.get_absolute_url())
        self.assertContains(response, 'class="card key-dates-card"')
        html = response.content.decode()
        dates_card = html.split('class="card key-dates-card"', 1)[1].split('class="card commission-card"', 1)[0]
        self.assertIn('data-workflow-toggle', dates_card)
        self.assertIn('aria-controls="workflow-checklist"', dates_card)
        self.assertIn('data-workflow-panel', dates_card)
        self.assertIn('data-workflow-item', dates_card)
        self.assertNotContains(response, 'deal-workspace')
        self.assertNotContains(response, 'Add another date')
        self.assertContains(response, 'data-dot-grid')
        self.assertContains(response, 'class="neon-tube"')

    def test_custom_deadline_editor_is_removed_without_deleting_dates(self):
        deadline = Deadline.objects.create(deal=self.record, name="Existing date", rule_type="fixed")
        for path in [f"/deadlines/new/?deal={self.record.pk}", f"/deadlines/{deadline.pk}/edit/"]:
            self.assertEqual(self.client.get(path).status_code, 404)
            self.assertEqual(self.client.post(path, {"name": "Changed"}).status_code, 404)
        deadline.refresh_from_db()
        self.assertEqual(deadline.name, "Existing date")

    def test_each_type_renders_checkboxes_without_na_controls(self):
        for kind, _label in TRANSACTION_TYPES:
            self.record.transaction_type = kind
            self.record.save(update_fields=["transaction_type"])
            with self.subTest(kind=kind):
                response = self.client.get(self.record.get_absolute_url())
                self.assertContains(response, 'data-workflow-item')
                self.assertNotContains(response, 'data-workflow-na')
                self.assertNotContains(response, 'workflow-optional')
                self.assertNotContains(response, 'Mark optional tasks N/A')

    def test_types_omit_unrelated_tasks_and_known_cash_financing(self):
        self.record.transaction_type = 'land_purchase'
        land_titles = ' '.join(row['title'] for row in self.rows())
        self.assertNotIn('rent roll', land_titles)
        self.assertNotIn('Property inspection', land_titles)
        self.assertIn('Utilities / Access', land_titles)
        self.record.transaction_type = 'business_asset'
        self.assertFalse(any('consideration' in row['key'] for row in self.rows()))
        self.record.transaction_type = 'lease_renewal'
        renewal_titles = ' '.join(row['title'] for row in self.rows())
        self.assertNotIn('CO applicability', renewal_titles)
        self.assertNotIn('Pro-rata', renewal_titles)
        self.record.transaction_type = 'purchase'
        self.record.financing_status = 'not_applicable'
        self.assertFalse(any(row['key'].endswith('-financing') for row in self.rows()))

    def test_previously_skipped_tasks_stay_out_of_the_simple_list(self):
        key = 'purchase-buyer-consideration'
        self.post(key, 'na')
        self.assertFalse(any(row['key'] == key for row in self.rows()))
        self.assertEqual(self.record.checklist_items.get(workflow_key=key).status, 'not_applicable')

    def test_type_and_side_select_the_correct_tasks_without_writing(self):
        for kind, _label in TRANSACTION_TYPES:
            with self.subTest(kind=kind):
                self.record.transaction_type = kind
                panel = build(self.record, self.broker)
                rows = self.rows(panel)
                self.assertTrue(rows)
                self.assertEqual(len(rows), len({row["key"] for row in rows}))
                self.assertTrue(all(row["key"].startswith(kind.replace("_", "-") + "-") for row in rows))
                titles = " ".join(row["title"] for row in rows)
                if kind.startswith("lease"):
                    self.assertNotIn("Title Commitment", titles)
                    self.assertNotIn("Earnest Money", titles)
                if kind == "lease_renewal":
                    self.assertIn("Renewal", titles)
                    self.assertNotIn("First month's rent paid", titles)
                if kind == "lease_assignment":
                    self.assertIn("Landlord consent", titles)
                if kind.startswith("land_"):
                    self.assertIn("Utilities / Access", titles)
        self.assertEqual(self.record.checklist_items.count(), 0)

    def test_tenant_landlord_both_and_unknown_wording(self):
        self.record.transaction_type = "lease"
        for side, expected in [("tenant", "submitted"), ("landlord", "received and reviewed")]:
            self.rep.side = side
            self.rep.save()
            descriptions = " ".join(row["description"] for row in self.rows())
            titles = " ".join(row["title"] for row in self.rows())
            self.assertIn("P&L / financial information " + expected, descriptions)
            self.assertIn("Pro-rata rent", titles)
            self.assertIn("CO", titles)
        Representation.objects.create(deal=self.record, side="tenant", is_skw=True)
        self.assertEqual(len(self.rows()), len({row["key"] for row in self.rows()}))
        self.record.representations.all().delete()
        self.assertEqual(build(self.record, self.broker)["role"], "unknown")

    def test_sale_payments_have_no_receipt_tasks(self):
        titles = " ".join(row["title"] for row in self.rows())
        self.assertIn("EM", titles)
        self.assertIn("Independent Consideration", titles)
        self.assertNotIn("receipt", titles.lower())

    def test_autosave_persists_is_idempotent_and_keeps_history(self):
        key = "purchase-buyer-em"
        self.assertEqual(self.post(key, "done").status_code, 200)
        item = self.record.checklist_items.get(workflow_key=key)
        self.assertEqual(item.status, "approved")
        self.assertIsNotNone(item.approved_on)
        self.assertEqual(self.post(key, "done").status_code, 200)
        self.assertEqual(self.record.checklist_items.count(), 1)
        self.assertEqual(item.history.count(), 1)
        self.assertTrue(next(row for row in self.rows() if row["key"] == key)["done"])
        self.assertEqual(self.post(key, "todo").status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.status, "not_started")
        self.assertIsNone(item.approved_on)
        self.assertEqual(item.history.count(), 2)

    def test_not_applicable_is_excluded_from_progress_and_can_be_restored(self):
        before = build(self.record, self.broker)
        key = "purchase-buyer-consideration"
        response = self.post(key, "na")
        self.assertEqual(response.status_code, 200)
        after = build(self.record, self.broker)
        self.assertEqual(after["total"], before["total"] - 1)
        self.assertEqual(after["done"], 0)
        self.assertEqual(self.post(key, "todo").status_code, 200)
        self.assertEqual(build(self.record, self.broker)["total"], before["total"])

    def test_role_change_keeps_history_without_reusing_wrong_side_completion(self):
        self.post("purchase-buyer-em", "done")
        self.rep.side = "seller"
        self.rep.save()
        self.assertEqual(build(self.record, self.broker)["done"], 0)
        self.assertEqual(self.post("purchase-buyer-em", "todo").status_code, 404)
        self.assertEqual(self.record.checklist_items.get().status, "approved")

    def test_permission_validation_and_csrf_prevent_mutations(self):
        self.assertEqual(self.post("purchase-buyer-em", "invalid").status_code, 400)
        self.assertEqual(self.post("lease-tenant-deposit", "done").status_code, 404)
        self.client.force_login(self.user("read_only"))
        self.assertEqual(self.post("purchase-buyer-em", "done").status_code, 403)
        coordinator = self.user("coordinator")
        self.client.force_login(coordinator)
        self.assertFalse(any(row["financial"] for row in self.rows(build(self.record, coordinator))))
        self.assertEqual(self.post("purchase-buyer-cda", "done").status_code, 404)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.broker)
        self.assertEqual(csrf_client.post(reverse("workflow_checklist_update", args=[self.record.pk, "purchase-buyer-em"]), {"state": "done"}).status_code, 403)
        self.assertEqual(self.record.checklist_items.count(), 0)

    def test_legacy_records_are_preserved_but_complex_ui_is_removed(self):
        legacy = ChecklistItem.objects.create(deal=self.record, category="Closing", title="Legacy evidence workflow", status="received")
        response = self.client.get(self.record.get_absolute_url() + "?tab=checklist")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'data-deal-tab="checklist"')
        self.assertNotContains(response, "Create checklist")
        self.assertNotContains(response, "Legacy evidence workflow")
        legacy.refresh_from_db()
        self.assertEqual(legacy.status, "received")
        self.assertEqual(self.record.checklist_items.count(), 1)

    def test_financial_task_status_does_not_leak_through_old_item_forms_or_activity(self):
        self.assertEqual(self.post("purchase-buyer-cda", "done").status_code, 200)
        item = self.record.checklist_items.get(workflow_key="purchase-buyer-cda")
        self.client.force_login(self.user("coordinator"))
        self.assertEqual(self.client.get(reverse("checklist_item_edit", args=[item.pk])).status_code, 403)
        self.assertNotContains(self.client.get(self.record.get_absolute_url()), "CDA confirmed")

    def test_linked_deadline_does_not_expose_financial_checklist_items(self):
        self.post('purchase-buyer-cda', 'done')
        item = self.record.checklist_items.get(workflow_key='purchase-buyer-cda')
        deadline = Deadline.objects.create(deal=self.record, name='Closing deadline', rule_type='fixed')
        item.deadline = deadline
        item.save(update_fields=['deadline'])
        self.client.force_login(self.user('coordinator'))
        self.assertNotContains(self.client.get(deadline.get_absolute_url()), item.title)
        self.client.force_login(self.broker)
        self.assertContains(self.client.get(deadline.get_absolute_url()), item.title)

    def test_legacy_dependency_choices_do_not_expose_financial_tasks(self):
        self.post("purchase-buyer-cda", "done")
        private = self.record.checklist_items.get(workflow_key="purchase-buyer-cda")
        ordinary = ChecklistItem.objects.create(deal=self.record, category="General", title="Ordinary follow-up")
        url = reverse("checklist_item_edit", args=[ordinary.pk])
        for role in ["coordinator", "read_only"]:
            self.client.force_login(self.user(role))
            response = self.client.get(url)
            self.assertNotIn(private, response.context["form"].fields["depends_on"].queryset)
            self.assertNotContains(response, "CDA confirmed")
        self.client.force_login(self.broker)
        response = self.client.get(url)
        self.assertIn(private, response.context["form"].fields["depends_on"].queryset)

    def test_language_changes_labels_without_changing_saved_tasks(self):
        self.post("purchase-buyer-em", "done")
        with override("zh-hans"):
            row = next(row for row in self.rows() if row["key"] == "purchase-buyer-em")
            self.assertEqual(row["title"], "EM")
            self.assertTrue(row["done"])
        with override("en"):
            self.assertEqual(next(row for row in self.rows() if row["key"] == "purchase-buyer-em")["title"], "EM")
