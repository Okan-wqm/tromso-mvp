"""The new look behind ?ui=next (core/ui.py, templates/app_base.html): the cookie that keeps it, <html data-ui>, the status
strip from the real readers, the menu group over the title."""
import re
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from alarms import read as alarms_read
from alarms.models import Alarm
from alarms.tests import D, AlarmsCase
from core import ui
from farm.models import WaterLimit
from farm.tests.helpers import role, stock_fish
from farm.tests.test_stock import make_unit
from farm.water import services as water


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

    @override_settings(ATTENTION_CACHE_SECONDS=0)
    def test_the_strip_says_the_alarms_the_people_on_site_and_the_companys_clock_and_is_polled_whole(self):
        html = self.client.get(reverse('home'), {'ui': 'next'}).content.decode()
        strip = html[html.index('<div class="ui-strip"'):]
        strip = strip[:strip.index('</div>')]
        # polled whole while it is shown, stale after one failed answer; the alarms are being read, never "no alarms"
        self.assertIn(f'data-poll="{reverse("core:ui_strip")}" data-poll-every="30" data-poll-state="loading" '
                      'data-poll-stale-after="1" data-poll-if-shown data-unread-text="Not updated: the alarms cannot be read"',
                      strip)
        self.assertIn(f'<a class="ui-strip-item" href="{reverse("alarms:alarm_list")}" data-strip="alarms">Reading the alarms…</a>',
                      strip)
        self.assertNotIn('No open alarms', strip)
        self.assertIn('<p class="sr-only" id="ui-strip-said" role="status"></p><p class="sr-only" id="ui-strip-alert" role="alert"></p>',
                      html)
        fragment = self.client.get(reverse('core:ui_strip')).content.decode()
        self.assertIn(f'href="{reverse("alarms:alarm_list")}" data-strip="alarms">No open alarms</a>', fragment)
        for part in (strip, fragment):                       # the clock and the muster count are polled with it (M3)
            self.assertIn(f'href="{reverse("hr:today")}" data-strip="on_site">0 on site</a>', part)
            self.assertRegex(part, r'data-strip="clock">\d\d\.\d\d\.\d{4}, \d\d:\d\d · Europe/Oslo</span>')

    def test_a_way_back_to_the_classic_look_in_the_user_menu(self):
        html = self.client.get(reverse('farm:site_list'), {'ui': 'next'}).content.decode()
        self.assertIn(f'<a class="menu-item" href="{reverse("farm:site_list")}?ui=classic" data-look="classic">'
                      'Back to the classic look</a>', html)
        self.assertNotIn('data-look="classic"', self.client.get(reverse('farm:site_list'), {'ui': 'classic'}).content.decode())

    def test_the_strip_shows_only_what_the_person_may_see(self):
        person = get_user_model().objects.create_user('worker', password='x')
        person.groups.add(role('Nobody'))
        self.client.force_login(person)
        html = self.client.get(reverse('home'), {'ui': 'next'}).content.decode()
        self.assertNotIn('data-strip="alarms"', html)
        self.assertNotIn('data-strip="alarms"', self.client.get(reverse('core:ui_strip')).content.decode())
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


