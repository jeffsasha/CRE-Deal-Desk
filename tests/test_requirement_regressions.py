from datetime import date
from decimal import Decimal
from django.urls import reverse
from deals import keydates, services
from deals.forms import CloseDealForm, NewDealForm, KeyDatesForm
from tests.base import DeskTestCase

class RequirementRegressions(DeskTestCase):
    def setUp(self):
        self.broker = self.user('broker')
        self.client.force_login(self.broker)

    def test_lease_rent_shown_in_list(self):
        self.deal(transaction_type='lease', lease_starting_rent=Decimal('1234.50'), lease_rent_unit='usd_month', lease_rent_basis='gross')
        self.assertContains(self.client.get(reverse('deal_list')), '$1,234.50/mo Gross')

    def test_correct_closing_form_preserves_actual_values(self):
        d = self.deal(executed_contract_price_cents=100000)
        services.close_deal(d, self.broker, actual_closing_date=date(2025,12,19), total_cents=90000)
        form = CloseDealForm(deal=d)
        self.assertEqual(form.initial.get('total'), 90000)
        self.assertEqual(form.initial.get('actual_closing_date'), date(2025,12,19))

    def test_rent_rejects_values_outside_model_precision(self):
        for value in ('12345678901.00', '9'*400):
            with self.subTest(value=value[:20]):
                form = NewDealForm({'kind':'lease','side':'tenant','status':'active','street':'1 Test St','city':'Houston','lease_starting_rent':value})
                self.assertFalse(form.is_valid())
                self.assertIn('lease_starting_rent',form.errors)

    def test_sale_ignores_hidden_lease_values(self):
        form = NewDealForm({'kind':'sale','side':'buyer','status':'active','street':'1 Test St','city':'Houston','price':'1200','lease_starting_rent':'bad'})
        self.assertTrue(form.is_valid(),form.errors)

    def test_fixed_feasibility_closing_without_effective_date(self):
        d = self.deal()
        keydates.save(d, {'feasibility_mode':'date','feasibility_date':date(2026,4,15),'closing_mode':'days','closing_days':15},self.broker)
        closing = d.deadlines.get(template_key='closing_offset',state='open')
        self.assertEqual(closing.current_date,date(2026,4,30))

    def test_closing_tracks_event_date_changes(self):
        d = self.deal()
        keydates.save(d, {'effective_date':date(2026,3,4),'feasibility_days':30,'closing_mode':'days','closing_days':15,'next_business_day':True},self.broker)
        services.record_event(d,'effective_date',date(2026,3,6),self.broker)
        closing = d.deadlines.get(template_key='closing_offset',state='open')
        self.assertEqual(closing.current_date,date(2026,4,21))
        d.refresh_from_db()
        self.assertEqual(d.contractual_closing_date,date(2026,4,21))

    def test_hidden_date_mode_values_do_not_block_save(self):
        d = self.deal()
        form = KeyDatesForm({'feasibility_mode':'date','feasibility_date':'2026-04-15','feasibility_days':'bad','closing_mode':'date','closing_date':'2026-05-01','closing_days':'bad'},deal=d)
        self.assertTrue(form.is_valid(),form.errors)

    def test_switching_feasibility_basis_relinks_closing(self):
        d = self.deal()
        base = {'effective_date':date(2026,3,4),'closing_mode':'days','closing_days':15}
        keydates.save(d, {**base,'feasibility_days':30},self.broker)
        keydates.save(d, {**base,'feasibility_mode':'date','feasibility_date':date(2026,4,15)},self.broker)
        closing = d.deadlines.get(template_key='closing_offset',state='open')
        self.assertEqual(closing.current_date,date(2026,4,30))
        keydates.extend(d,'feasibility',self.broker,days=5)
        closing.refresh_from_db()
        self.assertEqual(closing.current_date,date(2026,5,5))

    def test_money_too_large_for_storage_is_form_error(self):
        form = NewDealForm({'kind':'sale','side':'buyer','status':'active','street':'1 Test St','city':'Houston','price':'999999999999999999'})
        self.assertFalse(form.is_valid())
        self.assertIn('price',form.errors)

    def test_switch_to_fixed_feasibility_applies_weekend_before_closing(self):
        d = self.deal()
        keydates.save(d, {'effective_date':date(2026,3,2),'feasibility_days':30,'closing_mode':'days','closing_days':15},self.broker)
        keydates.save(d, {'effective_date':date(2026,3,2),'feasibility_mode':'date','feasibility_date':date(2026,5,3),'closing_mode':'days','closing_days':15,'next_business_day':True},self.broker)
        closing = d.deadlines.get(template_key='closing_offset',state='open')
        self.assertEqual(closing.current_date,date(2026,5,19))

    def test_legacy_closing_conversion_preserves_weekend_adjusted_dates(self):
        d = self.deal()
        keydates.save(d, {'effective_date':date(2026,1,2),'feasibility_days':1,'next_business_day':True},self.broker)
        services.set_term(d,'closing_days_after_effective',10,self.broker)
        from deadlines.services import generate_standard_deadlines
        generate_standard_deadlines(d,actor=self.broker)
        closing = d.deadlines.get(template_key='closing_offset',state='open')
        before = closing.current_date
        keydates.save(d,keydates.current_values(d),self.broker)
        closing.refresh_from_db()
        self.assertEqual(closing.current_date,before)

    def test_completed_feasibility_remains_a_closing_anchor(self):
        d = self.deal()
        values = {'effective_date':date(2026,3,4),'feasibility_days':30,'closing_mode':'days','closing_days':15}
        keydates.save(d,values,self.broker)
        d.deadlines.filter(template_key='feasibility_expiration',state='open').update(state='satisfied')
        keydates.save(d,values,self.broker)
        closing = d.deadlines.get(template_key='closing_offset',state='open')
        self.assertEqual(closing.current_date,date(2026,4,18))

    def test_incomplete_timeline_does_not_claim_all_dates_passed(self):
        d = self.deal()
        services.record_event(d,'effective_date',date(2025,1,1),self.broker)
        page = self.client.get(reverse('dashboard'))
        self.assertContains(page,'Key dates not entered')
        self.assertNotContains(page,'All key dates passed')
