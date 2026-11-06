"""How a card is drawn from its template (monitoring/cards/render.py and templates/monitoring/): the widgets in reading
order, placed by plain CSS grid, no query of their own; the frame always there; a widget the person may not read says
so, one whose source failed says "no data"; a value says its origin and age in words and "no data" rather than a dash;
the same template puts a widget in the same cell whatever the state; ids unique on a wall; ?state= does nothing on a
live page."""
import re
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from farm.tests.test_water_sources import FakeProvider
from farm.water import parameters, sources
from farm.water.evaluate import Status
from farm.water.read import Observation, Origin, PointWater, Reading

from .. import read
from ..cards import builtin, catalogue, render, resolve
from ..cards.resolve import Choice
from ..models import CardTemplate, CardTemplateAssignment
from . import D, MonitoringCase
from .golden import Tree

PAGE, CARDS = reverse('monitoring:monitor'), reverse('monitoring:cards')
POINT = SimpleNamespace(name='Middle', kind='middle', owner_type='unit')
NOW = timezone.now()
OPERATOR = builtin.OPERATOR_LAYOUT


def reading(code, value, hours=1, status=Status.OK, source='manual'):
    sample = SimpleNamespace(get_source_display=lambda: {'manual': 'Meter or test kit'}[source])
    observation = Observation(POINT, NOW - timedelta(hours=hours), Origin.MANUAL, {code: value}, sample=sample)
    return Reading(parameters.get(code), None if value is None else D(str(value)), observation, status=status)


def live(code, value, seconds, channel_no, origin=Origin.SENSOR, fresh_for=900):
    """A sensor's value on the middle point (owner rule A1), `seconds` old, fresh for `fresh_for` seconds."""
    observation = Observation(POINT, NOW - timedelta(seconds=seconds), origin, {code: D(value)}, channel_no=channel_no,
                              role='primary', fresh_for=fresh_for)
    return Reading(parameters.get(code), D(value), observation, status=Status.OK)


def articles(html):
    return {node.attrs['data-key']: node for node in Tree(html).root.walk()
            if node.tag == 'article' and node.attrs.get('data-key', '').startswith('card:')}


def widgets_of(article):
    return [node for node in article.walk() if 'w' in node.classes and node.tag == 'div']


class AgeTests(SimpleTestCase):
    def test_the_age_is_said_in_bands_so_a_card_changes_per_band_not_per_poll(self):
        for seconds, text in ((0, 'just now'), (9, 'just now'), (10, '10 s ago'), (59, '50 s ago'), (60, '1 min ago'),
                              (3599, '59 min ago'), (3600, '1 h ago'), (86399, '23 h ago'), (86400, '1 d ago'),
                              (3 * 86400 + 5, '3 d ago')):
            with self.subTest(seconds=seconds):
                self.assertEqual(render.age_text(seconds), text)


class FaceTests(SimpleTestCase):
    def test_a_value_says_its_figure_unit_status_origin_and_age_in_words(self):
        face = render.face(reading('oxygen_mg_l', '8.1'), NOW)
        self.assertEqual((face.value, face.label, face.status, face.origin, face.age, face.stale, face.missing),
                         ('8.10', 'O₂ (mg/L)', 'ok', 'Meter or test kit', '1 h ago', False, False))

    def test_no_reading_is_the_words_no_data_never_a_dash(self):
        face = render.face(None, NOW, parameters.get('ph'))
        self.assertEqual((face.value, face.missing, face.age), ('no data', True, ''))
        empty = render.face(reading('oxygen_mg_l', None), NOW)
        self.assertEqual((empty.value, empty.missing, empty.age), ('no data', True, '1 h ago'))

    def test_an_old_value_is_stale_by_the_parameters_own_freshness(self):
        self.assertTrue(render.face(reading('oxygen_mg_l', '8.1', hours=30), NOW).stale)
        self.assertFalse(render.face(reading('oxygen_mg_l', '8.1', hours=23), NOW).stale)

    def test_a_sensor_value_says_which_sensor_as_every_latest_value_does(self):
        # Owner rule A1: a live value says the sensor and its channel, as the water page and the Deffeyes window do.
        face = render.face(live('oxygen_mg_l', '8.4', seconds=40, channel_no=12), NOW)
        self.assertEqual((face.origin, face.age, face.stale), ('unit sensor #12', '40 s ago', False))
        system = render.face(live('temperature_c', '13.0', seconds=20, channel_no=3, origin=Origin.SYSTEM_SENSOR), NOW)
        self.assertEqual(system.origin, 'system sensor #3')

    def test_a_sensor_value_is_stale_by_its_channels_freshness_not_the_parameters_hours(self):
        self.assertTrue(render.face(live('oxygen_mg_l', '8.4', seconds=200, channel_no=12, fresh_for=180), NOW).stale)
        self.assertFalse(render.face(live('oxygen_mg_l', '8.4', seconds=170, channel_no=12, fresh_for=180), NOW).stale)


