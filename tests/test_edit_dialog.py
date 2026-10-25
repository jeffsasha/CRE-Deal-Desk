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


class NewDealDialogTests(DeskTestCase):
    def setUp(self):
        self.client.force_login(self.user("broker"))

    def test_new_deal_actions_open_in_dialog(self):
        for name in ("dashboard", "deal_list"):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertIn(reverse("deal_create"), EditorLinks(response.content.decode()).targets)

    def test_embedded_new_deal_requires_only_one_address_field(self):
        response = self.client.get(reverse("deal_create") + "?editor=1")
        self.assertContains(response, 'data-editor-page')
        self.assertContains(response, 'name="street"')
        for name in ("suite", "city", "zip_code"):
            self.assertNotIn(name, response.context["form"].fields)
            self.assertNotContains(response, f'name="{name}"')

    def test_create_from_dialog_preserves_full_address_and_opens_new_deal(self):
        from deals.models import Deal

        address = "100 Test Ave, Suite 210, Austin, TX 78701"
        response = self.client.post(reverse("deal_create") + "?editor=1", {
            "kind": "lease", "side": "tenant", "status": "active", "street": address,
            "lease_type": "lease", "lease_starting_rent": "3000", "lease_rent_unit": "usd_month",
            "lease_term_months": "60",
        })
        self.assertEqual(response.status_code, 302)
        deal = Deal.objects.get()
        self.assertRedirects(response, deal.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(deal.name, address)
        self.assertEqual(deal.primary_property.address, address)
        self.assertEqual(deal.lease_total_consideration_cents, 18_000_000)

    def test_invalid_new_deal_stays_in_dialog_and_keeps_choices(self):
        from deals.models import Deal

        response = self.client.post(reverse("deal_create") + "?editor=1", {
            "kind": "sale", "side": "seller", "status": "active", "street": "", "price": "125000",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-editor-page')
        self.assertIn("street", response.context["form"].errors)
        self.assertEqual(response.context["kind"], "sale")
        self.assertEqual(response.context["side"], "seller")
        self.assertFalse(Deal.objects.exists())

    def test_complete_address_reuses_existing_property_and_its_type(self):
        from deals.models import Deal
        from properties.models import Property

        prop = self.prop(street="100 Test Ave", suite="210", city="Austin", state="TX",
                         postal_code="78701", property_type="land")
        response = self.client.post(reverse("deal_create") + "?editor=1", {
            "kind": "sale", "side": "buyer", "status": "active",
            "street": "100 Test Avenue, Suite 210, Austin, TX 78701",
        })
        self.assertEqual(response.status_code, 302)
        deal = Deal.objects.get()
        self.assertEqual(deal.primary_property, prop)
        self.assertEqual(deal.transaction_type, "land_purchase")
        self.assertEqual(Property.objects.count(), 1)

    def test_single_address_property_can_be_edited_without_city_or_state(self):
        address = "100 Test Ave, Suite 210, Austin, TX 78701"
        prop = self.prop(street=address, city="", state="")
        response = self.client.post(reverse("property_edit", args=[prop.pk]), {
            "name": "Updated property name", "street": address, "property_type": "retail",
            "notes": "Updated after single-address creation",
        })
        self.assertRedirects(response, prop.get_absolute_url(), fetch_redirect_response=False)
        prop.refresh_from_db()
        self.assertEqual(prop.notes, "Updated after single-address creation")
        self.assertEqual(prop.address, address)