@override_settings(ATTENTION_CACHE_SECONDS=0)
class StripAlarmsTests(AlarmsCase):
    """The strip says what the alarm engine and the monitoring cards say (alarms.read.attention): the open alarms, and
    every stocked unit on the cards' own ladder (monitoring.read.water_rungs), so a critical value whose alarm is not
    raised yet, a blind unit (old or missing temperature or oxygen, no point at all) and an unjudged one are never "No
    open alarms". Each rung's test compares the strip with the card of the same unit (`card.state.key`)."""

    def setUp(self):
        super().setUp()
        self.boss = get_user_model().objects.create_superuser('boss', 'boss@example.com', 'x')
        self.client.force_login(self.boss)

    def fragment(self):
        response = self.client.get(reverse('core:ui_strip'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        return html[html.index('data-strip="alarms"'):html.index('</a>', html.index('data-strip="alarms"'))]

    def agree(self):
        """{unit id: rung} of the strip, checked against the cards' state of the same units (a card's note is OK to the
        strip: a withdrawal, a ration the farm cannot work out, are not alarms)."""
        from farm.models import Tank
        from monitoring import read as monitoring_read
        from monitoring.cards import resolve
        cards = monitoring_read.cards(list(Tank.objects.all()), self.boss, resolve.Choice(), monitoring_read.ALL)
        on_cards = {card.unit.pk: ('ok' if card.state.key == 'note' else card.state.key)
                    for card in cards if card.state.key != 'empty'}
        strip = dict(alarms_read.attention().units)
        self.assertEqual(strip, on_cards)
        return strip

    def water(self, hours=1, point=None, **values):
        return water.record(self.keeper, point=point or self.mid1, measured_at=self.now - timedelta(hours=hours),
                            source='manual', values={key: D(str(value)) for key, value in values.items()})

    def limits(self):
        """Limits for the temperature and the oxygen too, so a full fresh sample can be OK (the fixture has pH only)."""
        WaterLimit.objects.create(species=self.salmon, parameter='temperature_c', water_type='any', warning_high=D(18))
        WaterLimit.objects.create(species=self.salmon, parameter='oxygen_mg_l', water_type='any', critical_low=D(5),
                                  warning_low=D(7))

    def test_critical_a_value_whose_alarm_is_not_raised_yet(self):
        self.limits()
        self.water(ph='5.5', temperature_c=9, oxygen_mg_l=10)        # pH under its critical low; no engine pass
        self.assertFalse(Alarm.objects.exists())
        self.assertEqual(self.agree(), {self.t1.pk: 'critical'})
        html = self.fragment()
        self.assertIn('data-status="critical"', html)
        self.assertIn('1 unit critical', html)

    def test_warning(self):
        self.limits()
        self.water(ph='6.2', temperature_c=9, oxygen_mg_l=10)        # between the critical 6.0 and the warning 6.5
        self.assertEqual(self.agree(), {self.t1.pk: 'warning'})
        self.assertIn('1 unit with a warning', self.fragment())

    def test_blind_a_fresh_ph_alone(self):
        """Review H1: a fresh pH hid the missing temperature and oxygen; the card says no recent data, so does the strip."""
        self.limits()
        self.water(ph='7.2')
        self.assertEqual(self.agree(), {self.t1.pk: 'blind'})
        html = self.fragment()
        self.assertNotIn('No open alarms', html)
        self.assertIn('data-status="warning"', html)
        self.assertIn('1 unit with no recent data', html)

    def test_blind_an_oxygen_three_days_old(self):
        self.limits()
        self.water(hours=72, oxygen_mg_l=10)
        self.water(ph='7.2', temperature_c=9)
        self.assertEqual(self.agree(), {self.t1.pk: 'blind'})
        self.assertIn('1 unit with no recent data', self.fragment())

    def test_blind_a_stocked_unit_with_no_active_point(self):
        self.limits()
        self.water(ph='7.2', temperature_c=9, oxygen_mg_l=10)
        type(self.mid1).objects.filter(unit=self.t1).update(is_active=False)
        self.assertEqual(self.agree(), {self.t1.pk: 'blind'})
        self.assertIn('1 unit with no recent data', self.fragment())

    def test_unjudged_no_limit_for_the_fish(self):
        self.water(ph='7.2', temperature_c=9, oxygen_mg_l=10)        # no temperature or oxygen limit (the fixture)
        self.assertEqual(self.agree(), {self.t1.pk: 'unjudged'})
        html = self.fragment()
        self.assertNotIn('No open alarms', html)
        self.assertIn('1 unit with no limit', html)

    def test_ok_says_no_open_alarms_only_then(self):
        self.limits()
        self.water(ph='7.2', temperature_c=9, oxygen_mg_l=10)
        self.assertEqual(self.agree(), {self.t1.pk: 'ok'})
        html = self.fragment()
        self.assertIn('>No open alarms', html)
        self.assertNotIn('data-status', html)

    def test_an_open_alarm_never_hides_the_units_behind_it(self):
        self.limits()
        self.water(ph='5.5', temperature_c=9, oxygen_mg_l=10)
        self.loop()
        self.loop(minutes=1)
        html = self.fragment()
        self.assertRegex(html, r'\d open alarms? · 1 unit critical')

    def test_a_unit_that_cannot_be_read_is_counted_and_the_others_still_are(self):
        """Review M1: one unit whose water read fails made the whole strip answer 500; it is read on its own, as the
        engine reads it, and counted as unreadable."""
        from farm.water import read as water_read
        self.limits()
        t2 = make_unit('T-02', self.hall, system=self.ras)
        stock_fish(self.keeper, t2, 500, '50', 10, species=self.salmon)
        self.water(ph='5.5', temperature_c=9, oxygen_mg_l=10)
        real = water_read.points_water

        def failing(units, *args, **kwargs):
            if any(unit.pk == t2.pk for unit in units):
                raise RuntimeError('broken unit')
            return real(units, *args, **kwargs)

        with mock.patch.object(water_read, 'points_water', side_effect=failing):
            found = alarms_read.attention()
            html = self.fragment()
        self.assertEqual((found.critical, found.unreadable), (1, 1))
        self.assertIn('1 unit critical · 1 unit cannot be read', html)

    def test_a_farm_wide_alarm_counts_on_every_site(self):
        """Review M4: an alarm on no site (the live values cannot be read) is about every site: each site's count holds
        it, marked farm-wide."""
        from farm.models import ProductionDepartment
        self.limits()
        hall_b = ProductionDepartment.objects.create(site=self.oslo, name='Hall B', code='HB')
        t2 = make_unit('T-02', hall_b)
        stock_fish(self.keeper, t2, 500, '50', 10, species=self.salmon)
        self.water(ph='5.5', temperature_c=9, oxygen_mg_l=10)
        Alarm.objects.create(source='system', parameter='sensors_failed', severity='critical', opened_at=self.now,
                             summary='The live water values (the sensors) cannot be read.')
        by_site = alarms_read.attention_by_site()
        self.assertEqual({site: (each.alarms, each.farm_wide, each.critical, each.blind) for site, each in by_site.items()},
                         {self.bergen.pk: (1, 1, 1, 0), self.oslo.pk: (1, 1, 0, 1)})
        self.assertEqual(alarms_read.attention(site=self.oslo).status, 'critical')     # the farm-wide alarm
        self.assertEqual((alarms_read.attention().alarms, alarms_read.attention().farm_wide), (1, 1))

    @override_settings(ATTENTION_CACHE_SECONDS=15)
    def test_one_read_for_every_viewer_in_its_time(self):
        """Review M2: the same answer for everyone, read once in 15 s however many pages ask."""
        from django.core.cache import cache
        cache.delete(alarms_read.CACHE_KEY)
        self.addCleanup(cache.delete, alarms_read.CACHE_KEY)
        with mock.patch.object(alarms_read, '_snapshot', wraps=alarms_read._snapshot) as read:
            self.fragment()
            self.fragment()
            alarms_read.attention_by_site()
        self.assertEqual(read.call_count, 1)
