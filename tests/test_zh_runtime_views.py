"""Runtime UI translation keeps record names intact in both languages."""
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils.translation import gettext, override

from core.models import AuditLog, HolidayCalendar
from crm.models import Organization

from .base import DeskTestCase


class ChineseRuntimeViewTests(DeskTestCase):
    def setUp(self):
        self.admin = self.user("admin", username="English User")
        self.client.force_login(self.admin)
        self.client.cookies["django_language"] = "zh-hans"

    def translated(self, msgid, **values):
        with override("zh-hans"):
            translated = gettext(msgid)
        self.assertNotEqual(translated, msgid, msgid)
        return translated % values if values else translated

    def test_creation_titles(self):
        for route, msgid in [("contact_create", "New contact"), ("organization_create", "New company")]:
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.context["title"], self.translated(msgid))

    def test_settings_titles_keep_names(self):
        calendar = HolidayCalendar.objects.create(name="English Calendar", code="runtime-test")
        cases = [("user_edit", self.admin.pk, "Edit %(username)s", {"username": self.admin.username}),
                 ("holiday_add", calendar.pk, "Add holiday to %(calendar)s", {"calendar": str(calendar)})]
        for route, pk, msgid, values in cases:
            with self.subTest(route=route):
                response = self.client.get(reverse(route, args=[pk]))
                self.assertEqual(response.context["title"], self.translated(msgid, **values))

    def test_company_filter_labels_keep_query_values(self):
        response = self.client.get(reverse("contact_list"), {"tab": "companies"})
        choices = response.context["listing"].filters[1].choices
        self.assertEqual(choices, [("1", self.translated("Clients only"))])

    def test_archive_title_and_notice_keep_company_name_and_note(self):
        company = Organization.objects.create(name="Do Not Translate LLC")
        url = reverse("archive_party", args=["organization", company.pk])
        response = self.client.get(url)
        self.assertEqual(response.context["title"], self.translated("Archive %(object)s", object=str(company)))
        response = self.client.post(url, {"reason": "Keep my English note"})
        notices = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertEqual(notices, [self.translated("%(object)s archived; restore from Settings.", object=str(company))])
        company.refresh_from_db()
        self.assertEqual(company.name, "Do Not Translate LLC")
        self.assertEqual(AuditLog.objects.filter(action="organization.archived").latest("pk").note, "Keep my English note")

    def test_saved_view_notice_keeps_name(self):
        response = self.client.post(reverse("save_view"), {"area": "companies", "name": "My English view"})
        notices = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertEqual(notices, [self.translated("Saved view '%(name)s'.", name="My English view")])

    def test_english_creation_titles_remain_english(self):
        self.client.cookies["django_language"] = "en"
        for route, title in [("contact_create", "New contact"), ("organization_create", "New company")]:
            self.assertEqual(self.client.get(reverse(route)).context["title"], title)
