from html.parser import HTMLParser

from django.urls import reverse

from .base import DeskTestCase


class AppearanceChoices(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.choices = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("type") == "radio":
            self.choices.setdefault(attrs.get("name"), set()).add(attrs.get("value"))


class ThemeSettingsTests(DeskTestCase):
    def test_theme_choices_are_available_to_every_workspace_user(self):
        for role in ("broker", "read_only"):
            self.client.force_login(self.user(role))
            response = self.client.get(reverse("settings_index"))
            self.assertEqual(response.status_code, 200)
            choices = AppearanceChoices(response.content.decode()).choices
            self.assertEqual(choices.get("palette"), {'sunset', 'blue-grey', 'indigo', 'ultraviolet', 'minimal', 'ocean', 'teal-gold', 'lemon', 'rose', 'ice-orange', 'mint-violet', 'mecha'})
            self.assertEqual(choices.get("appearance"), {"light", "dark", "system"})

    def test_settings_fragment_retains_theme_controls_and_existing_settings(self):
        self.client.force_login(self.user("admin"))
        self.client.cookies["django_language"] = "zh-hans"
        response = self.client.get(reverse("settings_index"), HTTP_X_WORKSPACE_NAVIGATION="1")
        self.assertContains(response, "主题配色")
        self.assertContains(response, "紫夜原版")
        self.assertContains(response, "橙蓝")
        self.assertContains(response, f'href="{reverse("import_list")}"')
        self.assertNotContains(response, '<aside class="sidebar">')
        self.assertEqual(len(AppearanceChoices(response.content.decode()).choices["palette"]), 12)
