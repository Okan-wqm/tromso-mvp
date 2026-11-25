"""Production › Overview (config.views.production_home, templates/production_home.html): the panel's landing page at the
start of a shift, a dashboard. The day's figures as metric cards (stock, feed, water, tasks, reports), each card a link
saying its source and time; what needs attention in compact rows (the critical and warning water points, the critical
first, each value with where it came from and how old it is; overdue tasks and reports); beside it the farm's structure
as cards (departments, systems and their status, equipment, units and their kind) and the reports due. Every figure the
page showed before its redesign is still on it. All of it only as far as the person's rights reach. One primary action,
Record water sample, for a person who may record one."""
import re
from datetime import date
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

from .helpers import role
from .test_water import WaterTestCase

from ..models import SamplingPoint

URL = reverse('production_home')


def figure_of(html, key):
    """The figure of the metric card `data-metric="key"`, as text; None when there is no such card."""
    found = re.search(r'<a [^>]*data-metric="' + re.escape(key) + r'"[^>]*>(.*?)</a>', html, re.S)
    if not found:
        return None
    figure = re.search(r'<span [^>]*data-figure[^>]*>(.*?)</span>', found.group(1), re.S)
    return re.sub(r'<[^>]+>', '', figure.group(1)).strip() if figure else ''


def card_of(html, key):
    found = re.search(r'<a [^>]*data-metric="' + re.escape(key) + r'"[^>]*>.*?</a>', html, re.S)
    return found.group(0) if found else ''


def section(html, heading):
    """The <section> whose h2 says `heading`."""
    found = re.search(r'<section[^>]*>\s*<h2[^>]*>' + re.escape(heading) + r'</h2>.*?</section>', html, re.S)
    return found.group(0) if found else ''


class OverviewTestCase(WaterTestCase):
    def page(self, language=None):
        if language:
            self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = language
        return self.client.get(URL).content.decode()

    def as_role(self, *codenames):
        person = get_user_model().objects.create_user(f'p{len(codenames)}', f'p{len(codenames)}@example.com')
        person.groups.add(role(f'Role {len(codenames)}', *codenames))
        self.client.force_login(person)


class NeedsAttentionTests(OverviewTestCase):
    def setUp(self):
        super().setUp()
        self.stock()
        self.stock(self.t2)
        self.limit('co2_mg_l', warning_high=12, critical_high=15)
        # Both units' oxygen, fresh: a unit with fish and no fresh oxygen is critical (owner decision of 2026-11-23),
        # which these tests are not about.
        for unit in (self.t1, self.t2):
            self.sample(unit, hours=1, oxygen_mg_l='9')

    def test_the_critical_point_comes_first_with_its_value_origin_and_age(self):
        side = SamplingPoint.objects.create(unit=self.t2, name='East side outlet', kind='side_outlet')
        self.sample(self.t1, hours=1, co2_mg_l='13')                    # a warning at T-01's middle point
        self.sample(side, hours=2, co2_mg_l='15.6')                      # critical at T-02's side outlet
        attention = section(self.page(), 'Needs attention')
        self.assertIn('East side outlet', attention)
        self.assertLess(attention.index('East side outlet'), attention.index('T-01'))      # the critical first
        self.assertIn('data-status="critical"', attention)
        self.assertIn('data-status="warning"', attention)
        self.assertIn('15.6', attention)
        self.assertIn('<span class="wq-origin">manual</span>', attention)
        self.assertIn('<span class="wq-age">2\xa0hours ago</span>', attention)
        self.assertIn(f'href="{reverse("farm:water")}?point={side.pk}"', attention)
        self.assertIn('Nobody is alerted: critical values are shown here, not sent.', attention)

    def test_the_head_counts_the_critical_and_the_warnings_as_the_water_page_does(self):
        side = SamplingPoint.objects.create(unit=self.t2, name='East side outlet', kind='side_outlet')
        self.sample(self.t1, co2_mg_l='13')
        self.sample(side, co2_mg_l='15.6')
        water = self.client.get(reverse('farm:water')).context
        head = re.search(r'<div class="ui-head-status">.*?</div>', self.page(), re.S).group(0)
        self.assertIn(f'{water["critical_count"]} critical', head)
        self.assertIn(f'{water["warning_count"]} warning', head)

    def test_an_old_critical_value_says_no_recent_data(self):
        self.sample(self.t1, hours=72, co2_mg_l='15.6')
        self.assertIn('Critical, no recent data', section(self.page(), 'Needs attention'))

    def test_nothing_abnormal_says_so_in_words(self):
        self.sample(self.t1, co2_mg_l='8')
        self.sample(self.t2, co2_mg_l='8')        # both stocked units: one without a sample needs attention (M-20)
        html = self.page()
        attention = section(html, 'Needs attention')
        self.assertIn('Nothing needs attention', attention)
        self.assertIn('data-status="ok"', attention)
        self.assertNotIn('data-status="critical"', html)
        self.assertNotIn('data-status="warning"', html)

    def test_overdue_tasks_and_reports_are_listed_too(self):
        tasks = [{'key': 'due_today', 'label': 'Tasks due today', 'count': 2, 'url': '/tasks/'},
                 {'key': 'overdue', 'label': 'Overdue tasks', 'count': 3, 'url': '/tasks/'}]
        kind = mock.Mock(label='Planned slaughter')
        upcoming = {'rows': [mock.Mock(kind=kind, place='Fjord Seafood (N1234)', period=None, deadline=date(2026, 10, 29),
                                       overdue=True),
                             mock.Mock(kind=mock.Mock(label='Disease'), place='Tromsø Grow-out', period=None,
                                       deadline=date(2026, 12, 1), overdue=False)],
                    'more': 0, 'url': '/reports/', 'overdue': 1, 'duties': [], 'duties_url': '/reports/duties/'}
        with mock.patch('config.views.task_tiles', return_value=tasks), \
                mock.patch('config.views.overview_upcoming', return_value=upcoming):
            html = self.page()
        attention = section(html, 'Needs attention')
        self.assertIn('3 tasks are overdue', attention)
        self.assertIn('Planned slaughter, Fjord Seafood (N1234)', attention)
        self.assertNotIn('Tromsø Grow-out', attention)
        self.assertIn('Tromsø Grow-out', section(html, 'Reports due'))


