from datetime import date

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils.translation import override

from deadlines.models import Deadline
from deadlines.presentation import current_note, deadline_name
from deadlines.services import recompute
from deals.models import DealEvent
from .base import DeskTestCase


class ChineseDeadlineTests(DeskTestCase):
    def setUp(self):
        self.client.force_login(self.user('admin'))
        self.client.cookies['django_language'] = 'zh-hans'
        self.deal_record = self.deal()
        self.deadline = Deadline.objects.create(
            deal=self.deal_record, name='Earnest money deposit due',
            template_key='earnest_money_deposit', offset_days=3,
            trigger_keys=['effective_date'], computation_note='Original English note')

    def test_current_note_has_dates_and_rule(self):
        DealEvent.objects.create(deal=self.deal_record, key='effective_date',
                                 occurred_on=date(2026, 3, 4), status='confirmed')
        recompute(self.deadline)
        with override('zh-hans'):
            note = current_note(self.deadline)
        self.assertIn('2026年3月4日', note)
        self.assertIn('2026年3月7日', note)
        self.assertIn('3', note)
        self.assertNotIn('Calculated result:', note)
        self.assertNotIn('calendar days', note)
        self.assertNotIn('trigger day excluded', note)

    def test_missing_trigger_and_custom_names(self):
        with override('zh-hans'):
            note = current_note(self.deadline)
            self.assertNotEqual(deadline_name(self.deadline), self.deadline.name)
            self.deadline.name = 'Client Custom Deadline'
            self.assertEqual(deadline_name(self.deadline), 'Client Custom Deadline')
        self.assertIn('未', note)
        self.assertNotIn('Awaiting trigger', note)

    def test_unconfirmed_trigger_is_explicit(self):
        DealEvent.objects.create(deal=self.deal_record, key='effective_date',
                                 occurred_on=date(2026, 3, 4), status='needs_review')
        with override('zh-hans'):
            note = current_note(self.deadline)
        self.assertIn('未确认', note)
        self.assertIn('2026年3月4日', note)

    def test_get_does_not_rewrite_history_or_dates(self):
        before = Deadline.objects.values().get(pk=self.deadline.pk)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.deadline.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Original English note')
        self.assertEqual(Deadline.objects.values().get(pk=self.deadline.pk), before)
        self.assertFalse(any(q['sql'].lstrip().upper().startswith(('INSERT ', 'UPDATE ', 'DELETE ')) for q in queries))

    def test_english_note_remains_unchanged(self):
        with override('en'):
            self.assertEqual(current_note(self.deadline), 'Original English note')
            self.assertEqual(deadline_name(self.deadline), 'Earnest money deposit due')

    def test_fixed_date_weekend_adjustment(self):
        self.deadline.rule_type = 'fixed'
        self.deadline.fixed_date = date(2026, 3, 7)
        self.deadline.weekend_rule = 'next_business_day'
        with override('zh-hans'):
            note = current_note(self.deadline)
        self.assertIn('2026年3月7日', note)
        self.assertIn('2026年3月9日', note)
        self.assertNotIn('Fixed date:', note)
        self.assertNotIn('Move to next business day', note)

    def test_list_displays_localized_dates_names_and_filter_labels(self):
        self.deadline.current_date = date(2026, 3, 7)
        self.deadline.computation = 'computed'
        self.deadline.save()
        response = self.client.get('/deadlines/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '2026年3月7日')
        self.assertNotContains(response, 'Earnest money deposit due')
        self.assertNotContains(response, '>Contractual<')
        self.assertNotContains(response, '>Internal targets<')

    def test_status_label_is_not_geographic_state(self):
        response = self.client.get(self.deadline.get_absolute_url())
        self.assertContains(response, '<label for="id_state">状态')
        self.assertNotContains(response, '<label for="id_state">州')
