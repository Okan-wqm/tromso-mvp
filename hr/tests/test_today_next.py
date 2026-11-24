"""Today & attendance, Team overview and Scheduling settings in the new look (hr.views.today behind ?ui=next): drawn by the server with the design system's classes,
so the one poll draws its board again (hr.views.today_board answers in the look the page is in). Held to the classic page
(core.pagesays) on the test world (core/test_world.py), its clock pinned, in three languages and under both mounts; the
stacked bar's parts are the board's own tiles and add up to Planned today; no style attribute and no dialog link."""
import json
import re
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core import stack
from core.pagesays import unsaid

PAGES = ('hr:today', 'hr:production_today')
MANIFEST = str(Path(__file__).resolve().parents[2] / 'core' / 'testdata' / 'islands-company-manifest.json')


def props_of(html, name):
    found = re.search(r'<script id="island-' + name + r'-1" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(found.group(1)) if found else None


@override_settings(ALLOWED_HOSTS=['localhost', 'testserver'], ISLANDS_MANIFEST=MANIFEST)
class TodayNextTests(TestCase):
    def setUp(self):
        from core.test_world import MOMENT, world
        clock = mock.patch('django.utils.timezone.now', return_value=MOMENT)
        clock.start()
        self.addCleanup(clock.stop)
        self.admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
        world(self.admin)
        self.client.force_login(self.admin)

    def test_the_new_page_says_everything_the_classic_page_says_in_three_languages_and_both_mounts(self):
        for name in PAGES:
            for language in ('en', 'nb', 'tr'):
                with self.subTest(page=name, language=language):
                    self.client.cookies['django_language'] = language
                    old = self.client.get(reverse(name), {'ui': 'classic'}).content.decode()
                    new = self.client.get(reverse(name), {'ui': 'next'}).content.decode()
                    self.assertIn('class="ui-stack"', new)
                    self.assertNotIn('class="tiles"', new)
                    self.assertEqual(unsaid(old, {}, new_html=new), [])
                    main = new[new.index('<main'):new.index('</main>')]
                    self.assertIsNone(re.search(r'\sstyle=', main), 'no style attribute: the policy refuses it')
                    self.assertIsNone(re.search(r'\sdata-modal[\s>=]', main), 'no link opens the classic dialog')

    def test_the_team_overview_and_the_scheduling_settings_say_all_their_classic_pages_say(self):
        for name in ('hr:overview', 'hr:production_overview', 'hr:schedulingsettings_list'):
            for language in ('en', 'nb', 'tr'):
                with self.subTest(page=name, language=language):
                    self.client.cookies['django_language'] = language
                    old = self.client.get(reverse(name), {'ui': 'classic'}).content.decode()
                    new = self.client.get(reverse(name), {'ui': 'next'}).content.decode()
                    self.assertIn('class="ui-plates"', new)
                    self.assertEqual(unsaid(old, {}, new_html=new), [])
                    main = new[new.index('<main'):new.index('</main>')]
                    self.assertIsNone(re.search(r'\sstyle=', main))
                    self.assertIsNone(re.search(r'\sdata-modal[\s>=]', main))

    def test_the_organisation_chart_island_says_all_the_classic_chart_says(self):
        for name in ('hr:orgchart', 'hr:production_orgchart'):
            for language in ('en', 'nb', 'tr'):
                with self.subTest(page=name, language=language):
                    self.client.cookies['django_language'] = language
                    old = self.client.get(reverse(name), {'ui': 'classic'}).content.decode()
                    new = self.client.get(reverse(name), {'ui': 'next'}).content.decode()
                    props = props_of(new, 'org-chart')
                    self.assertIsNotNone(props)
                    self.assertTrue(props['nodes'])
                    self.assertEqual(unsaid(old, props, new_html=new), [])

    def test_the_shift_schedule_island_says_all_the_classic_schedule_says(self):
        for name in ('hr:shiftassignment_list', 'hr:production_shiftassignment_list'):
            for language in ('en', 'nb', 'tr'):
                with self.subTest(page=name, language=language):
                    self.client.cookies['django_language'] = language
                    old = self.client.get(reverse(name), {'ui': 'classic'}).content.decode()
                    new = self.client.get(reverse(name), {'ui': 'next'}).content.decode()
                    props = props_of(new, 'roster')
                    self.assertIsNotNone(props)
                    self.assertTrue(props['grid']['rows'])
                    self.assertEqual(unsaid(old, props, new_html=new), [])

    def test_the_paint_posts_what_the_servers_batch_route_takes(self):
        from hr.models import Employee, Shift, ShiftAssignment
        props = props_of(self.client.get(reverse('hr:production_shiftassignment_list'), {'ui': 'next'}).content.decode(), 'roster')
        paint = props['grid']['paint']
        second = Employee.objects.get(employee_number='E-9002')
        row = next(row for row in props['grid']['rows'] if row['key'] == str(second.pk))
        empty = next(cell['key'] for cell in row['cells'] if cell['key'] and cell['add'])
        shift = Shift.objects.get(code='TD')
        self.assertIn({'value': str(shift.pk), 'label': 'TD', 'title': 'Test day shift'}, paint['choices'])
        response = self.client.post(paint['action'], {'csrfmiddlewaretoken': paint['csrfToken'], 'next': paint['next'],
                                                      'shift': str(shift.pk), 'cells': [empty]})
        self.assertEqual(response.status_code, 302)
        day = empty.split(':', 1)[1]
        self.assertEqual(ShiftAssignment.objects.get(employee=second, day=day).shift, shift)

    def test_the_polled_board_answers_in_the_look_of_the_page(self):
        self.client.get(reverse('hr:today'), {'ui': 'next'})                  # the cookie keeps the look
        board = self.client.get(reverse('hr:today_board')).content.decode()
        self.assertIn('class="ui-stack"', board)
        self.client.get(reverse('hr:today'), {'ui': 'classic'})
        board = self.client.get(reverse('hr:today_board')).content.decode()
        self.assertNotIn('ui-stack', board)
        self.assertIn('class="tiles"', board)

    def test_the_stacked_bar_is_the_boards_own_tiles_and_adds_up_to_planned_today(self):
        response = self.client.get(reverse('hr:today'), {'ui': 'next'})
        board, bar = response.context['board'], response.context['planned_stack']
        self.assertEqual(bar['total'], board.planned)
        self.assertEqual({part['key']: part['value'] for part in bar['parts']}, {tile.key: tile.count for tile in board.tiles})


class StackTests(TestCase):
    def test_the_parts_are_laid_out_on_the_whole_and_a_zero_draws_nothing(self):
        found = stack.stack('Planned today', [stack.part('a', 'Here now', 3, 'ok'), stack.part('b', 'Absent', 0, 'critical'),
                                              stack.part('c', 'On leave', 2, 'note')])
        self.assertEqual(found['total'], 5)
        self.assertEqual([(each['key'], each['x'], each['value']) for each in found['segments']], [('a', 0, 3), ('c', 3, 2)])
        self.assertEqual(found['said'], 'Planned today. Here now 3, Absent 0, On leave 2')
        with self.assertRaises(ValueError):
            stack.part('d', 'Odd', 1, 'purple')
