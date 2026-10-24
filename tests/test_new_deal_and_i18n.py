"""Guided New Deal (type + representation mapping) and the 中/EN switch."""
from django.urls import reverse

from crm.models import Organization
from datetime import date
from decimal import Decimal

from deals.models import Deal

from .base import DeskTestCase


class GuidedNewDealTests(DeskTestCase):
    def setUp(self):
        self.broker = self.user("broker")
        self.client.force_login(self.broker)

    def post(self, **data):
        base = {"status": "active", "street": "100 Test Ave", "city": "Houston", "lease_type": "lease"}
        base.update(data)
        return self.client.post(reverse("deal_create"), base)

    def created(self):
        return Deal.objects.order_by("-pk").first()

    def test_mapping(self):
        cases = [
            ("sale", "buyer", {}, "purchase", ["buyer"]),
            ("sale", "seller", {}, "sale", ["seller"]),
            ("sale", "both", {}, "sale", ["buyer", "seller"]),
            ("lease", "tenant", {"lease_type": "lease_renewal"}, "lease_renewal", ["tenant"]),
            ("lease", "both", {}, "lease", ["landlord", "tenant"]),
            ("business", "seller", {}, "business_asset", ["seller"]),
        ]
        for kind, side, extra, ttype, sides in cases:
            resp = self.post(kind=kind, side=side, **extra)
            self.assertEqual(resp.status_code, 302, (kind, side, resp.content[:300]))
            d = self.created()
            self.assertEqual(d.transaction_type, ttype, (kind, side))
            self.assertEqual(sorted(d.representations.values_list("side", flat=True)), sorted(sides))
            self.assertTrue(all(d.representations.values_list("is_skw", flat=True)))

    def test_clients_and_parties(self):
        Organization.objects.create(name="Existing Tenant LLC", is_client=True)
        self.post(kind="lease", side="both", suite="210", client_a="existing tenant llc", client_b="New Landlord LP")
        d = self.created()
        roles = dict(d.parties.values_list("role", "organization__name"))
        self.assertEqual(roles["tenant"], "Existing Tenant LLC")  # matched, not duplicated
        self.assertEqual(roles["landlord"], "New Landlord LP")
        self.assertEqual(Organization.objects.filter(name__iexact="existing tenant llc").count(), 1)
        self.assertEqual(d.deal_properties.get().space.suite, "210")
        self.assertEqual(d.name, "100 Test Ave Ste 210, Houston, TX")  # the deal is its address

    def test_same_address_reuses_the_property(self):
        self.post(kind="sale", side="seller", street="4008 Ade St", zip_code="77063")
        self.post(kind="lease", side="landlord", street="4008 ADE STREET")
        first, second = Deal.objects.order_by("pk")
        self.assertEqual(first.primary_property, second.primary_property)
        self.assertEqual(first.name, "4008 Ade St, Houston, TX 77063")
        self.assertEqual(second.responsible_broker, self.broker)

    def test_price_entered_with_the_deal(self):
        self.post(kind="sale", side="buyer", price="1,250,000.50")
        d = self.created()
        self.assertEqual(d.executed_contract_price_cents, 125000050)
        self.assertEqual(d.status_key, "active")
        self.post(kind="lease", side="tenant", lease_starting_rent="1,400", lease_rent_unit="usd_month",
                  lease_rent_basis="nnn", lease_nnn_amount="350.00", lease_utility_amount="120",
                  lease_utility_unit="usd_month", lease_free_rent_months="2", lease_ti_amount="15",
                  lease_ti_unit="usd_sf", lease_escalation_pct="3")
        d = self.created()
        self.assertEqual((d.lease_starting_rent, d.lease_rent_unit, d.lease_rent_basis), (Decimal("1400.00"), "usd_month", "nnn"))
        self.assertEqual((d.lease_nnn_amount, d.lease_free_rent_months, d.lease_ti_unit, d.lease_escalation_pct),
                         (Decimal("350.00"), Decimal("2"), "usd_sf", Decimal("3")))
        page = self.client.get(d.get_absolute_url())
        self.assertContains(page, "$1,400/mo NNN")
        # Edit the price later from the deal.
        self.client.post(reverse("deal_edit", args=[d.pk]), {"name": d.name, "lease_starting_rent": "1,500.00",
                                                             "lease_rent_unit": "usd_month", "lease_rent_basis": "gross"})
        d.refresh_from_db()
        self.assertEqual((d.lease_starting_rent, d.lease_rent_basis, d.lease_nnn_amount), (Decimal("1500.00"), "gross", None))

    def test_letters_are_not_an_amount(self):
        resp = self.post(kind="sale", side="buyer", price="12abc")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Deal.objects.exists())

    def test_past_deal_added_as_closed(self):
        resp = self.post(kind="sale", side="seller", price="360,000", status="closed", closed_on="2025-12-19")
        d = self.created()
        self.assertRedirects(resp, d.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual((d.status_key, d.actual_closing_date, d.actual_closing_price_cents), ("closed", date(2025, 12, 19), 36000000))
        self.assertEqual(self.post(kind="sale", side="seller", status="closed").status_code, 200)  # date required

    def test_terminate_and_reopen(self):
        self.post(kind="sale", side="buyer")
        d = self.created()
        url = reverse("deal_status", args=[d.pk])
        self.client.post(url, {"action": "terminate"})
        d.refresh_from_db()
        self.assertEqual(d.status_key, "active")  # a reason is required
        self.client.post(url, {"action": "terminate", "reason": "Buyer walked"})
        d.refresh_from_db()
        self.assertEqual((d.status_key, d.termination_reason), ("terminated", "Buyer walked"))
        self.client.post(url, {"action": "reopen"})
        d.refresh_from_db()
        self.assertEqual(d.status_key, "active")

    def test_side_must_match_kind(self):
        resp = self.post(kind="lease", side="buyer")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Deal.objects.exists())

    def test_read_only_cannot_create(self):
        self.client.force_login(self.user("read_only"))
        self.assertEqual(self.post(kind="sale", side="buyer").status_code, 403)


class LanguageTests(DeskTestCase):
    def test_switch_to_chinese_and_back(self):
        self.client.force_login(self.user("broker"))
        self.assertContains(self.client.get(reverse("dashboard")), "Due in 7 days")
        self.client.post(reverse("set_language"), {"language": "zh-hans", "next": "/"})
        resp = self.client.get(reverse("dashboard"))
        self.assertContains(resp, "7 天内到期")
        self.assertContains(resp, 'lang="zh-hans"')
        self.client.post(reverse("set_language"), {"language": "en", "next": "/"})
        self.assertContains(self.client.get(reverse("dashboard")), "Due in 7 days")

    def test_login_page_switch_available_anonymously(self):
        resp = self.client.post(reverse("set_language"), {"language": "zh-hans", "next": "/accounts/login/"})
        self.assertEqual(resp.status_code, 302)
        self.assertContains(self.client.get("/accounts/login/"), "登录 DealDesk")
