"""The Sensors pages in the new look (?ui=next) on THE test world (core/test_world.py `world` and `sensors_world`, the clock
at its MOMENT): every tab's list and Live values, Dead letters and Alarm events drawn by the shared list page (island
`list-page`), Overview by its own island; each says everything its classic page says (core.pagesays) in English,
Norwegian and Turkish, nothing on it opens the classic dialog, and its props are kept for the browser test
(frontend/test/prodrest.pages.ts, .build/island-props by core/island_props.py: never a recording of a real database)."""
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.island_props import keep, props_of
from core.pagesays import unsaid
from core.test_world import MOMENT, sensors_world, world
from core.testing import FrozenClock

MANIFEST = str(Path(__file__).resolve().parents[2] / 'core' / 'testdata' / 'islands-prodrest-manifest.json')

# {name: (route, query, island)}: every Sensors page this branch draws in the new look (Charts is Tank › Water's branch's).
PAGES = {
    'sensors-connections': ('sensors:connection_list', {}, 'list-page'),
    'sensors-formats': ('sensors:payloadformat_list', {}, 'list-page'),
    'sensors-devices': ('sensors:device_list', {}, 'list-page'),
    'sensors-devices-unplaced': ('sensors:device_list', {'placed': 'no'}, 'list-page'),
    'sensors-channels': ('sensors:channel_list', {}, 'list-page'),
    'sensors-credentials': ('sensors:credential_list', {}, 'list-page'),
    'sensors-bindings': ('sensors:binding_list', {}, 'list-page'),
    'sensors-rules': ('sensors:alarmrule_list', {}, 'list-page'),
    'sensors-live': ('sensors:live', {}, 'list-page'),
    'sensors-dead': ('sensors:dead_letters', {}, 'list-page'),
    'sensors-dead-all': ('sensors:dead_letters', {'show': 'all'}, 'list-page'),
    'sensors-events': ('sensors:alarm_events', {}, 'list-page'),
    'sensors-home': ('sensors:home', {}, 'sensors-home'),
}
SHOTS = {'sensors-devices', 'sensors-channels', 'sensors-bindings', 'sensors-rules', 'sensors-live', 'sensors-dead-all',
         'sensors-events', 'sensors-home', 'sensors-connections', 'sensors-formats', 'sensors-credentials'}


