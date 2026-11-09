"""Production › Overview (config.views.production_home, templates/production_home.html): the panel's landing page at the
start of a shift. What needs attention first (the critical and warning water points, the critical first, each value with
where it came from and how old it is; overdue tasks and reports), the day in four lines (stock, feed, water, tasks) each
saying its source and time, the reports due and the farm's structure, all of it only as far as the person's rights reach.
One primary action, Record water sample, for a person who may record one. No KPI tile row."""
import re
from datetime import date
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

from .helpers import role
from .test_water import D, WaterTestCase

from ..models import SamplingPoint

URL = reverse('production_home')


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
    def test_each_line_says_its_figures_where_they_come_from_and_when(self):
        self.stock()
        today = section(self.page(), 'Today on the farm')
        self.assertIn('1,000 fish', today)
        self.assertIn('in 1 of 2 units', today)
        self.assertIn('From the stock records at ', today)
        self.assertIn('From the latest samples and sensors at ', today)
        self.assertIn(f'href="{reverse("farm:production_units")}"', today)

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
                       reverse('tasks:task_list'), 'Needs attention', 'From the stock records'):
            self.assertNotIn(hidden, html)
        self.assertIn(reverse('farm:tank_list'), section(html, 'The farm'))

    def test_a_person_without_any_production_right_gets_a_word_not_a_blank(self):
        self.as_role()
        html = self.page()
        self.assertEqual(self.client.get(URL).status_code, 200)
        self.assertIn('Your role opens none of the production figures yet.', html)


class DesignTests(OverviewTestCase):
    def test_no_kpi_tile_row_and_no_placeholder(self):
        html = self.page()
        self.assertNotIn('class="tiles"', html)
        self.assertNotIn('The production figures will appear here.', html)

    def test_the_page_is_drawn_with_the_tailwind_build(self):
        html = self.page()
        self.assertRegex(html, r'href="/static/css/tw\.css\?v=\d+"')
        self.assertIn('tw:grid', html)

    def test_it_speaks_norwegian_and_turkish(self):
        self.stock()
        for language, words in {'nb': ('I dag på anlegget', 'Trenger oppfølging', '1\xa0000 fisk'),
                                'tr': ('Bugün çiftlikte', 'Dikkat gerektirenler', '1.000 balık')}.items():
            html = self.page(language)
            for word in words:
                with self.subTest(language=language, word=word):
                    self.assertIn(word, html)