class BuildTests(MonitoringCase):
    def cards(self, layout=None, user=None, mode=None, **fields):
        if layout is not None:
            mine = CardTemplate.objects.create(name=f'L{CardTemplate.objects.count()}', layout=layout)
            CardTemplateAssignment.objects.filter(unit=None, system=None, system_type=None, species=None,
                                                  kind=None).update(template=mine)
        units = read.units_for(read.Params())
        return read.cards(units, user or self.reader, Choice(address=mode), **fields)

    def test_the_widgets_come_in_reading_order_and_cost_no_query(self):
        layout = {'schema': 1, 'widgets': [
            {'id': 'b', 'type': 'tasks', 'x': 6, 'y': 0, 'w': 6, 'h': 2},
            {'id': 'c', 'type': 'fish', 'x': 0, 'y': 2, 'w': 12, 'h': 5},
            {'id': 'a', 'type': 'tasks', 'x': 0, 'y': 0, 'w': 6, 'h': 2}]}
        card = self.cards(layout)[0]
        with self.assertNumQueries(0):
            views = render.build(card)
        self.assertEqual([view.id for view in views], ['a', 'b', 'c'])
        self.assertEqual((views[2].x, views[2].y, views[2].w, views[2].h, views[2].renderer),
                         (0, 2, 12, 5, 'monitoring/widgets/_fish.html'))
        self.assertEqual(views[0].dom_id, f'w-{card.unit.pk}-a')

    def test_an_empty_unit_shows_only_the_widgets_that_belong_on_an_empty_card(self):
        empty = self.cards(builtin.DETAILED_LAYOUT, occupancy='empty')[0]
        self.assertEqual([view.type for view in render.build(empty)], ['experiment', 'deffeyes'])

    def test_a_widget_the_person_may_not_read_says_so(self):
        user = self.as_person('stock-only', 'view_stockoperation')
        views = {view.type: view for view in render.build(self.cards(builtin.DETAILED_LAYOUT, user=user)[0])}
        self.assertEqual({kind: views[kind].hidden for kind in ('fish', 'feeding', 'water_table', 'health', 'tasks')},
                         {'fish': '', 'feeding': 'feeding', 'water_table': 'water', 'health': 'health', 'tasks': 'tasks'})

    def test_every_widget_that_can_be_placed_has_its_partial(self):
        for spec in catalogue.WIDGETS.values():
            if spec.enabled:
                with self.subTest(widget=spec.type):
                    self.assertTrue((Path(settings.BASE_DIR) / 'templates' / spec.renderer).is_file())


