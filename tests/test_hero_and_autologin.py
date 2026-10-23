"""Opening page, automatic sign-in for local single-user mode, and the owner's photo
(served from var/brand, never from static files)."""
import shutil
import tempfile
from pathlib import Path

from django.test import override_settings
from django.urls import reverse

from .base import DeskTestCase


class AutoLoginTests(DeskTestCase):
    def test_no_login_page_when_enabled(self):
        owner = self.user("admin", username="owner")
        self.user("broker", username="someone-else")
        with self.settings(AUTO_LOGIN=True):
            resp = self.client.get(reverse("dashboard"))
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.wsgi_request.user, owner)
            self.assertNotContains(resp, 'action="/accounts/logout/"')
            self.assertContains(resp, "https://github.com/jeffsasha")
            self.assertContains(resp, 'class="btn btn-exit" href="/"')  # exit back to the opening page
            self.assertRedirects(self.client.get("/accounts/login/"), reverse("hero"), fetch_redirect_response=False)

    def test_login_still_required_when_disabled(self):
        self.user("admin", username="owner")
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp["Location"])


class HeroTests(DeskTestCase):
    def setUp(self):
        self.client.force_login(self.user("admin", username="owner"))

    def test_hero_links_to_dashboard(self):
        resp = self.client.get(reverse("hero"))
        self.assertContains(resp, 'href="/dashboard/"')
        self.assertContains(resp, "data-skyline")
        self.assertContains(resp, "data-badge")
        self.assertContains(resp, "github.com/jeffsasha")
        self.assertContains(resp, 'data-photo=""')  # no photo in this test's data folder

    def test_photo_served_only_from_brand_folder(self):
        folder = Path(tempfile.mkdtemp())
        try:
            with override_settings(BRAND_DIR=folder):
                self.assertEqual(self.client.get(reverse("brand_photo")).status_code, 404)
                (folder / "photo.webp").write_bytes(b"RIFF0000WEBPVP8 ")
                resp = self.client.get(reverse("brand_photo"))
                self.assertEqual(resp.status_code, 200)
                html = self.client.get(reverse("hero")).content.decode()
                self.assertIn('data-photo="/brand/photo/?v=cutout"', html)
                self.assertIn('data-cutout=""', html)  # only the original exists
                self.assertIn('data-handle="@jeffsasha"', html)
                (folder / "photo-cutout.png").write_bytes(b"\x89PNG")
                self.assertIn('data-cutout="1"', self.client.get(reverse("hero")).content.decode())
        finally:
            shutil.rmtree(folder)

    def test_photo_is_not_in_static_files(self):
        static = Path(__file__).resolve().parent.parent / "static"
        self.assertFalse([p for p in static.rglob("photo.*")])
