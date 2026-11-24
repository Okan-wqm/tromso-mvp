"""The page and the fragment: what a person sees, the fragment protocol (204 while nothing changed, 200 with the next
address), the mode round trip, the wall, the menu and the role matrix; and that a poll writes nothing."""
import re
from unittest import mock

from django.contrib.sessions.models import Session
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core import access, navigation
from core.dates import company_today
from core.models import AuditLog, Profile
from farm.models import FeedingRecord, StockOperation, WaterMeasurement

from .. import read
from ..cards import builtin
from . import MonitoringCase

PAGE, CARDS = reverse('monitoring:monitor'), reverse('monitoring:cards')
DETAILED_CARD = f'data-template="{builtin.DETAILED}"'


def keys(html):
    return re.findall(r'data-key="([^"]+)"', html)


class PageTests(MonitoringCase):
    def test_the_page_has_a_card_for_each_stocked_unit_in_the_farms_order_and_a_polled_grid(self):
        response = self.client.get(PAGE, {'full': '1'})
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertEqual(keys(html), ['band', f'card:{self.t1.pk}', f'card:{self.t2.pk}'])
        for text in ('data-poll="', 'data-poll-every="15"', 'data-poll-merge="data-key"', 'id="monitor-windows"',
                     'data-fullscreen', 'T-01', 'T-02', '2 of 3 units shown', 'computed at'):
            self.assertIn(text, html)
        self.assertNotIn('data-wall', html)
        self.assertEqual(response.context['title'], 'Monitoring')
        for text in (f'id="flip-{self.t1.pk}"', f'id="w-{self.t1.pk}-w5"'):
            self.assertIn(text, html)                                    # focus can be restored by id after a refresh

    def test_filters_occupancy_and_the_units_chosen_narrow_what_is_shown(self):
        shown = lambda **query: keys(self.client.get(PAGE, {**query, 'full': '1'}).content.decode())[1:]
        self.assertEqual(shown(q='t-02'), [f'card:{self.t2.pk}'])
        self.assertEqual(shown(occupancy='empty'), [f'card:{self.p1.pk}'])
        self.assertEqual(len(shown(occupancy='all')), 3)
        self.assertEqual(shown(units=str(self.t1.pk)), [f'card:{self.t1.pk}'])
        self.assertEqual(shown(kind='pond'), ['empty'])             # the pond holds no fish: stocked is the default, so nothing
        self.assertEqual(shown(site='not-a-site', kind='nonsense'), [f'card:{self.t1.pk}', f'card:{self.t2.pk}'])

    def test_simple_and_detailed_and_the_round_trip_of_the_toggle(self):
        simple = self.client.get(PAGE, {'full': '1'}).content.decode()
        self.assertNotIn(DETAILED_CARD, simple)
        self.assertNotIn('w-tasks', simple)
        detailed = self.client.get(PAGE, {'mode': 'detailed', 'full': '1'}).content.decode()
        self.assertEqual(detailed.count(DETAILED_CARD), 2)
        for text in ('w-tasks', 'w-health', 'Feed rate', 'Losses'):
            self.assertIn(text, detailed)
        # the link of one card flips it: its href is the page, its data-poll-url the fragment, for that state
        link = re.search(rf'<article[^>]*card:{self.t1.pk}.*?<a class="monitor-flip" id="[^"]+" href="([^"]+)" data-poll-url="([^"]+)">'
                         r'([^<]+)</a>', simple, re.S)
        href, poll, word = (item.replace('&amp;', '&') for item in link.groups())
        self.assertEqual((href, word), (f'{PAGE}?flip={self.t1.pk}', 'Detailed'))
        self.assertEqual(poll, f'{CARDS}?flip={self.t1.pk}')
        flipped = self.client.get(f'{href}&full=1').content.decode()
        self.assertEqual(flipped.count(DETAILED_CARD), 1)
        fragment = self.client.get(poll).content.decode()
        self.assertEqual(fragment.count(DETAILED_CARD), 1)
        self.assertEqual(keys(fragment), keys(flipped)[:4][:len(keys(fragment))])

    def test_a_card_shows_the_pages_figures_for_its_unit(self):
        self.sample(self.t2, hours=1, temperature_c='13.2', oxygen_mg_l='8.1', ph='7.2')
        html = self.client.get(PAGE, {'full': '1'}).content.decode()
        card = re.search(rf'<article[^>]*card:{self.t2.pk}.*?</article>', html, re.S).group(0)
        for text in ('12,000', '13.2', '8.10', '7.20', 'Deffeyes chart', 'State from'):
            self.assertIn(text, card)
        self.assertIn(f'data-window="{reverse("farm:water_unit_chart", args=[self.t2.pk])}"', card)
        # the chart lives in the window, never in a card: the only svg are the icons and the capacity bar (an SVG rectangle,
        # templates/farm/_capacity_bar.html, since the Content-Security-Policy allows no style attribute)
        self.assertEqual(card.count('<svg') - card.count('<svg class="capacity-bar'), 0)
        self.assertEqual(html.count('<svg'), html.count('class="icon"') + html.count('<svg class="capacity-bar'))

    def test_a_card_that_may_not_see_a_section_says_so_and_prints_no_value_of_it(self):
        # Values that no date on the page can spell: the oxygen was 8.1, printed "8.10", and the page says when the
        # fish were last weighed, 15 days back: "28.10.2026" on 12.11.2026, when this test failed for that alone.
        self.sample(self.t2, hours=1, temperature_c='13.2', oxygen_mg_l='8.47')
        shown = self.client.get(PAGE, {'mode': 'detailed', 'full': '1'}).content.decode()
        for text in ('13.2', '8.47'):
            self.assertIn(text, shown)                               # as the page prints them for who may see the water
        self.as_person('stock-only', 'view_stockoperation')
        html = self.client.get(PAGE, {'mode': 'detailed', 'full': '1'}).content.decode()
        for text in ('Feeding: not shown to you', 'Water: not shown to you', 'Health: not shown to you',
                     'Tasks: not shown to you', 'State from: Fish'):
            self.assertIn(text, html)
        for text in ('13.2', '8.47', 'Deffeyes chart', 'Ration'):
            self.assertNotIn(text, html)
        self.assertIn('12,000', html)                                # the fish are the stock right's

    def test_without_the_stock_right_the_page_and_the_fragment_are_forbidden_and_the_menu_has_no_entry(self):
        self.as_person('water-only', 'view_watermeasurement')
        self.assertEqual(self.client.get(PAGE).status_code, 403)
        self.assertEqual(self.client.get(CARDS).status_code, 403)
        self.assertNotContains(self.client.get(reverse('production_home')), reverse('monitoring:monitor'))

    def test_the_languages(self):
        for language, word in {'tr': 'İzleme', 'nb': 'Overvåking'}.items():
            Profile.objects.update_or_create(user=self.reader, defaults={'language': language})
            for url in (PAGE, CARDS):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
            self.assertContains(self.client.get(PAGE), word, msg_prefix=language)
            self.assertContains(self.client.get(PAGE), f'lang="{language}"')


