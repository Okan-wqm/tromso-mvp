"""The new look behind ?ui=next (core/ui.py, templates/app_base.html): the cookie that keeps it, <html data-ui>, the status
strip from the real readers, the menu group over the title."""
import re
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.urls import reverse

from alarms import read as alarms_read
from alarms.models import Alarm
from alarms.tests import D, AlarmsCase
from core import ui
from farm.models import WaterLimit
from farm.tests.helpers import point_of, role, stock_fish
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


class StripLinkTests(TestCase):
    """Each count of the strip leads to the page that lists what it counts (core.ui.alarms_item), and one wording of an
    Attention (core.ui.attention_words)."""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.watcher = get_user_model().objects.create_user('watcher', password='x')     # Alarms, not Monitoring
        self.watcher.groups.add(role('Alarm watchers', 'view_alarm'))
        self.alarms, self.monitor = reverse('alarms:alarm_list'), reverse('monitoring:monitor')

    def test_the_words_of_an_attention_in_the_strips_order(self):
        every = alarms_read.Attention(alarms=2, alarms_critical=1, critical=3, warning=4, blind=5, unjudged=6, unreadable=7)
        self.assertEqual(ui.attention_words(every), [
            (ui.ALARMS, '2 open alarms'), (ui.UNITS, '3 units critical'), (ui.UNITS, '7 units cannot be read'),
            (ui.UNITS, '4 units with a warning'), (ui.UNITS, '5 units with no recent data'),
            (ui.UNITS, '6 units with no limit')])
        one = alarms_read.Attention(alarms=1, critical=1, warning=1, blind=1, unjudged=1, unreadable=1)
        self.assertEqual([text for _what, text in ui.attention_words(one)], [
            '1 open alarm', '1 unit critical', '1 unit cannot be read', '1 unit with a warning',
            '1 unit with no recent data', '1 unit with no limit'])
        self.assertEqual(ui.attention_words(alarms_read.Attention()), [])
        self.assertEqual(ui.attention_words(alarms_read.Attention(warning=19, critical=1)),
                         [(ui.UNITS, '1 unit critical'), (ui.UNITS, '19 units with a warning')])

    def test_the_words_are_translated(self):
        from django.utils import translation
        for language in ('nb', 'tr'):
            with translation.override(language):
                words = [text for _what, text in ui.attention_words(alarms_read.Attention(alarms=1, critical=2))]
            self.assertNotIn('open alarm', words[0], language)
            self.assertNotIn('units critical', words[1], language)

    def test_units_only_lead_to_monitoring(self):
        item = ui.alarms_item(alarms_read.Attention(critical=1, warning=19), self.admin)
        self.assertEqual((item['url'], item['text'], item['status'], item.get('parts')),
                         (self.monitor, '1 unit critical · 19 units with a warning', 'critical', None))

    def test_alarms_only_lead_to_the_alarms_page(self):
        item = ui.alarms_item(alarms_read.Attention(alarms=1, alarms_critical=1), self.admin)
        self.assertEqual((item['url'], item['text'], item['status'], item.get('parts')),
                         (self.alarms, '1 open alarm', 'critical', None))

    def test_nothing_says_no_open_alarms_and_leads_to_the_alarms_page(self):
        item = ui.alarms_item(alarms_read.Attention(), self.admin)
        self.assertEqual((item['url'], item['text'], item['status']), (self.alarms, 'No open alarms', ''))

    def test_both_one_link_each(self):
        item = ui.alarms_item(alarms_read.Attention(alarms=1, critical=1, blind=2), self.admin)
        self.assertEqual(item['url'], '')
        self.assertEqual(item['text'], '1 open alarm · 1 unit critical · 2 units with no recent data')
        self.assertEqual([(part['what'], part['text'], part['url']) for part in item['parts']],
                         [(ui.ALARMS, '1 open alarm', self.alarms),
                          (ui.UNITS, '1 unit critical · 2 units with no recent data', self.monitor)])

    def test_units_are_plain_words_for_a_person_who_may_not_open_monitoring(self):
        item = ui.alarms_item(alarms_read.Attention(critical=1), self.watcher)
        self.assertEqual((item['url'], item['text'], item['status']), ('', '1 unit critical', 'critical'))
        item = ui.alarms_item(alarms_read.Attention(alarms=1, critical=1), self.watcher)
        self.assertEqual([(part['text'], part['url']) for part in item['parts']],
                         [('1 open alarm', self.alarms), ('1 unit critical', '')])
        html = render_to_string('core/_strip.html', {'items': [item]})
        self.assertIn(f'<a class="ui-strip-link" href="{self.alarms}" data-strip-part="alarms">1 open alarm</a>', html)
        self.assertIn('<span data-strip-part="units">1 unit critical</span>', html)
        self.assertNotIn(self.monitor, html)
        html = render_to_string('core/_strip.html', {'items': [ui.alarms_item(alarms_read.Attention(critical=1),
                                                                               self.watcher)]})
        self.assertIn('<span class="ui-strip-item" data-strip="alarms" data-status="critical">', html)


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
        """The strip's alarms item, from its start to the next item."""
        response = self.client.get(reverse('core:ui_strip'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        start = html.rindex('<', 0, html.index('data-strip="alarms"'))
        return html[start:html.rindex('<', 0, html.index('data-strip="on_site"', start))]

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

    def test_a_red_strip_leads_to_a_page_that_lists_the_unit_it_counts(self):
        """The owner's report (2026-11-24): the strip was red from the cards' judgement, with no alarm open (the engine
        not running), and led to the Alarms page, which was empty. Units lead to Monitoring, which lists the unit, and
        the Alarms page names them too."""
        self.limits()
        self.water(ph='5.5', temperature_c=9, oxygen_mg_l=10)
        html = self.fragment()
        monitor = reverse('monitoring:monitor')
        self.assertIn(f'<a class="ui-strip-item" href="{monitor}" data-strip="alarms" data-status="critical">', html)
        self.assertNotIn(reverse('alarms:alarm_list'), html)
        page = self.client.get(monitor, {'full': '1'}).content.decode()    # the cards as the server draws them
        self.assertIn(self.t1.code, page)
        self.assertIn(f'data-key="card:{self.t1.pk}" data-state="critical"', page)
        for look in ('classic', 'next'):                                 # the Alarms page is not empty in either look
            listing = self.client.get(reverse('alarms:alarm_list'), {'ui': look}).content.decode()
            self.assertIn('No alarm is open.', listing)
            self.assertIn('On the Monitoring screen: 1 unit critical. 1 unit with critical or warning water has no open '
                          'alarm.', listing)
            self.assertNotIn('yet', listing[listing.index('data-units-note'):listing.index('</p>', listing.index('data-units-note'))])
            self.assertIn(f'<a href="{monitor}">See them on Monitoring</a>', listing)

    def test_the_alarms_page_says_nothing_of_units_when_none_needs_a_look(self):
        self.limits()
        self.water(ph='7.2', temperature_c=9, oxygen_mg_l=10)
        listing = self.client.get(reverse('alarms:alarm_list')).content.decode()
        self.assertNotIn('data-units-note', listing)

    def test_the_alarms_page_promises_nothing_for_a_rung_the_engine_never_alarms_on(self):
        """Review of the follow-up, M1: a unit with no limit (or blind, over capacity, weigh now) never gets an alarm, so
        the page names it and says nothing of alarms."""
        self.water(ph='7.2', temperature_c=9, oxygen_mg_l=10)            # no temperature or oxygen limit: unjudged
        self.assertFalse(Alarm.objects.exists())
        found = alarms_read.attention()
        self.assertEqual((found.unjudged, found.unalarmed, found.alarms), (1, 0, 0))
        listing = self.client.get(reverse('alarms:alarm_list')).content.decode()
        note = listing[listing.index('data-units-note'):listing.index('</p>', listing.index('data-units-note'))]
        self.assertIn('On the Monitoring screen: 1 unit with no limit.', note)
        self.assertNotIn('alarm', note)                                  # no sentence about alarms at all

    def test_the_unalarmed_units_are_counted_by_their_own_alarms_not_the_farms(self):
        """An open alarm elsewhere (a farm-wide system alarm) does not hide that a critical unit has none of its own."""
        self.limits()
        self.water(ph='5.5', temperature_c=9, oxygen_mg_l=10)
        Alarm.objects.create(source='system', parameter='sensors_failed', severity='critical', opened_at=self.now,
                             summary='The live water values (the sensors) cannot be read.')
        found = alarms_read.attention()
        self.assertEqual((found.alarms, found.critical, found.unalarmed), (1, 1, 1))
        listing = self.client.get(reverse('alarms:alarm_list')).content.decode()
        self.assertIn('1 unit with critical or warning water has no open alarm.', listing)

    def test_the_alarms_page_with_an_open_alarm_does_not_say_none_is_open(self):
        self.limits()
        self.water(ph='5.5', temperature_c=9, oxygen_mg_l=10)
        self.loop()
        listing = self.client.get(reverse('alarms:alarm_list')).content.decode()
        self.assertIn('On the Monitoring screen: 1 unit critical.', listing)
        self.assertNotIn('has no open alarm', listing)                      # the alarm is at T-01's point
        self.assertEqual(alarms_read.attention().unalarmed, 0)
        html = self.fragment()                                           # one item, one link per page
        self.assertIn('class="ui-strip-item ui-strip-split" data-strip="alarms" data-status="critical"', html)
        self.assertRegex(html, rf'<a class="ui-strip-link" href="{reverse("alarms:alarm_list")}" data-strip-part="alarms">'
                               r'\d open alarms?</a><span aria-hidden="true"> · </span>'
                               rf'<a class="ui-strip-link" href="{reverse("monitoring:monitor")}" data-strip-part="units">'
                               r'1 unit critical</a>')

    def test_the_alarms_page_says_so_when_the_units_cannot_be_read(self):
        with mock.patch.object(alarms_read, 'attention', side_effect=RuntimeError('broken')):
            response = self.client.get(reverse('alarms:alarm_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'The units that need a look could not be read here.')

    def test_warning(self):
        self.limits()
        self.water(ph='6.2', temperature_c=9, oxygen_mg_l=10)        # between the critical 6.0 and the warning 6.5
        self.assertEqual(self.agree(), {self.t1.pk: 'warning'})
        self.assertIn('1 unit with a warning', self.fragment())

    def test_blind_a_fresh_ph_and_oxygen_without_a_temperature(self):
        """Review H1: a fresh pH hid the missing temperature; the card says no recent data, so does the strip (the oxygen
        is fresh: with fish and none fresh it is critical, owner decision of 2026-11-23, below)."""
        self.limits()
        self.water(ph='7.2', oxygen_mg_l=10)
        self.assertEqual(self.agree(), {self.t1.pk: 'blind'})
        html = self.fragment()
        self.assertNotIn('No open alarms', html)
        self.assertIn('data-status="warning"', html)
        self.assertIn('1 unit with no recent data', html)

    def test_critical_an_oxygen_three_days_old_with_fish(self):
        """A unit with fish whose oxygen has no fresh value is critical on the card and on the strip (owner decision of
        2026-11-23; it was "no recent data")."""
        self.limits()
        self.water(hours=72, oxygen_mg_l=10)
        self.water(ph='7.2', temperature_c=9)
        self.assertEqual(self.agree(), {self.t1.pk: 'critical'})
        self.assertIn('1 unit critical', self.fragment())

    def test_blind_a_temperature_three_days_old(self):
        self.limits()
        self.water(hours=72, temperature_c=9)
        self.water(ph='7.2', oxygen_mg_l=10)
        self.assertEqual(self.agree(), {self.t1.pk: 'blind'})
        self.assertIn('1 unit with no recent data', self.fragment())

    def test_critical_a_stocked_unit_with_no_point(self):
        """A unit with fish, no sampling point of its own and no system: nothing is known of its water, its oxygen none:
        critical on the card and on the strip (owner decision of 2026-11-23; it was "no recent data")."""
        self.limits()
        self.water(ph='7.2', temperature_c=9, oxygen_mg_l=10)
        bare = make_unit('T-02', self.hall)                           # no point (the fixture's T-01 has its middle one)
        stock_fish(self.keeper, bare, 500, '50', 10, species=self.salmon)
        self.assertEqual(self.agree(), {self.t1.pk: 'ok', bare.pk: 'critical'})
        html = self.fragment()
        self.assertNotIn('No open alarms', html)
        self.assertIn('1 unit critical', html)

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
        html = self.fragment()                                   # both, each a link to its own page
        self.assertRegex(html, r'>\d open alarms?</a><span aria-hidden="true"> · </span><a [^>]*>1 unit critical</a>')

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
        self.water(point=point_of(t2), ph='7.2', oxygen_mg_l=10)       # T-02: no temperature, no recent data
        Alarm.objects.create(source='system', parameter='sensors_failed', severity='critical', opened_at=self.now,
                             summary='The live water values (the sensors) cannot be read.')
        by_site = alarms_read.attention_by_site()
        self.assertEqual({site: (each.alarms, each.farm_wide, each.critical, each.blind) for site, each in by_site.items()},
                         {self.bergen.pk: (1, 1, 1, 0), self.oslo.pk: (1, 1, 0, 1)})
        self.assertEqual(alarms_read.attention(site=self.oslo).status, 'critical')     # the farm-wide alarm
        self.assertEqual((alarms_read.attention().alarms, alarms_read.attention().farm_wide), (1, 1))
        total, sites = alarms_read.attention_all()                    # the farm and its sites from one reading
        self.assertEqual((total, sites), (alarms_read.attention(), by_site))
        self.assertEqual((total.critical, total.blind, total.alarms), (1, 1, 1))

    def test_over_capacity_is_a_warning_on_the_strip_as_on_the_card(self):
        """Review LOW: a card that says Over capacity beside a strip that said "No open alarms"; one rule now
        (monitoring.read.upper_state)."""
        from farm.models import Tank
        self.limits()
        self.water(ph='7.2', temperature_c=9, oxygen_mg_l=10)
        from monitoring import read as monitoring_read
        from monitoring.cards import resolve
        # (max_biomass_kg is generated from the volume and the max density: 1,000 fish of 50 g are 50 kg)
        Tank.objects.filter(pk=self.t1.pk).update(max_density_kg_m3=D('0.01'))
        unit = Tank.objects.get(pk=self.t1.pk)
        card, = monitoring_read.cards([unit], self.boss, resolve.Choice())
        self.assertTrue(card.stock.over_capacity, unit.max_biomass_kg)
        self.assertEqual((card.state.key, card.state.reasons), ('warning', ('Over capacity',)))
        self.assertEqual(self.agree(), {self.t1.pk: 'warning'})
        self.assertIn('1 unit with a warning', self.fragment())

    @override_settings(WEIGH_SOON_DAYS=3, WEIGH_NOW_DAYS=5)
    def test_weigh_now_is_a_warning_on_the_strip_as_on_the_card(self):
        """The fish were weighed when stocked, 10 days ago: past WEIGH_NOW_DAYS the card says Weigh now, a warning."""
        from farm.models import Tank
        from monitoring import read as monitoring_read
        from monitoring.cards import resolve
        self.limits()
        self.water(ph='7.2', temperature_c=9, oxygen_mg_l=10)
        card, = monitoring_read.cards([Tank.objects.get(pk=self.t1.pk)], self.boss, resolve.Choice())
        self.assertEqual(card.drift, 'now')
        self.assertEqual(self.agree(), {self.t1.pk: 'warning'})
        self.assertIn('1 unit with a warning', self.fragment())

    def test_a_unit_whose_state_cannot_be_worked_out_is_counted_and_the_strip_still_answers(self):
        """Review M1 residual: the read was isolated per unit, the evaluation was not, so one unit whose evaluation
        raised made the whole fragment 500. Each unit is worked out on its own now and counted unreadable."""
        from farm.stock import dates
        from monitoring import read as monitoring_read
        self.limits()
        t2 = make_unit('T-02', self.hall)                    # no point, no system: blind
        stock_fish(self.keeper, t2, 500, '50', 10, species=self.salmon)
        self.water(ph='5.5', temperature_c=9, oxygen_mg_l=10)
        real = dates.local_today

        def failing(unit=None):                              # T-02's evaluation raises, T-01's does not
            if unit is not None and unit.pk == t2.pk:
                raise RuntimeError('broken evaluation')
            return real(unit)

        with mock.patch.object(dates, 'local_today', side_effect=failing):
            found = alarms_read.attention()
            html = self.fragment()
        self.assertEqual(dict(found.units), {self.t1.pk: 'critical', t2.pk: alarms_read.UNREADABLE})
        self.assertIn('1 unit critical · 1 unit cannot be read', html)
        with mock.patch.object(monitoring_read, 'water_rungs', side_effect=RuntimeError('broken evaluation')):
            found = alarms_read.attention()
            html = self.fragment()                                    # 200 (fragment() checks it)
        self.assertEqual((found.unreadable, found.critical, found.status), (2, 0, 'warning'))
        self.assertIn('2 units cannot be read', html)
        self.assertNotIn('No open alarms', html)

    def test_a_unit_whose_feeding_cannot_be_read_is_counted_unless_its_water_is_critical(self):
        from farm.feeding import read as feeding_read
        self.limits()
        t2 = make_unit('T-02', self.hall)
        stock_fish(self.keeper, t2, 500, '50', 10, species=self.salmon)
        self.water(ph='5.5', temperature_c=9, oxygen_mg_l=10)          # T-01 critical
        self.water(point=point_of(t2), ph='7.2', temperature_c=9, oxygen_mg_l=10)     # T-02 fine
        real = feeding_read.figures

        def failing(stock, *args, **kwargs):
            if t2.pk in stock or self.t1.pk in stock:
                raise RuntimeError('broken feeding')
            return real(stock, *args, **kwargs)

        with mock.patch.object(feeding_read, 'figures', side_effect=failing):
            found = alarms_read.attention()
        self.assertEqual(dict(found.units), {self.t1.pk: 'critical', t2.pk: alarms_read.UNREADABLE})

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
            alarms_read.attention_all()
        self.assertEqual(read.call_count, 1)

    def test_the_farm_and_its_sites_from_one_reading_without_the_cache(self):
        with mock.patch.object(alarms_read, '_snapshot', wraps=alarms_read._snapshot) as read:
            alarms_read.attention_all()
        self.assertEqual(read.call_count, 1)
