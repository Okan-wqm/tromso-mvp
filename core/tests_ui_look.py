"""The new look behind ?ui=next (core/ui.py, templates/app_base.html): the cookie that keeps it, <html data-ui>, the status
strip from the real readers, the menu group over the title."""
import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core import ui
from farm.tests.helpers import role


def html_tag(response):
    return re.search(r'<html[^>]*>', response.content.decode()).group(0)


class NewLookTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(self.admin)

    def test_the_classic_look_is_the_default(self):
        response = self.client.get(reverse('home'))
        self.assertNotIn('data-ui', html_tag(response))
        self.assertNotIn('ui-strip', response.content.decode())

    def test_ui_next_turns_it_on_and_a_cookie_keeps_it_until_ui_classic(self):
        response = self.client.get(reverse('home'), {'ui': 'next'})
        self.assertIn('data-ui="next"', html_tag(response))
        self.assertEqual(response.cookies[ui.COOKIE].value, 'next')
        self.assertEqual(response.cookies[ui.COOKIE]['samesite'], 'Lax')
        self.assertIn('data-ui="next"', html_tag(self.client.get(reverse('farm:site_list'))))      # the next page too
        response = self.client.get(reverse('farm:site_list'), {'ui': 'classic'})
        self.assertNotIn('data-ui', html_tag(response))
        self.assertEqual(response.cookies[ui.COOKIE].value, '')                                   # removed
        self.assertNotIn('data-ui', html_tag(self.client.get(reverse('home'))))

    def test_an_unknown_value_changes_nothing(self):
        response = self.client.get(reverse('home'), {'ui': '"><script>'})
        self.assertNotIn(ui.COOKIE, response.cookies)
        self.assertNotIn('data-ui', html_tag(response))

    def test_the_strip_says_the_open_alarms_the_people_on_site_and_the_companys_clock(self):
        html = self.client.get(reverse('home'), {'ui': 'next'}).content.decode()
        strip = html[html.index('class="ui-strip"'):]
        strip = strip[:strip.index('</div>')]
        self.assertIn(f'href="{reverse("alarms:alarm_list")}" data-strip="alarms">No open alarms</a>', strip)
        self.assertIn(f'href="{reverse("hr:today")}" data-strip="on_site">0 on site</a>', strip)
        self.assertRegex(strip, r'data-strip="clock">\d\d\.\d\d\.\d{4}, \d\d:\d\d · Europe/Oslo</span>')

    def test_the_strip_shows_only_what_the_person_may_see(self):
        person = get_user_model().objects.create_user('worker', password='x')
        person.groups.add(role('Nobody'))
        self.client.force_login(person)
        html = self.client.get(reverse('home'), {'ui': 'next'}).content.decode()
        self.assertNotIn('data-strip="alarms"', html)
        self.assertNotIn('data-strip="on_site"', html)
        self.assertIn('data-strip="clock"', html)

    def test_the_menu_group_stands_over_the_title(self):
        html = self.client.get(reverse('farm:site_list'), {'ui': 'next'}).content.decode()
        self.assertRegex(html, r'<span class="ui-head-group">Facility</span>')
        classic = self.client.get(reverse('farm:site_list'), {'ui': 'classic'}).content.decode()
        self.assertNotIn('ui-head-group', classic)
