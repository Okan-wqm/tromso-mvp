"""The data-layering audit, M-3: the pages that show tasks only read. The planned tasks of the recurring tasks are made by
the task job (`manage.py generate_tasks`), never by a GET of the production overview or the Tasks pages; a page says
how many recurring tasks are not planned up to today instead, and the overview never fails because of the planning."""
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core import ui
from core.island_props import props_of

from .. import read
from ..models import Frequency, Task, TaskSeries
from . import TasksTestCase

PAGES = ('production_home', 'tasks:task_list', 'tasks:taskseries_list')
WRITES = ('INSERT', 'UPDATE', 'DELETE')
TASK_TABLES = ('"tasks"', '"task_', 'audit_log')


class PagesOnlyReadTests(TasksTestCase):
    def setUp(self):
        super().setUp()
        self.behind = TaskSeries(title='Feed check', frequency=Frequency.DAILY, starts_on=self.day(-3))
        self.behind.set_place(self.ras)
        self.behind.save()                               # saved as a row: nothing planned yet (the job's work)
        self.behind.assignees.set([self.ali])

    def test_no_page_makes_the_planned_tasks(self):
        for name in PAGES:
            with self.subTest(page=name), CaptureQueriesContext(connection) as queries:
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
            written = [query['sql'] for query in queries if query['sql'].lstrip().upper().startswith(WRITES)
                       and any(table in query['sql'] for table in TASK_TABLES)]
            self.assertEqual(written, [])
        self.assertFalse(Task.all_objects.filter(series=self.behind).exists())
        self.behind.refresh_from_db()
        self.assertIsNone(self.behind.generated_until)

    def test_the_pages_say_how_many_are_not_planned_up_to_today(self):
        self.assertEqual([series.pk for series in read.unplanned()], [self.behind.pk])
        self.assertEqual(self.client.get(reverse('production_home')).context['tasks_unplanned'], 1)
        for name in ('tasks:task_list', 'tasks:taskseries_list'):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.context['unplanned'], 1)
                self.assertContains(response, 'not planned up to today')

    def test_the_new_look_says_it_too(self):
        # a redesign never drops what the classic page says: the overview's Needs attention, both task pages' notices
        manifest = str(Path(__file__).resolve().parents[2] / 'core' / 'testdata' / 'islands-prodrest-manifest.json')
        with override_settings(ISLANDS_MANIFEST=manifest):
            props = props_of(self.client.get(reverse('production_home'), {ui.PARAM: ui.NEXT}).content.decode(),
                             'production')
            rows = {row['key']: row for row in props['attention']['rows']}
            self.assertEqual(rows['tasks-unplanned']['title'], '1 recurring task not planned up to today')
            self.assertIsNone(props['attention']['nothing'])
            for name in ('tasks:task_list', 'tasks:taskseries_list'):
                with self.subTest(page=name):
                    self.assertContains(self.client.get(reverse(name), {ui.PARAM: ui.NEXT}),
                                        '1 recurring task is not planned up to today')
        call_command('generate_tasks', stdout=StringIO())
        with override_settings(ISLANDS_MANIFEST=manifest):
            props = props_of(self.client.get(reverse('production_home'), {ui.PARAM: ui.NEXT}).content.decode(),
                             'production')
            self.assertNotIn('tasks-unplanned', {row['key'] for row in props['attention']['rows']})
            self.assertNotContains(self.client.get(reverse('tasks:taskseries_list'), {ui.PARAM: ui.NEXT}),
                                   'not planned up to today')

    def test_the_job_plans_them_and_the_notice_goes(self):
        call_command('generate_tasks', stdout=StringIO())
        self.assertTrue(Task.objects.filter(series=self.behind, occurrence_date=self.today).exists())
        self.assertEqual(read.unplanned(), [])
        self.assertEqual(self.client.get(reverse('production_home')).context['tasks_unplanned'], 0)
        self.assertNotContains(self.client.get(reverse('tasks:task_list')), 'not planned up to today')

    def test_a_recurring_task_that_starts_later_or_is_paused_is_not_behind(self):
        TaskSeries.objects.filter(pk=self.behind.pk).update(starts_on=self.day(1))
        self.assertEqual(read.unplanned(), [])
        TaskSeries.objects.filter(pk=self.behind.pk).update(starts_on=self.day(-3), is_active=False)
        self.assertEqual(read.unplanned(), [])
        TaskSeries.objects.filter(pk=self.behind.pk).update(is_active=True, generated_until=self.today)
        self.assertEqual(read.unplanned(), [])
        TaskSeries.objects.filter(pk=self.behind.pk).update(generated_until=self.day(-1))
        self.assertEqual(len(read.unplanned()), 1)

    def test_a_recurring_task_planned_to_its_last_day_is_not_behind(self):
        # its last day is past and its tasks reach it: nothing is left to plan (the landing review, m-2)
        TaskSeries.objects.filter(pk=self.behind.pk).update(ends_on=self.day(-2), generated_until=self.day(-2))
        self.assertEqual(read.unplanned(), [])
        TaskSeries.objects.filter(pk=self.behind.pk).update(generated_until=self.day(-3))
        self.assertEqual(len(read.unplanned()), 1)                 # a day before its end is still missing
        TaskSeries.objects.filter(pk=self.behind.pk).update(ends_on=self.day(3), generated_until=self.day(-1))
        self.assertEqual(len(read.unplanned()), 1)                 # it goes on after today: today is missing

    def test_the_overview_never_fails_on_the_planning(self):
        with mock.patch('tasks.services.materialise', side_effect=RuntimeError('a series whose place is gone')):
            self.assertEqual(self.client.get(reverse('production_home')).status_code, 200)
            self.assertEqual(self.client.get(reverse('tasks:task_list')).status_code, 200)
