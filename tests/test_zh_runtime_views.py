"""Runtime UI translation keeps record names intact in both languages."""
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils.translation import gettext, override

from core.models import HolidayCalendar

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
        for route, msgid in [("user_create", "New user"), ("stage_create", "Stage")]:
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

    def test_saved_view_notice_keeps_name(self):
        response = self.client.post(reverse("save_view"), {"area": "deals", "name": "My English view"})
        notices = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertEqual(notices, [self.translated("Saved view '%(name)s'.", name="My English view")])

    def test_english_creation_titles_remain_english(self):
        self.client.cookies["django_language"] = "en"
        for route, title in [("user_create", "New user"), ("stage_create", "Stage")]:
            self.assertEqual(self.client.get(reverse(route)).context["title"], title)
