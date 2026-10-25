from html.parser import HTMLParser

from django.urls import reverse
from django.utils import timezone

from .base import DeskTestCase


class EditorLinks(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.targets = set()
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "data-editor" in attrs:
            self.targets.add(attrs.get("href"))


class EditDialogTests(DeskTestCase):
    def setUp(self):
        self.broker = self.user("broker")
        self.client.force_login(self.broker)
        self.record = self.deal(actor=self.broker)
        self.record.effective_date = timezone.localdate()
        self.record.save(update_fields=["effective_date"])

    def test_secondary_actions_open_in_dialog(self):
        response = self.client.get(self.record.get_absolute_url())
        targets = EditorLinks(response.content.decode()).targets
        for name in ["deal_edit", "deal_key_dates", "deal_extend", "deal_close"]:
            self.assertIn(reverse(name, args=[self.record.pk]), targets)
        self.assertNotIn(f"/deadlines/new/?deal={self.record.pk}", targets)
        self.assertContains(response, 'id="edit-dialog"')

    def test_supporting_party_forms_use_same_dialog(self):
        response = self.client.get(self.record.get_absolute_url() + "?tab=parties")
        self.assertIn(reverse("deal_sub", args=[self.record.pk, "party"]),
                      EditorLinks(response.content.decode()).targets)

    def test_embedded_forms_keep_fields_and_omit_recursive_dialog(self):
        for name in ["deal_edit", "deal_key_dates", "deal_extend", "deal_close"]:
            with self.subTest(name=name):
                response = self.client.get(reverse(name, args=[self.record.pk]) + "?editor=1")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'class="editor-page" data-editor-page')
                self.assertContains(response, 'name="csrfmiddlewaretoken"')
                self.assertNotContains(response, 'id="edit-dialog"')

    def test_invalid_submission_stays_in_editor_without_changing_data(self):
        original_name = self.record.name
        response = self.client.post(reverse("deal_edit", args=[self.record.pk]) + "?editor=1",
                                    {"name": "", "price": "invalid"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="editor-page" data-editor-page')
        self.assertTrue(response.context["form"].errors)
        self.record.refresh_from_db()
        self.assertEqual(self.record.name, original_name)

    def test_save_retains_existing_redirect_and_price_validation(self):
        response = self.client.post(reverse("deal_edit", args=[self.record.pk]) + "?editor=1",
                                    {"name": "Updated address", "price": "125,000", "description": "Saved in dialog"})
        self.assertRedirects(response, self.record.get_absolute_url(), fetch_redirect_response=False)
        self.record.refresh_from_db()
        self.assertEqual(self.record.name, "Updated address")
        self.assertEqual(self.record.executed_contract_price_cents, 12_500_000)

    def test_dialog_does_not_bypass_edit_permission(self):
        self.client.force_login(self.user("read_only"))
        response = self.client.get(reverse("deal_edit", args=[self.record.pk]) + "?editor=1")
        self.assertEqual(response.status_code, 403)
