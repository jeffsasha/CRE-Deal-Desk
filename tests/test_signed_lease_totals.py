from datetime import date
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.urls import reverse
from deals import pricing, services, stats
from deals.forms import DealForm, CloseDealForm, NewDealForm
from tests.base import DeskTestCase

class SignedLeaseTotalTests(DeskTestCase):
    def setUp(self):
        self.broker=self.user('broker')
        self.client.force_login(self.broker)

    def values(self,**changes):
        data={'lease_starting_rent':Decimal('3000'),'lease_rent_unit':'usd_month','lease_term_months':60,'lease_free_rent_months':None,'lease_escalation_pct':None}
        data.update(changes)
        return data

    def total(self,**changes):
        return pricing.lease_total_cents(self.values(**changes))

    def test_five_and_ten_year_signed_terms(self):
        self.assertEqual(self.total(),18000000)
        self.assertEqual(self.total(lease_term_months=120),36000000)

    def test_free_rent_and_annual_escalation(self):
        self.assertEqual(self.total(lease_free_rent_months=Decimal('2')),17400000)
        self.assertEqual(self.total(lease_free_rent_months=Decimal('2'),lease_escalation_pct=Decimal('3')),18512889)
        self.assertEqual(self.total(lease_term_months=13,lease_escalation_pct=Decimal('10')),3930000)
        self.assertEqual(self.total(lease_term_months=12,lease_free_rent_months=Decimal('1.5')),3150000)
        self.assertEqual(self.total(lease_term_months=12,lease_free_rent_months=Decimal('12')),0)

    def test_yearly_and_square_foot_units(self):
        for unit,rent,area in [('usd_year','36000',None),('usd_sf_year','18','2000'),('usd_sf_month','1.5','2000')]:
            with self.subTest(unit=unit):
                self.assertEqual(self.total(lease_starting_rent=Decimal(rent),lease_rent_unit=unit,lease_area_sf=Decimal(area) if area else None),18000000)
        self.assertEqual(self.total(lease_rent_unit='usd_total',lease_starting_rent=Decimal('180000')),18000000)

    def test_unknown_inputs_stay_unknown(self):
        for fields in ({'lease_term_months':None},{'lease_starting_rent':None},{'lease_rent_unit':''},{'lease_rent_unit':'usd_sf_year','lease_area_sf':None}):
            with self.subTest(fields=fields): self.assertIsNone(self.total(**fields))

    def test_extra_charges_and_unexercised_options_are_not_counted(self):
        self.assertEqual(self.total(lease_nnn_amount=Decimal('500'),lease_utility_amount=Decimal('200'),lease_ti_amount=Decimal('15000'),renewal_option_months=60),18000000)

    def test_invalid_or_excessive_values_are_rejected(self):
        for values in ({'lease_term_months':0},{'lease_term_months':1201},{'lease_free_rent_months':Decimal('61')},{'lease_starting_rent':Decimal('-1')},{'lease_escalation_pct':Decimal('-1')},{'lease_rent_unit':'usd_total','lease_escalation_pct':Decimal('3')},{'lease_term_months':1200,'lease_escalation_pct':Decimal('100'),'lease_starting_rent':Decimal('9999999999')}):
            with self.subTest(values=values):
                with self.assertRaises(ValidationError):self.total(**values)

    def test_creation_edit_close_and_header_use_calculated_total(self):
        response=self.client.post(reverse('deal_create'),{'kind':'lease','side':'tenant','status':'active','street':'100 Signed Lease St','city':'Houston','lease_starting_rent':'3000','lease_rent_unit':'usd_month','lease_term_months':'60','lease_free_rent_months':'2','lease_escalation_pct':'3','renewal_option_months':'60'})
        self.assertEqual(response.status_code,302)
        from deals.models import Deal
        deal=Deal.objects.order_by('-pk').first()
        self.assertEqual(deal.lease_total_consideration_cents,18512889)
        page=self.client.get(reverse('deal_list'))
        self.assertContains(page,'$3,000/mo')
        self.assertContains(self.client.get(deal.get_absolute_url()),'$185,128.89')
        response=self.client.post(reverse('deal_edit',args=[deal.pk]),{'name':deal.name,'lease_starting_rent':'3000','lease_rent_unit':'usd_month','lease_term_months':'120','lease_free_rent_months':'0','lease_escalation_pct':'0'})
        self.assertEqual(response.status_code,302)
        deal.refresh_from_db();self.assertEqual(deal.lease_total_consideration_cents,36000000)
        form=CloseDealForm(deal=deal)
        self.assertTrue(form.fields['total'].disabled)
        self.assertEqual(form.initial['total'],36000000)
        services.close_deal(deal,self.broker,actual_closing_date=date(2025,12,1),total_cents=1)
        deal.refresh_from_db();self.assertEqual(deal.lease_total_consideration_cents,36000000)
        self.assertEqual(stats.totals(2025).leases,36000000)

    def test_editing_without_a_term_preserves_legacy_manual_total(self):
        deal=self.deal(transaction_type='lease',lease_total_consideration_cents=500000)
        response=self.client.post(reverse('deal_edit',args=[deal.pk]),{'name':deal.name,'lease_starting_rent':'1000','lease_rent_unit':'usd_month'})
        self.assertEqual(response.status_code,302)
        deal.refresh_from_db();self.assertEqual(deal.lease_total_consideration_cents,500000)
        self.assertFalse(CloseDealForm(deal=deal).fields['total'].disabled)

    def test_clearing_a_previously_calculated_term_clears_stale_total(self):
        deal=self.deal(transaction_type='lease',lease_term_months=60,lease_starting_rent=Decimal('3000'),lease_rent_unit='usd_month',lease_total_consideration_cents=18000000)
        response=self.client.post(reverse('deal_edit',args=[deal.pk]),{'name':deal.name,'lease_starting_rent':'3000','lease_rent_unit':'usd_month','lease_term_months':''})
        self.assertEqual(response.status_code,302)
        deal.refresh_from_db();self.assertIsNone(deal.lease_total_consideration_cents)

    def test_form_validation_explains_missing_area_and_excess_free_rent(self):
        base={'kind':'lease','side':'tenant','status':'active','street':'A','city':'Houston','lease_starting_rent':'18','lease_rent_unit':'usd_sf_year','lease_term_months':'60'}
        form=NewDealForm(base)
        self.assertFalse(form.is_valid());self.assertIn('lease_area_sf',form.errors)
        form=NewDealForm({**base,'lease_rent_unit':'usd_month','lease_free_rent_months':'61'})
        self.assertFalse(form.is_valid());self.assertIn('lease_free_rent_months',form.errors)

    def test_square_foot_quote_precision_is_preserved_end_to_end(self):
        payload={'kind':'lease','side':'tenant','status':'active','street':'Precision Test St','city':'Houston','lease_starting_rent':'1.2345','lease_rent_unit':'usd_sf_month','lease_area_sf':'10000','lease_term_months':'60'}
        form=NewDealForm(payload)
        self.assertTrue(form.is_valid(),form.errors)
        self.assertEqual(form.cleaned_data['lease_starting_rent'],Decimal('1.2345'))
        response=self.client.post(reverse('deal_create'),payload)
        self.assertEqual(response.status_code,302)
        from deals.models import Deal
        deal=Deal.objects.order_by('-pk').first()
        self.assertEqual(deal.lease_total_consideration_cents,74070000)
        self.assertEqual(DealForm(instance=deal)['lease_starting_rent'].value(),'1.2345')
        self.assertIn('$1.2345/SF/mo',pricing.headline(deal))

    def test_total_rounding_happens_after_summing_the_signed_term(self):
        self.assertEqual(self.total(lease_starting_rent=Decimal('1000'),lease_rent_unit='usd_year',lease_term_months=12),100000)
        self.assertEqual(self.total(lease_starting_rent=Decimal('0.01'),lease_term_months=1,lease_free_rent_months=Decimal('0.5')),1)
