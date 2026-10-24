from django.urls import reverse
from crm.models import Organization, Contact
from deals.models import DealParty
from tests.base import DeskTestCase

class SimplePartyFormTests(DeskTestCase):
    def setUp(self):
        self.client.force_login(self.user('broker'))
        self.record=self.deal()

    def test_form_only_asks_for_role_name_and_notes(self):
        page=self.client.get(reverse('deal_sub',args=[self.record.pk,'party']))
        self.assertEqual(list(page.context['form'].fields),['role','name','notes'])
        self.assertContains(page,'name="name"')
        for field in ('organization','contact','file_number','notice_address','is_notice_recipient'):
            self.assertNotContains(page,'id="id_'+field+'"')

    def test_add_party_by_typing_a_person_or_company(self):
        before=Organization.objects.count()
        for name in ('Jane Doe','Example Title LLC'):
            response=self.client.post(reverse('deal_sub',args=[self.record.pk,'party']),{'role':'tenant','name':name,'notes':'Call next week'})
            self.assertEqual(response.status_code,302)
            party=self.record.parties.order_by('-pk').first()
            self.assertEqual(party.display_name,name)
            self.assertEqual(party.notes,'Call next week')
        self.assertEqual(Organization.objects.count(),before)
        page=self.client.get(self.record.get_absolute_url()+'?tab=parties')
        self.assertContains(page,'Jane Doe')
        self.assertContains(page,'Example Title LLC')
        for label in ('File #','Designated recipient','<th>Contact</th>'):
            self.assertNotContains(page,label)

    def test_edit_legacy_party_without_renaming_shared_company(self):
        company=Organization.objects.create(name='Existing Company')
        contact=Contact.objects.create(first_name='Existing',last_name='Person')
        party=DealParty.objects.create(deal=self.record,role='tenant',organization=company,contact=contact,file_number='OLD-123',is_notice_recipient=True,notice_address='Old address')
        url=reverse('deal_sub_edit',args=[self.record.pk,'party',party.pk])
        page=self.client.get(url)
        self.assertEqual(page.context['form'].initial['name'],'Existing Person')
        response=self.client.post(url,{'role':'tenant','name':'New Name','notes':'Updated'})
        self.assertEqual(response.status_code,302)
        party.refresh_from_db();company.refresh_from_db()
        self.assertEqual(party.display_name,'New Name')
        self.assertEqual(company.name,'Existing Company')
        self.assertEqual((party.file_number,party.notice_address,party.is_notice_recipient),('OLD-123','Old address',True))

    def test_blank_name_is_rejected(self):
        page=self.client.post(reverse('deal_sub',args=[self.record.pk,'party']),{'role':'tenant','name':'   '})
        self.assertEqual(page.status_code,200)
        self.assertIn('name',page.context['form'].errors)
        self.assertFalse(self.record.parties.exists())
