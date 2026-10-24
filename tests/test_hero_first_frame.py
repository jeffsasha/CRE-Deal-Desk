from html.parser import HTMLParser
from django.urls import reverse
from tests.base import DeskTestCase

class FirstFrameParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.words=[]
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if 'data-word' in attrs:
            self.words.append('hidden' not in attrs)

class HeroFirstFrameTests(DeskTestCase):
    def setUp(self):
        self.client.force_login(self.user('admin'))

    def test_only_one_rotating_word_is_visible_before_javascript(self):
        for language in ('en','zh-hans'):
            with self.subTest(language=language):
                self.client.cookies['django_language']=language
                html=self.client.get(reverse('hero')).content.decode()
                parser=FirstFrameParser()
                parser.feed(html)
                self.assertEqual(parser.words,[True,False,False,False])

    def test_hero_statistics_do_not_reset_to_zero_on_startup(self):
        html=self.client.get(reverse('hero')).content.decode()
        stats=html.split('<div class="hero-stats">',1)[1].split('<a class="hero-cta"',1)[0]
        self.assertNotIn('data-odo=',stats)
        self.assertNotIn('hv odo',stats)