class FragmentTests(MonitoringCase):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(read, 'TOKEN_BUCKET', 10 ** 9)          # the minute does not roll over under the test
        patch.start()
        self.addCleanup(patch.stop)

    def ask(self, query=''):
        return self.client.get(f'{CARDS}?{query}' if query else CARDS)

    def test_200_with_the_cards_and_the_next_address_then_204_while_nothing_changes(self):
        first = self.ask()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(keys(first.content.decode()), ['band', f'card:{self.t1.pk}', f'card:{self.t2.pk}'])
        self.assertEqual(first['Cache-Control'], 'no-store')
        after = first['X-Poll-Next']
        self.assertTrue(after.startswith(f'{CARDS}?after='))
        again = self.client.get(after)
        self.assertEqual((again.status_code, again.content, again['X-Poll-Next']), (204, b'', after))
        self.assertEqual(again['Cache-Control'], 'no-store')

    def test_a_change_gives_a_new_body_and_a_new_address(self):
        after = self.ask()['X-Poll-Next']
        self.mortality(self.batch, 1, days_ago=0)
        changed = self.client.get(after)
        self.assertEqual(changed.status_code, 200)
        self.assertNotEqual(changed['X-Poll-Next'], after)
        self.assertEqual(self.client.get(changed['X-Poll-Next']).status_code, 204)

    def test_the_address_keeps_the_state_and_the_fragment_has_no_shell(self):
        response = self.ask(f'mode=detailed&flip={self.t1.pk}&q=T-0&wall=1')
        self.assertIn(f'flip={self.t1.pk}', response['X-Poll-Next'])
        self.assertIn('wall=1', response['X-Poll-Next'])
        html = response.content.decode()
        for shell in ('<html', 'rail', 'Skip to content', 'id="monitor-windows"'):
            self.assertNotIn(shell, html)                           # no request: the shell's context never ran
        self.assertNotIn('<svg', html.replace('<svg class="icon"', '').replace('<svg class="capacity-bar', ''))

    def test_the_fragment_is_the_pages_grid(self):
        page = self.client.get(PAGE, {'full': '1'})
        token = read.change_token(self.reader, '')
        inner = re.search(r'<div class="monitor-grid"[^>]*>(.*)</div>\s*<div id="monitor-windows"', page.content.decode(), re.S)
        self.assertIsNotNone(inner)
        self.assertEqual(keys(inner.group(1)), keys(self.ask().content.decode()))
        self.assertIn(token, re.search(r'class="monitor-grid"[^>]*data-poll="([^"]+)"', page.content.decode()).group(1))

    def test_a_poll_writes_no_row_and_no_audit_entry(self):
        tables = (AuditLog, StockOperation, FeedingRecord, WaterMeasurement)
        before = [model.all_objects.count() if hasattr(model, 'all_objects') else model.objects.count() for model in tables]
        after = self.ask()['X-Poll-Next']
        with CaptureQueriesContext(connection) as log:
            self.client.get(after)                                  # the 204 path
            self.ask(f'mode=detailed&units={self.t1.pk}')           # a 200 path
        verbs = {query['sql'].lstrip().split(None, 1)[0].upper() for query in log}
        self.assertLessEqual(verbs, {'SELECT', 'WITH', 'SAVEPOINT', 'RELEASE'})      # savepoints: the chips' fail-open, no write
        now = [model.all_objects.count() if hasattr(model, 'all_objects') else model.objects.count() for model in tables]
        self.assertEqual(now, before)

    def test_a_source_the_state_needs_that_fails_is_a_503_that_keeps_the_last_picture(self):
        with mock.patch.object(read.stock_read, 'stock_of', side_effect=RuntimeError('down')):
            for url in (CARDS, f'{PAGE}?full=1'):
                response = self.client.get(url)
                self.assertEqual((response.status_code, response['Cache-Control']), (503, 'no-store'), url)
                self.assertNotIn(b'data-key="card:', response.content)

    def test_a_source_the_state_needs_that_fails_is_logged_with_its_name_and_cause_once_a_minute(self):
        """F-025: the 503 is never silent: the source and the error with its trace are logged, at most once a minute per
        source, so a wall that polls every 15 s does not flood the log."""
        read.FAILED_AT.clear()
        for name, target in (('stock', 'stock_read.stock_of'), ('water', 'water_read.points_water'),
                             ('events', 'health_read.open_events')):
            owner, attribute = target.split('.')
            with self.subTest(source=name), \
                    mock.patch.object(getattr(read, owner), attribute, side_effect=RuntimeError(f'{name} is down')):
                with self.assertLogs('monitoring.read', 'ERROR') as logged:
                    self.assertEqual(self.client.get(CARDS).status_code, 503)
                self.assertEqual(len(logged.records), 1)
                record = logged.records[0]
                self.assertIn(f'The {name} source', record.getMessage())
                self.assertIn(f'RuntimeError: {name} is down', logged.output[0])     # the trace and the cause
                with self.assertNoLogs('monitoring.read', 'ERROR'):
                    self.assertEqual(self.client.get(CARDS).status_code, 503)        # within the minute: once

    def test_the_204_path_costs_a_session_the_rights_and_two_revision_queries(self):
        after = self.ask()['X-Poll-Next']
        self.client.get(after)
        with CaptureQueriesContext(connection) as log:
            self.client.get(after)
        tables = ' '.join(query['sql'] for query in log)
        for table in ('"stock_movements"', '"water_measurements"', '"feeding_records"', '"batches"'):
            self.assertNotIn(table, tables)
        self.assertLessEqual(len(log), 8)

    def test_the_counts_do_not_grow_with_the_units_on_the_page(self):
        self.ask()
        small = len(self.count_queries())
        self.farm_of(12)
        self.ask()
        self.assertEqual(len(self.count_queries()), small)

    def count_queries(self):
        with CaptureQueriesContext(connection) as log:
            self.ask('mode=detailed')
        return list(log)


