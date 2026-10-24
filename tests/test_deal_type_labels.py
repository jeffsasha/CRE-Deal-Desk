from django.urls import reverse
from tests.base import DeskTestCase

class DealTypeLabelTests(DeskTestCase):
    def setUp(self):
        self.client.force_login(self.user('broker'))

    def test_three_transaction_types_have_distinct_status_style_labels(self):
        for kind in ('sale','lease','business_asset'):
            self.deal(name=kind,transaction_type=kind)
        page=self.client.get(reverse('deal_list'))
        self.assertContains(page,'<span class="pill pill-amber">For sale</span>',html=True)
        self.assertContains(page,'<span class="pill pill-blue">Lease</span>',html=True)
        self.assertContains(page,'<span class="pill pill-violet">Business for sale</span>',html=True)

    def test_original_address_and_price_layout_is_preserved(self):
        self.deal(name='Original transaction name',transaction_type='sale')
        page=self.client.get(reverse('deal_list'))
        self.assertContains(page,'Original transaction name')
        for obsolete in ('deal-entry','deal-field','deal-property-icon','deal-directory'):
            self.assertNotContains(page,obsolete)