class TodayTests(OverviewTestCase):
    def test_each_card_says_its_figure_where_it_comes_from_and_when(self):
        self.stock()
        today = section(self.page(), 'Today on the farm')
        self.assertEqual(figure_of(today, 'stock-fish'), '1,000')
        self.assertEqual(figure_of(today, 'stock-stocked'), '1')
        self.assertIn('of 2 units', card_of(today, 'stock-stocked'))
        self.assertIn('Stock records at ', card_of(today, 'stock-fish'))
        self.assertIn('Samples and sensors at ', card_of(today, 'water-critical'))
        self.assertIn(f'href="{reverse("farm:production_units")}"', card_of(today, 'stock-fish'))

    def test_only_an_abnormal_card_has_colour_and_it_says_the_word(self):
        self.limit('co2_mg_l', warning_high=12, critical_high=15)
        self.stock()
        self.sample(self.t1, co2_mg_l='15.6')
        today = section(self.page(), 'Today on the farm')
        critical, warning = card_of(today, 'water-critical'), card_of(today, 'water-warning')
        self.assertEqual(figure_of(today, 'water-critical'), '1')
        self.assertIn('data-status="critical"', critical)
        self.assertIn('<svg class="icon"', critical)                      # the glyph, and the word in the label
        self.assertIn('critical', re.sub(r'<[^>]+>', ' ', critical).lower())
        self.assertEqual(figure_of(today, 'water-warning'), '0')
        self.assertNotIn('data-status', warning)
        self.assertNotIn('<svg', warning)
        points = self.client.get(reverse('farm:water')).context['point_count']
        self.assertIn(f'of {points} sampling points', critical)

    def test_no_value_is_a_dash(self):
        today = section(self.page(), 'Today on the farm')
        self.assertNotIn('>—<', today)
        self.assertNotIn('>-<', today)


