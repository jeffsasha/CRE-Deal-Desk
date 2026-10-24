from decimal import Decimal
from django.urls import reverse
from django.utils.translation import override
from core.money import Total
from core.templatetags.desk import money, rate
from deals.forms import IssueForm
from deals import pricing
from tests.base import DeskTestCase

class ChineseCopyTests(DeskTestCase):
    def setUp(self):
        self.client.force_login(self.user('admin'))
        self.client.cookies['django_language']='zh-hans'

    def test_dashboard_uses_chinese_business_terms(self):
        self.deal(name='保留原始地址',transaction_type='purchase')
        page=self.client.get(reverse('dashboard'))
        for text in ('进行中的交易','SKW 预计佣金','生效日期','尽调期结束','交割日期'):
            self.assertContains(page,text)
        for text in ('进行中的 Deal','SKW Commission','Effective Date','Feasibility Period','Closing Date'):
            self.assertNotContains(page,text)
        self.assertContains(page,'保留原始地址')

    def test_lease_form_uses_readable_chinese_labels(self):
        page=self.client.get(reverse('deal_create'))
        for text in ('售价','免租期（月）','租户装修补贴（TI）','水电等公用事业费','租金年递增率（%）'):
            self.assertContains(page,text)
        self.assertNotContains(page,'TI allowance')

    def test_currency_units_and_missing_amounts_follow_language(self):
        d=self.deal(transaction_type='lease',lease_starting_rent=Decimal('1400'),lease_rent_unit='usd_month',lease_rent_basis='gross')
        with override('zh-hans'):
            self.assertIn('/月',pricing.headline(d))
            self.assertIn('包费租金',pricing.headline(d))
            self.assertEqual(money(None),'未知')
            self.assertNotIn('unknown',Total(unknown_count=1).display())
            self.assertEqual(rate(Decimal('12'),'usd_sf_year'),'$12.00/平方英尺/年')
        with override('en'):
            self.assertEqual(pricing.headline(d),'$1,400/mo Gross')
            self.assertEqual(money(None),'Unknown')

    def test_issue_title_is_heading_not_property_title(self):
        with override('zh-hans'):
            self.assertEqual(IssueForm().fields['title'].label,'标题')
