"""Guided New Deal (type + representation mapping) and the 中/EN switch."""
from django.urls import reverse

from crm.models import Organization
from deals.models import Deal, Stage

from .base import DeskTestCase


class GuidedNewDealTests(DeskTestCase):
    def setUp(self):
        self.broker = self.user("broker")
        self.client.force_login(self.broker)
        self.lead = Stage.objects.get(key="lead")

    def post(self, **data):
        base = {"stage": self.lead.pk, "responsible_broker": self.broker.pk, "property_mode": "new",
                "new_address": "100 Test Ave", "new_city": "Houston", "new_type": "retail", "lease_type": "lease"}
        base.update(data)
        return self.client.post(reverse("deal_create"), base)

    def created(self):
        return Deal.objects.order_by("-pk").first()

    def test_mapping(self):
        cases = [
            ("sale", "buyer", {}, "purchase", ["buyer"]),
            ("sale", "seller", {}, "sale", ["seller"]),
            ("sale", "both", {}, "sale", ["buyer", "seller"]),
            ("sale", "buyer", {"new_type": "land"}, "land_purchase", ["buyer"]),
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
        self.assertIn("Commercial lease", d.name)

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
