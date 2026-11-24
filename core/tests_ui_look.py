"""The new look behind ?ui=next (core/ui.py, templates/app_base.html): the cookie that keeps it, <html data-ui>, the status
strip from the real readers, the menu group over the title."""
import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from alarms.tests import AlarmsCase
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
        for look in ('next', 'classic'):        # no template comment is printed (a {# #} that spans lines is)
            self.assertNotIn('{#', self.client.get(reverse('home'), {'ui': look}).content.decode())

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
        # the alarms come as a fragment: until it is there they are being read, never "no alarms"
        self.assertIn(f'<span class="ui-strip-poll" data-poll="{reverse("core:ui_strip_alarms")}" data-poll-every="30" '
                      f'data-poll-state="loading"><a class="ui-strip-item" href="{reverse("alarms:alarm_list")}" '
                      'data-strip="alarms">Reading the alarms…</a></span>', strip)
        self.assertNotIn('No open alarms', strip)
        fragment = self.client.get(reverse('core:ui_strip_alarms')).content.decode()
        self.assertIn(f'href="{reverse("alarms:alarm_list")}" data-strip="alarms">No open alarms</a>', fragment)
        self.assertIn(f'href="{reverse("hr:today")}" data-strip="on_site">0 on site</a>', strip)
        self.assertRegex(strip, r'data-strip="clock">\d\d\.\d\d\.\d{4}, \d\d:\d\d · Europe/Oslo</span>')

    def test_the_strip_shows_only_what_the_person_may_see(self):
        person = get_user_model().objects.create_user('worker', password='x')
        person.groups.add(role('Nobody'))
        self.client.force_login(person)
        html = self.client.get(reverse('home'), {'ui': 'next'}).content.decode()
        self.assertNotIn('data-strip="alarms"', html)
        self.assertEqual(self.client.get(reverse('core:ui_strip_alarms')).status_code, 403)
        self.assertNotIn('data-strip="on_site"', html)
        self.assertIn('data-strip="clock"', html)

    def test_the_menu_group_stands_over_the_title(self):
        html = self.client.get(reverse('farm:site_list'), {'ui': 'next'}).content.decode()
        self.assertRegex(html, r'<span class="ui-head-group">Facility</span>')
        self.assertIn('<p class="eyebrow">Company<span aria-hidden="true"> › </span>Facility<span aria-hidden="true"> › </span>'
                      '<span class="ui-crumb-here">Sites</span></p>', html)
        overview = self.client.get(reverse('home')).content.decode()                           # group = panel: said once
        self.assertIn('<p class="eyebrow">Company<span aria-hidden="true"> › </span><span class="ui-crumb-here">Overview</span></p>', overview)
        classic = self.client.get(reverse('farm:site_list'), {'ui': 'classic'}).content.decode()
        self.assertNotIn('ui-head-group', classic)


class StripAlarmsTests(AlarmsCase):
    """The strip's alarms read the water as the alarm engine and the cards judge it (alarms.read.attention, unit_water):
    a critical value whose alarm is not raised yet (no engine pass since) is critical in the strip, never "no alarms"."""

    def setUp(self):
        super().setUp()
        self.boss = get_user_model().objects.create_superuser('boss', 'boss@example.com', 'x')
        self.client.force_login(self.boss)

    def fragment(self):
        return self.client.get(reverse('core:ui_strip_alarms')).content.decode()

    def test_a_critical_point_without_its_alarm_yet_is_critical(self):
        from alarms.models import Alarm
        self.sample(5.5)                                   # pH under its critical low of 6.0; no engine pass
        self.assertFalse(Alarm.objects.exists())
        html = self.fragment()
        self.assertNotIn('No open alarms', html)
        self.assertRegex(html, r'data-strip="alarms" data-status="critical"><svg[^>]*>.*</svg>1 unit critical</a>')

    def test_once_raised_it_is_counted_as_an_open_alarm(self):
        self.sample(5.5)
        self.loop()
        self.loop(minutes=1)
        self.assertRegex(self.fragment(), r'data-status="critical">.*\d open alarms?</a>')

    def test_a_warning_value_is_a_warning(self):
        self.sample(6.2)                                   # between the critical 6.0 and the warning 6.5
        self.assertRegex(self.fragment(), r'data-status="warning">.*1 unit with a warning</a>')

    def test_a_unit_with_fish_and_only_old_values_is_blind_not_fine(self):
        self.sample(7.2, hours=24 * 20)                    # old: past its freshness, inside the page's 30-day window
        html = self.fragment()
        self.assertNotIn('No open alarms', html)
        self.assertRegex(html, r'data-status="warning">.*1 unit without recent data</a>')

    def test_a_unit_with_fish_and_no_value_is_blind_not_fine(self):
        html = self.fragment()                             # T-01 holds fish and was never measured
        self.assertNotIn('No open alarms', html)
        self.assertRegex(html, r'data-status="warning">.*1 unit without recent data</a>')

    def test_nothing_open_and_good_water_says_no_open_alarms(self):
        self.sample(7.2)
        self.assertRegex(self.fragment(), r'data-strip="alarms">No open alarms</a>')
