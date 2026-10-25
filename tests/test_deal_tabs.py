from deals.models import DealParty, log_activity

from .base import DeskTestCase


class DealTabsTests(DeskTestCase):
    def test_preloaded_activity_respects_commission_permission(self):
        broker = self.user("broker")
        deal = self.deal(actor=broker)
        log_activity(deal, "SKW commission set to $85,500.00", actor=broker)
        log_activity(deal, "Commission ledger: Receipt $15,000.00", actor=broker)
        log_activity(deal, "Operational update", actor=broker)
        self.client.force_login(self.user("read_only"))
        response = self.client.get(deal.get_absolute_url())
        self.assertContains(response, "Operational update")
        self.assertNotContains(response, "$85,500.00")
        self.assertNotContains(response, "$15,000.00")
        self.client.force_login(broker)
        self.assertContains(self.client.get(deal.get_absolute_url()), "$85,500.00")

    def test_each_entry_tab_includes_data_for_switching_without_another_request(self):
        broker = self.user("broker")
        self.client.force_login(broker)
        deal = self.deal(actor=broker)
        party = DealParty.objects.create(deal=deal, role="buyer", name="Tab party")
        activity = log_activity(deal, "Tab activity", actor=broker)

        for tab in ["overview", "parties", "activity", "closing"]:
            with self.subTest(tab=tab):
                response = self.client.get(deal.get_absolute_url(), {"tab": tab})
                self.assertEqual(response.status_code, 200)
                self.assertIn(party, response.context["parties"])
                self.assertIn(activity, response.context["activities"])
                self.assertTrue(response.context["workflow"]["stages"])
                self.assertContains(response, "Tab party")
                self.assertContains(response, "Tab activity")
