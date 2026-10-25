from django.urls import reverse
from django.utils.translation import override

from checklists.workflow import build
from crm.models import Contact, Organization
from deals.models import Representation
from imports.views import NewImportForm
from .base import DeskTestCase


class SimplifiedNavigationTests(DeskTestCase):
    def setUp(self):
        self.admin = self.user('admin')
        self.client.force_login(self.admin)

    def test_settings_uses_the_same_partial_navigation(self):
        response = self.client.get(reverse('settings_index'), HTTP_X_WORKSPACE_NAVIGATION='1')
        self.assertContains(response, 'data-workspace-page="settings_index"')
        self.assertNotContains(response, '<aside class="sidebar">')
        self.assertIn('X-Workspace-Navigation', response.headers['Vary'])
        full = self.client.get(reverse('dashboard'))
        self.assertContains(full, '<a href="/settings/" data-workspace-nav')
        self.assertNotContains(full, 'Contacts &amp; Companies')
        self.assertNotContains(full, '/contacts/')

    def test_contact_management_routes_are_removed_but_records_remain(self):
        company = Organization.objects.create(name='Keep Company')
        contact = Contact.objects.create(first_name='Keep Person', organization=company)
        for url in ['/contacts/', '/contacts/new/', f'/contacts/{contact.pk}/',
                    f'/contacts/{contact.pk}/edit/', '/companies/new/', f'/companies/{company.pk}/',
                    f'/companies/{company.pk}/edit/', f'/contacts/archive/contact/{contact.pk}/']:
            self.assertEqual(self.client.get(url).status_code, 404, url)
            self.assertEqual(self.client.post(url, {'first_name': 'Changed'}).status_code, 404, url)
        self.assertTrue(Contact.objects.filter(pk=contact.pk, first_name='Keep Person').exists())
        self.assertTrue(Organization.objects.filter(pk=company.pk).exists())

    def test_contact_results_and_import_creation_are_removed(self):
        company = Organization.objects.create(name='Unique CRM Company')
        Contact.objects.create(first_name='Unique CRM Person', organization=company)
        response = self.client.get(reverse('search'), {'q': 'Unique CRM'})
        self.assertNotIn('Contacts', response.context['results'])
        self.assertNotIn('Companies', response.context['results'])
        self.assertEqual(self.client.get(reverse('quick_search'), {'q': 'Unique CRM'}).json()['results'], [])
        self.assertNotIn('contacts', dict(NewImportForm().fields['kind'].choices))
        self.assertEqual(self.client.get(reverse('import_template', args=['contacts'])).status_code, 404)

    def test_short_checklist_labels_preserve_completion_keys(self):
        record = self.deal(actor=self.admin)
        Representation.objects.create(deal=record, side='buyer', is_skw=True)
        self.client.post(reverse('workflow_checklist_update', args=[record.pk, 'purchase-buyer-em']), {'state': 'done'})
        for language in ['en', 'zh-hans']:
            with override(language):
                rows = {row['key']: row for stage in build(record, self.admin)['stages'] for row in stage['items']}
                for key, label in [('em', 'EM'), ('survey', 'Survey'), ('title', 'Title Commitment'), ('cda', 'CDA')]:
                    self.assertEqual(rows['purchase-buyer-' + key]['title'], label)
                self.assertTrue(rows['purchase-buyer-em']['done'])
                self.assertLessEqual(max(len(row['title']) for row in rows.values()), 32)

    def test_property_owner_remains_plain_text_without_removed_crm_links(self):
        company = Organization.objects.create(name='Existing Owner LLC')
        prop = self.prop(owner=company)
        response = self.client.get(prop.get_absolute_url())
        self.assertContains(response, company.name)
        self.assertNotContains(response, f'<a href="">{company.name}</a>')