class PageTests(MonitoringCase):
    def page(self, layout=None, **query):
        if layout is not None:
            mine = CardTemplate.objects.create(name=f'P{CardTemplate.objects.count()}', layout=layout)
            CardTemplateAssignment.objects.filter(unit=None, system=None, system_type=None, species=None,
                                                  kind=None).update(template=mine)
        return self.client.get(PAGE, query).content.decode()

    def test_a_card_is_its_frame_and_a_grid_of_placed_widgets(self):
        html = self.page()
        card = articles(html)[f'card:{self.t2.pk}']
        self.assertEqual(card.attrs['data-template'], str(builtin.SIMPLE))
        grid = next(node for node in card.walk() if 'card-grid' in node.classes)
        placed = [node.attrs['class'] for node in widgets_of(card)]
        self.assertEqual(placed[0], 'w w-experiment gx-0 gy-0 gw-12 gh-1')       # placed by classes: no style attribute
        self.assertTrue(all('style' not in node.attrs for node in widgets_of(card)))
        self.assertEqual([each.split()[1] for each in placed], [f'w-{widget["type"]}' for widget in builtin.SIMPLE_LAYOUT['widgets']])
        self.assertTrue(grid is not None)
        self.assertIn('class="monitor-card-head"', html)                  # the frame is not a widget

    def test_a_value_widget_says_origin_and_age_and_no_data_in_words(self):
        self.sample(self.t2, hours=1, temperature_c='13.2', oxygen_mg_l='8.1')
        html = self.page(OPERATOR)
        card = articles(html)[f'card:{self.t2.pk}']
        text = ' '.join(card.text().split())
        self.assertIn('8.10', text)
        self.assertIn('Meter or test kit', text)
        self.assertIn('ago', text)
        tan = next(node for node in widgets_of(card) if {'gx-8', 'gy-3'} <= set(node.classes))
        self.assertIn('no data', ' '.join(tan.text().split()))
        self.assertNotIn('—', tan.text())

    def test_a_card_says_when_the_live_sensor_values_could_not_be_read(self):
        # Owner rule A1: when the sensors cannot be read, the water shown comes from the samples only, and the card says so.
        self.sample(self.t2, hours=1, temperature_c='13.2', oxygen_mg_l='8.1')
        broken = FakeProvider(broken=True)
        sources.register(broken)
        self.addCleanup(sources.unregister, broken)
        with self.assertLogs('farm.water.sources', 'ERROR'):
            html = self.page(builtin.DETAILED_LAYOUT)
        text = ' '.join(articles(html)[f'card:{self.t2.pk}'].text().split())
        self.assertIn('Live sensor values could not be read: samples only.', text)
        self.assertIn('8.10', text)                                              # the sample's value is still shown

    def test_a_bar_draws_its_limits_as_an_image_with_the_same_sentence_or_says_there_is_none(self):
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7, warning_high=12, critical_high=14)
        self.sample(self.t2, hours=1, temperature_c='13.2', oxygen_mg_l='8.1', ph='7.2')    # pH has a value but no limit
        layout = {'schema': 1, 'widgets': [
            {'id': 'w1', 'type': 'bar', 'x': 0, 'y': 0, 'w': 6, 'h': 2, 'bind': {'parameter': 'oxygen_mg_l'}},
            {'id': 'w2', 'type': 'bar', 'x': 6, 'y': 0, 'w': 6, 'h': 2, 'bind': {'parameter': 'ph'}}]}
        card = articles(self.page(layout))[f'card:{self.t2.pk}']
        svg = next(node for node in card.walk() if node.tag == 'svg' and node.attrs.get('role') == 'img')
        self.assertIn('8.10', svg.attrs['aria-label'])
        self.assertIn('6', svg.attrs['aria-label'])
        ph = widgets_of(card)[1]
        self.assertIn('no limit', ' '.join(ph.text().split()))

    def test_the_same_template_puts_each_widget_in_the_same_cell_whatever_the_state(self):
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7)
        self.sample(self.t1, hours=1, temperature_c='13', oxygen_mg_l='5')            # critical
        self.sample(self.t2, hours=1, temperature_c='13.2', oxygen_mg_l='8.1')       # fine
        cards = articles(self.page(OPERATOR))
        cells = [[node.attrs['style'] for node in widgets_of(cards[f'card:{unit.pk}'])] for unit in (self.t1, self.t2)]
        self.assertEqual(cells[0], cells[1])
        self.assertNotEqual(cards[f'card:{self.t1.pk}'].attrs['class'], cards[f'card:{self.t2.pk}'].attrs['class'])

    def test_ids_are_unique_and_no_widget_changes_the_tab_order(self):
        self.farm_of(4)
        for layout in (None, builtin.DETAILED_LAYOUT, OPERATOR):
            html = self.page(layout, occupancy='all')
            ids = re.findall(r'\sid="([^"]+)"', html)
            self.assertEqual(len(ids), len(set(ids)), [each for each in ids if ids.count(each) > 1][:3])
            self.assertNotRegex(html, r'tabindex="[1-9]')

    def test_state_in_the_address_changes_nothing_on_a_live_page(self):
        self.sample(self.t2, hours=1, temperature_c='13.2', oxygen_mg_l='8.1')
        plain, forced = self.page(), self.page(state='critical')
        strip = lambda html: re.sub(r'computed at [^<]+|after=[0-9a-f]+', '', html)
        self.assertEqual([node.attrs['class'] for node in articles(plain).values()],
                         [node.attrs['class'] for node in articles(forced).values()])
        self.assertNotIn('data-preview', forced)
        self.assertEqual(strip(self.client.get(CARDS).content.decode()),
                         strip(self.client.get(CARDS, {'state': 'critical'}).content.decode()))

    def test_a_failed_optional_source_draws_no_data_in_its_widgets_and_keeps_the_card(self):
        from unittest import mock
        read.FAILED_AT.clear()
        with mock.patch.object(read.tasks_read, 'per_unit', side_effect=RuntimeError('down')), \
                self.assertLogs('monitoring.read'):
            html = self.page(builtin.DETAILED_LAYOUT)
        card = articles(html)[f'card:{self.t2.pk}']
        tasks = next(node for node in widgets_of(card) if 'w-tasks' in node.classes)
        self.assertIn('no data', ' '.join(tasks.text().split()))