class RightsTests(OverviewTestCase):
    def test_the_one_primary_action_records_a_water_sample(self):
        html = self.page()
        self.assertEqual(html.count('data-variant="primary"'), 1)
        button = re.search(r'<a [^>]*data-variant="primary"[^>]*>', html).group(0)
        self.assertIn(f'href="{reverse("farm:water_record")}?next=%2Fproduction%2F"', button)
        self.assertIn('data-modal', button)

    def test_a_reader_of_the_water_gets_no_record_button(self):
        self.as_role('view_watermeasurement')
        html = self.page()
        self.assertNotIn('data-variant="primary"', html)
        self.assertNotIn(reverse('farm:water_record'), html)
        self.assertIn('Needs attention', html)

    def test_a_person_sees_only_what_their_rights_open(self):
        self.as_role('view_tank')
        html = self.page()
        for hidden in (reverse('farm:water'), reverse('farm:production_units'), reverse('farm:meal_board'),
                       reverse('tasks:task_list'), 'Needs attention', 'Stock records at', 'data-metric="stock-'):
            self.assertNotIn(hidden, html)
        self.assertIn(reverse('farm:tank_list'), section(html, 'The farm'))

    def test_a_person_without_any_production_right_gets_a_word_not_a_blank(self):
        self.as_role()
        html = self.page()
        self.assertEqual(self.client.get(URL).status_code, 200)
        self.assertIn('Your role opens none of the production figures yet.', html)


class OldFiguresTests(OverviewTestCase):
    """The figures of the overview before its redesign (b413dd8^: the stock, feed, water and task tiles, the farm's
    counts, the systems by status and the units by kind) are each a metric card with the same figure."""
    def test_every_figure_of_the_old_page_is_a_card_with_its_figure(self):
        self.client.force_login(get_user_model().objects.create_superuser('boss', 'boss@example.com', 'x'))
        self.stock()
        response = self.client.get(URL)
        html, context = response.content.decode(), response.context
        expected = {}
        for area, tiles in (('stock', 'stock_tiles'), ('feed', 'feeding_tiles'), ('tasks', 'task_tiles')):
            expected.update({f'{area}-{tile["key"]}': tile['count'] for tile in context[tiles]})
        expected['water-critical'] = context['water_tiles'][0]['count']
        expected.update({f'farm-{tile["key"]}': tile['count'] for tile in context['tiles']})
        expected.update({f'system-{item["value"]}': item['count'] for item in context['systems_by_status']})
        expected.update({f'kind-{item["value"]}': item['count'] for item in context['units_by_kind']})
        self.assertEqual(len(expected), 3 + 2 + 2 + 1 + 4 + 4 + 3)     # stock, feed, tasks, water, farm, statuses, kinds
        for key, figure in expected.items():
            with self.subTest(card=key):
                self.assertEqual(figure_of(html, key), str(figure))
        for key, figure in {'stock-fish': '1,000', 'stock-stocked': '1', 'farm-system': '1', 'farm-tank': '2',
                            'farm-productiondepartment': '1', 'system-operational': '1', 'system-offline': '0',
                            'kind-tank': '2', 'kind-cage': '0'}.items():
            with self.subTest(fixed=key):
                self.assertEqual(figure_of(html, key), figure)


class DesignTests(OverviewTestCase):
    def test_the_figures_are_metric_cards_each_a_link_with_its_source_and_no_placeholder(self):
        self.client.force_login(get_user_model().objects.create_superuser('boss', 'boss@example.com', 'x'))
        html = self.page()
        cards = re.findall(r'<a [^>]*data-metric="[^"]+"[^>]*>.*?</a>', html, re.S)
        self.assertGreaterEqual(len(cards), 10 + 4 + 4 + 3)
        for card in cards:
            with self.subTest(card=card[:80]):
                self.assertRegex(card, r'^<a [^>]*href="[^"#]+')
                self.assertIn('data-figure', card)
        for key in ('stock-fish', 'feed-today', 'water-critical', 'tasks-due_today', 'reports-due', 'farm-system'):
            with self.subTest(source=key):
                self.assertRegex(card_of(html, key), r'data-source[^>]*>[^<]* at \d')
        self.assertNotIn('class="tiles"', html)
        self.assertNotIn('The production figures will appear here.', html)

    def test_the_page_is_drawn_with_the_tailwind_build(self):
        html = self.page()
        self.assertRegex(html, r'href="/static/css/tw\.css\?v=\d+"')
        self.assertIn('tw:grid', html)

    def test_it_speaks_norwegian_and_turkish(self):
        self.stock()
        for language, words in {'nb': ('I dag på anlegget', 'Trenger oppfølging', '>Fisk<', '>1\xa0000<',
                                       'Beholdningsføringer kl. '),
                                'tr': ('Bugün çiftlikte', 'Dikkat gerektirenler', '>Balık<', '>1.000<',
                                       'Stok kayıtları, saat ')}.items():
            html = self.page(language)
            for word in words:
                with self.subTest(language=language, word=word):
                    self.assertIn(word, html)