class WallTests(MonitoringCase):
    def test_a_wall_page_marks_the_document_and_keeps_its_session_once_a_day(self):
        html = self.client.get(PAGE, {'wall': '1'}).content.decode()
        self.assertRegex(html, r'<html lang="en" data-theme="[a-z]+" data-wall>')         # (core/theme.py)
        self.assertIn('data-fullscreen', html)                           # the wall keeps its Full screen button ...
        self.assertIn('Leave the wall', html)                            # ... and a way out
        self.assertIn('wall=1', re.search(r'class="monitor-grid"[^>]*data-poll="([^"]+)"', html).group(1))
        self.assertEqual(self.client.session['monitoring_wall_day'], company_today().isoformat())   # the company's day
        key = self.client.session.session_key
        first = Session.objects.get(pk=key).expire_date
        self.client.get(PAGE, {'wall': '1'})                        # the same day: no write
        self.assertEqual(Session.objects.get(pk=key).expire_date, first)
        session = self.client.session
        session['monitoring_wall_day'] = '2026-01-01'               # a day ago: extended again
        session.save()
        self.client.get(f'{CARDS}?wall=1')
        self.assertEqual(self.client.session['monitoring_wall_day'], company_today().isoformat())   # the company's day

    def test_a_page_that_is_not_a_wall_does_not_touch_the_session(self):
        self.client.get(PAGE)
        self.client.get(CARDS)
        self.assertNotIn('monitoring_wall_day', self.client.session)


class MenuAndRolesTests(MonitoringCase):
    def test_the_entry_follows_production_units_and_production_units_keeps_the_title(self):
        place = navigation.place('farm.view_stockoperation')
        self.assertEqual(str(place.entry.label), 'Production units')
        page = self.client.get(reverse('farm:production_units'))
        self.assertContains(page, '<h1>Production units</h1>', html=True)
        html = self.client.get(PAGE).content.decode()
        self.assertLess(html.index('title="Production units"'), html.index('title="Monitoring"'))
        self.assertIn('aria-current="page"', re.search(r'<a class="rail-link"[^>]*title="Monitoring"[^>]*>', html).group(0))
        self.assertNotIn('aria-current', re.search(r'<a class="rail-link"[^>]*title="Production units"[^>]*>', html).group(0))

    def test_there_is_no_area_of_its_own_the_stock_right_reads_the_page(self):
        labels = [str(area.label) for area in access.areas()]
        self.assertIn('Production units', labels)
        self.assertEqual([label for label in labels if label.startswith('Monitoring')], ['Monitoring boards'])
        self.assertEqual({source.name: source.permission for source in read.SOURCES}['stock'], 'farm.view_stockoperation')