class AnnouncerTests(MonitoringCase):
    """frontend/announce.ts reads the state from the article and speaks through two regions outside the grid, in the
    person's language; the page carries every word it says."""

    def test_the_state_is_on_the_article_and_the_regions_sit_outside_the_grid(self):
        html = self.client.get(PAGE).content.decode()
        tree = Tree(html).root
        card = articles(html)[f'card:{self.t2.pk}']
        self.assertEqual(card.attrs['data-state'], card.attrs['class'].split('monitor-')[-1].split()[0])
        regions = {node.attrs['aria-live']: node for node in tree.walk() if 'data-announcer' in node.attrs}
        self.assertEqual(set(regions), {'assertive', 'polite'})
        grid = next(node for node in tree.walk() if 'monitor-grid' in node.classes)
        self.assertFalse([node for node in grid.walk() if 'data-announcer' in node.attrs])
        holder = next(node for node in tree.walk() if node.attrs.get('id') == 'monitor-announce')
        for key in ('data-announce-worse', 'data-announce-more', 'data-state-critical', 'data-state-warning',
                    'data-state-blind', 'data-state-note'):
            self.assertTrue(holder.attrs.get(key), key)
        self.assertIn('js/announce.js', html)
        self.assertNotIn('data-announcer', self.client.get(CARDS).content.decode())      # never inside the fragment


class GridStyleSheetTests(SimpleTestCase):
    """A widget's cell is given by classes (gx-, gy-, gw-, gh-) that static/css/card-grid.css turns into the grid's
    --x, --y, --w, --h: a style attribute on the widget would be blocked by the Content-Security-Policy. The style sheet is
    made from the catalogue (`render.grid_css`, `manage.py card_grid_css`) and covers every cell a valid layout can use."""

    def test_the_style_sheet_is_the_one_the_catalogue_makes(self):
        path = Path(settings.BASE_DIR) / 'static' / 'css' / 'card-grid.css'
        self.assertEqual(path.read_text(encoding='utf-8'), render.grid_css(), 'run manage.py card_grid_css')

    def test_it_covers_every_cell_and_size_a_valid_layout_can_use(self):
        css = render.grid_css()
        tallest = max(spec.max_h for spec in catalogue.WIDGETS.values())
        self.assertEqual(catalogue.ROWS, catalogue.MAX_WIDGETS * tallest)
        for x in range(catalogue.COLUMNS):
            self.assertIn(f'.gx-{x}{{--x:{x}}}', css)
        for size in range(1, catalogue.COLUMNS + 1):
            self.assertIn(f'.gw-{size}{{--w:{size}}}', css)
        for size in range(1, tallest + 1):
            self.assertIn(f'.gh-{size}{{--h:{size}}}', css)
        for y in range(catalogue.ROWS):
            self.assertIn(f'.gy-{y}{{--y:{y}}}', css)
        self.assertNotIn(f'.gy-{catalogue.ROWS}{{', css)

    def test_a_widget_below_the_last_row_is_out_of_bounds(self):
        from ..cards import validate
        widget = {'id': 'w1', 'type': 'tasks', 'x': 0, 'w': 6, 'h': 2}
        found = validate.validate({'schema': 1, 'widgets': [{**widget, 'y': catalogue.ROWS - 2}]})
        self.assertNotIn('bounds', [problem.code for problem in found])
        found = validate.validate({'schema': 1, 'widgets': [{**widget, 'y': catalogue.ROWS - 1}]})
        self.assertIn('bounds', [problem.code for problem in found])

    def test_the_pages_that_draw_cards_load_it(self):
        for name in ('monitoring/monitor.html', 'monitoring/template_form.html'):
            text = (Path(settings.BASE_DIR) / 'templates' / name).read_text(encoding='utf-8')
            self.assertIn("{% asset 'css/card-grid.css' %}", text, name)
