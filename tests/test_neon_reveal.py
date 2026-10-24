from django.urls import reverse
from tests.base import DeskTestCase

class NeonRevealTests(DeskTestCase):
    def setUp(self):
        self.client.force_login(self.user('admin'))

    def test_tube_belongs_to_sticky_header(self):
        html = self.client.get(reverse('dashboard')).content.decode()
        header = html.split('<header class="topbar">', 1)[1].split('</header>', 1)[0]
        self.assertIn('data-neon-rail', header)