@override_settings(ISLANDS_MANIFEST=MANIFEST)
class SensorsPagesNextTests(FrozenClock, TestCase):
    NOW = MOMENT

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
        made = world(cls.admin, Client())
        refused = [each for each in made if each.rsplit(': ', 1)[-1].isdigit() and not each.endswith(': 302')]
        if refused:
            raise AssertionError(f'the test world was not built: {refused}')
        sensors_world(cls.admin)

    def setUp(self):
        self.client.force_login(self.admin)

    def apart(self, language):
        """What the new page says apart that the classic page says in one run: a payload format's time unit, which the
        classic list writes after its path ("/ts · Milliseconds since 1970") and the new one under it."""
        from django.utils import translation

        from sensors.models import PayloadFormat
        with translation.override(language):
            return {f'· {each.get_time_unit_display()}' for each in PayloadFormat.objects.exclude(time_path='')}

    def pages(self, route, query, language):
        self.client.cookies['django_language'] = language
        old = self.client.get(reverse(route), {**query, 'ui': 'classic'}).content.decode()
        new = self.client.get(reverse(route), {**query, 'ui': 'next'}).content.decode()
        return old, new

    def test_every_page_says_everything_its_classic_page_says_in_three_languages(self):
        from core.language import save_account_language
        for language in ('en', 'nb', 'tr'):
            save_account_language(self.admin, language)
            for name, (route, query, island) in PAGES.items():
                with self.subTest(page=name, language=language):
                    old, new = self.pages(route, query, language)
                    props = props_of(new, island)
                    self.assertNotIn('class="data-table"', new)
                    self.assertEqual(unsaid(old, props, new_html=new, ignore=self.apart(language)), [])
                    main = new[new.index('<main'):new.index('</main>')]
                    self.assertIsNone(re.search(r'\sdata-modal[\s>=]', main), 'nothing opens the classic dialog')
                    if island == 'list-page' and name != 'sensors-dead':
                        self.assertTrue(props['table']['rows'], 'the test world has rows on every list')
                    if name in SHOTS and (language == 'en' or name in ('sensors-devices', 'sensors-live')):
                        keep(f'{name}-{language}', {'island': island, 'props': props})

    def test_the_lists_say_the_worlds_facts(self):
        props = props_of(self.pages('sensors:device_list', {}, 'en')[1], 'list-page')
        rows = {row['cells']['device']['text']: row for row in props['table']['rows']}
        simulated = rows['Test simulated probe']
        self.assertEqual(simulated['cells']['device']['chips'], [{'kind': 'hold', 'text': 'Simulated'}])
        self.assertEqual(simulated['cells']['placed']['chip']['text'], 'Not placed')
        self.assertEqual([action['icon'] for action in simulated['actions']], ['target', 'pencil', 'trash'])
        live = props_of(self.pages('sensors:live', {}, 'en')[1], 'list-page')
        states = {row['cells']['channel']['text']: row['cells']['state'] for row in live['table']['rows']}
        self.assertEqual(states['PH']['chip'], {'kind': 'stale', 'text': 'Stale'})          # silent: never shown as fresh
        self.assertEqual(states['OXYGEN_MG_L']['chip'], {'kind': 'ok', 'text': 'Fresh'})
        stale = next(row for row in live['table']['rows'] if row['cells']['channel']['text'] == 'PH')
        self.assertEqual(stale['status'], 'warning')
        events = props_of(self.pages('sensors:alarm_events', {}, 'en')[1], 'list-page')
        [open_event, closed] = events['table']['rows']
        self.assertEqual(open_event['cells']['closed']['chip']['text'], 'Open')
        self.assertEqual([action['kind'] for action in open_event['actions']], ['post'])
        self.assertEqual(open_event['actions'][0]['href'], reverse('sensors:alarm_event_acknowledge', args=[open_event['key']]))
        self.assertEqual(closed['actions'], [])                     # acknowledged already
        self.assertIn('test.admin', closed['cells']['acknowledged']['text'])
        dead = props_of(self.pages('sensors:dead_letters', {'show': 'all'}, 'en')[1], 'list-page')
        self.assertEqual(len(dead['table']['rows']), 2)
        self.assertEqual({each['name'] for each in dead['toolbar']['filters']}, {'reason', 'show'})

    def test_a_place_s_bindings_lead_back_to_every_binding(self):
        from farm.models import Tank
        unit = Tank.objects.get(code='TT-01')
        old, new = self.pages('sensors:binding_list', {'place': f'unit:{unit.pk}'}, 'en')
        props = props_of(new, 'list-page')
        self.assertEqual(props['tabs']['tabs'][0]['href'], reverse('sensors:binding_list'))
        self.assertTrue(props['notices'])
        self.assertEqual(unsaid(old, props, new_html=new), [])

    def test_the_overview_says_the_ingest_is_alive_and_counts_the_setup(self):
        props = props_of(self.pages('sensors:home', {}, 'en')[1], 'sensors-home')
        figures = {tile['label']: tile['figure'] for tile in props['state']['tiles']}
        self.assertEqual(figures['Ingest'], 'Alive')
        self.assertEqual(figures['Open alarms'], '1')
        statuses = {tile['key']: tile['status'] for tile in props['state']['tiles']}
        self.assertEqual((statuses['ingest'], statuses['alarms']), (None, 'critical'))     # alive; an open alarm
        self.assertEqual(statuses['stale'], 'warning')                                     # the silent pH
        self.assertEqual(props['state']['tiles'][0]['sub'], 'Heartbeat 4 s ago')
        self.assertEqual([tile['key'] for tile in props['state']['tiles']][:3], ['ingest', 'online', 'stale'])
        self.assertTrue(props['setup']['tiles'])
