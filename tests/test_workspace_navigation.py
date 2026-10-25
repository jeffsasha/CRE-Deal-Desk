from django.urls import reverse

from .base import DeskTestCase


class WorkspaceNavigationTests(DeskTestCase):
    def test_navigation_returns_current_content_without_rebuilding_shell(self):
        broker = self.user("broker")
        self.client.force_login(broker)
        deal = self.deal(name="Navigation transaction", actor=broker)
        for route in ["dashboard", "deal_list", "commission_list"]:
            with self.subTest(route=route):
                response = self.client.get(reverse(route), HTTP_X_WORKSPACE_NAVIGATION="1")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Navigation transaction")
                self.assertNotContains(response, '<aside class="sidebar">')
                self.assertNotContains(response, '<header class="topbar">')
        deal.name = "Updated navigation transaction"
        deal.save(update_fields=["name"])
        response = self.client.get(reverse("deal_list"), {"q": "Updated"}, HTTP_X_WORKSPACE_NAVIGATION="1")
        self.assertContains(response, "Updated navigation transaction")
        response = self.client.get(reverse("deal_list"), {"q": "no-match"}, HTTP_X_WORKSPACE_NAVIGATION="1")
        self.assertNotContains(response, "Updated navigation transaction")

    def test_partial_navigation_does_not_bypass_commission_permission(self):
        self.client.force_login(self.user("read_only"))
        response = self.client.get(reverse("commission_list"), HTTP_X_WORKSPACE_NAVIGATION="1")
        self.assertEqual(response.status_code, 403)
