"""Recurring tasks through their pages, checked against the stored rows: every rule (daily, weekly, monthly)
created, read, edited, paused and deleted; the planned tasks made up to the horizon, back at most the backfill
window, once per day however often they are made; a change, a pause or a delete replacing only the tasks nobody
touched; deleting the place deleting the recurring task with its planned tasks; the checklist copied."""

from django.conf import settings
from django.db import IntegrityError, transaction
from django.urls import reverse

from core import softdelete
from core.models import AuditLog
from farm.tests.helpers import rows_data

from .. import places, services
from ..models import Frequency, Status, Task, TaskChecklistItem, TaskNote, TaskSeries
from . import TasksTestCase, form_data

LIST = reverse('tasks:taskseries_list')
NEW = reverse('tasks:taskseries_create')
HORIZON, BACKFILL = settings.TASK_HORIZON_DAYS, settings.TASK_BACKFILL_DAYS


def series_data(place, **fields):
    data = form_data(site=places.site_key(place), location=places.token(place), frequency='daily', interval='1',
                     due_time='', starts_on='', ends_on='', is_active='on')
    for key in ('batch', 'due_date'):
        data.pop(key)
    data.update(fields)
    return data


class SeriesPagesTests(TasksTestCase):
    def create(self, **fields):
        fields.setdefault('assignees', [self.ali.pk])
        fields.setdefault('title', 'Oxygen round')
        data = series_data(self.t1, starts_on=self.today.isoformat(), **fields)
        response = self.client.post(NEW, data)
        self.assertEqual(response.status_code, 302, response.context and response.context['form'].errors)
        return TaskSeries.objects.get(title=data['title'])

    def planned_days(self, series):
        return list(Task.objects.filter(series=series).order_by('occurrence_date').values_list('occurrence_date',
                                                                                              flat=True))

    def test_every_rule_is_created_read_edited_and_deleted(self):
        rules = [
            ('daily', {'interval': '2'}, [self.day(offset) for offset in range(0, HORIZON + 1, 2)]),
            ('weekly', {'weekdays': [str(self.today.weekday())]}, [self.day(offset) for offset in range(0, HORIZON + 1, 7)]),
            ('monthly', {'day_of_month': str(self.today.day)}, [self.today]),
        ]
        for frequency, fields, expected in rules:
            with self.subTest(frequency=frequency):
                series = self.create(title=f'{frequency} round', frequency=frequency, **fields)
                self.assertEqual((series.frequency, series.created_by, series.is_active), (frequency, self.boss, True))
                self.assertEqual(self.planned_days(series), expected)
                self.assertEqual(series.generated_until, self.day(HORIZON))
                task = Task.objects.filter(series=series).first()
                self.assertEqual((task.unit, list(task.assignees.all()), task.created_by, task.title),
                                 (self.t1, [self.ali], None, f'{frequency} round'))
                self.assertContains(self.client.get(LIST), f'{frequency} round')
                edit = reverse('tasks:taskseries_edit', args=[series.pk])
                self.assertEqual(self.client.get(edit).status_code, 200)
                response = self.client.post(edit, series_data(
                    self.t2, title=f'{frequency} round, moved', frequency=frequency, interval='1',
                    starts_on=self.today.isoformat(), assignees=[self.kari.pk], version=series.version, **{
                        key: value for key, value in fields.items() if key != 'interval'}))
                self.assertEqual(response.status_code, 302)
                series.refresh_from_db()
                self.assertEqual((series.title, series.unit, list(series.assignees.all())),
                                 (f'{frequency} round, moved', self.t2, [self.kari]))
                moved = Task.objects.filter(series=series)
                self.assertTrue(moved.exists())
                self.assertTrue(all(task.unit == self.t2 and list(task.assignees.all()) == [self.kari]
                                    and task.title == f'{frequency} round, moved' for task in moved))
                delete = reverse('tasks:taskseries_delete', args=[series.pk])
                plan = self.client.get(delete).context['plan']
                self.assertEqual(sum(len(group['records']) for group in plan.deleted_groups()), moved.count())
                self.client.post(delete)
                self.assertTrue(TaskSeries.all_objects.get(pk=series.pk).is_deleted)
                self.assertFalse(Task.objects.filter(series=series).exists())

    def test_a_recurring_task_at_every_kind_of_place_plans_its_tasks_there(self):
        for place in (self.bergen, self.hall, self.ras, self.t1, self.pump, self.loose, self.t9):
            with self.subTest(place=places.token(place)):
                title = f'Round at {places.label(place)}'
                response = self.client.post(NEW, series_data(place, title=title, starts_on=self.today.isoformat(),
                                                             assignees=[self.ali.pk]))
                self.assertEqual(response.status_code, 302)
                series = TaskSeries.objects.get(title=title)
                self.assertEqual(series.place, place)
                planned = Task.objects.filter(series=series)
                self.assertEqual(planned.count(), HORIZON + 1)
                self.assertTrue(all(task.place == place for task in planned))
                self.assertEqual(AuditLog.objects.filter(entity_id=str(series.pk), action='create').count(), 1)

    def test_the_rule_form_shows_the_fields_of_its_rule_and_clears_the_others(self):
        form = self.client.get(NEW).context['form']
        self.assertIn('weekdays', form.fields)
        self.assertNotIn('day_of_month', form.fields)
        draft = self.client.post(NEW, {**series_data(self.t1, frequency='monthly'), '_draft': 'frequency'})
        self.assertIn('day_of_month', draft.context['form'].fields)
        self.assertNotIn('weekdays', draft.context['form'].fields)
        series = self.create(frequency='weekly', weekdays=['0', '3'])
        self.assertEqual(series.weekdays, [0, 3])
        self.client.post(reverse('tasks:taskseries_edit', args=[series.pk]), series_data(
            self.t1, title='Oxygen round', frequency='daily', starts_on=self.today.isoformat(),
            assignees=[self.ali.pk], version=series.version))
        series.refresh_from_db()
        self.assertEqual((series.frequency, series.weekdays, series.day_of_month), ('daily', [], None))
        response = self.client.post(NEW, series_data(self.t1, title='No days', frequency='weekly',
                                                     starts_on=self.today.isoformat(), assignees=[self.ali.pk]))
        self.assertIn('weekdays', response.context['form'].errors)
        response = self.client.post(NEW, series_data(self.t1, title='Ends early', starts_on=self.today.isoformat(),
                                                     ends_on=self.day(-1).isoformat(), assignees=[self.ali.pk]))
        self.assertIn('ends_on', response.context['form'].errors)

    def test_every_optional_field_can_be_cleared(self):
        series = self.create(description='Both tanks', due_time='08:00', ends_on=self.day(30).isoformat())
        self.client.post(reverse('tasks:taskseries_edit', args=[series.pk]), series_data(
            self.t1, title='Oxygen round', starts_on=self.today.isoformat(), assignees=[self.ali.pk],
            version=series.version))
        series.refresh_from_db()
        self.assertEqual((series.description, series.due_time, series.ends_on), ('', None, None))

    def test_pausing_removes_the_untouched_tasks_from_today_and_resuming_does_not_backfill(self):
        series = self.create()
        edit = reverse('tasks:taskseries_edit', args=[series.pk])
        data = series_data(self.t1, title='Oxygen round', starts_on=self.today.isoformat(), assignees=[self.ali.pk])
        data.pop('is_active')
        self.client.post(edit, {**data, 'version': series.version})
        self.assertEqual(Task.objects.filter(series=series).count(), 0)
        self.assertEqual(services.materialise_due(), [])
        series.refresh_from_db()
        # resumed after a week: from today on, the paused days stay empty
        TaskSeries.objects.filter(pk=series.pk).update(generated_until=self.day(-8))
        series.refresh_from_db()
        self.client.post(edit, {**data, 'is_active': 'on', 'version': series.version})
        self.assertEqual(self.planned_days(series)[0], self.today)

    def test_a_change_keeps_the_tasks_someone_touched(self):
        series = self.create()
        tasks = list(Task.objects.filter(series=series).order_by('occurrence_date'))
        started, noted, ticked, edited, done = tasks[1:6]
        services.start(self.ali, started)
        TaskNote.objects.create(task=noted, author=self.ali, body='Low O2 yesterday')
        line = TaskChecklistItem.objects.create(task=ticked, text='Probe')
        services.tick(self.ali, line, True)
        Task.objects.filter(pk=edited.pk).update(version=2, title='Moved by hand')
        services.complete(self.ali, done)
        kept = {task.pk for task in (started, noted, ticked, edited, done)}
        self.client.post(reverse('tasks:taskseries_edit', args=[series.pk]), series_data(
            self.t1, title='Renamed round', starts_on=self.today.isoformat(), assignees=[self.ali.pk],
            version=series.version))
        after = Task.objects.filter(series=series)
        self.assertTrue(kept <= {task.pk for task in after})
        self.assertEqual(self.planned_days(series), [self.day(offset) for offset in range(HORIZON + 1)])
        renamed = after.exclude(pk__in=kept)
        self.assertTrue(all(task.title == 'Renamed round' for task in renamed))
        self.assertEqual(after.get(pk=edited.pk).title, 'Moved by hand')
        self.assertTrue(AuditLog.objects.filter(action='delete', entity_id=str(tasks[0].pk)).exists())

    def test_the_checklist_is_copied_and_saving_it_plans_again(self):
        series = self.create()
        url = reverse('tasks:taskseries_checklist', args=[series.pk])
        self.client.post(url, rows_data('checklist', [{'text': 'Read the probe'}, {'text': 'Write it down'}], record=series))
        for task in Task.objects.filter(series=series):
            self.assertEqual(list(task.checklist.values_list('text', flat=True)), ['Read the probe', 'Write it down'])

    def test_people_who_can_no_longer_read_tasks_get_no_new_tasks(self):
        series = self.create(assignees=[self.ali.pk, self.kari.pk])
        self.kari.is_active = False
        self.kari.save()
        Task.objects.filter(series=series).delete()
        TaskSeries.objects.filter(pk=series.pk).update(generated_until=None)
        services.materialise(series)
        self.assertEqual(set(Task.objects.filter(series=series).values_list('assignees', flat=True)), {self.ali.pk})


class MaterialiseTests(TasksTestCase):
    def series(self, **fields):
        values = {'title': 'Feed check', 'frequency': Frequency.DAILY, 'starts_on': self.today, **fields}
        series = TaskSeries(**values)
        series.set_place(self.ras)
        series.save()
        series.assignees.set([self.ali])
        return series

    def days(self, series):
        return sorted(Task.all_objects.filter(series=series).values_list('occurrence_date', flat=True))

    def test_twice_makes_each_day_once_and_the_key_is_the_backstop(self):
        series = self.series()
        made = services.materialise(series)
        self.assertEqual(len(made), HORIZON + 1)
        self.assertEqual(services.materialise(series), [])
        TaskSeries.objects.filter(pk=series.pk).update(generated_until=None)
        self.assertEqual(services.materialise(series), [])
        self.assertEqual(len(self.days(series)), HORIZON + 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_task(place=self.ras, series=series, occurrence_date=self.today)

    def test_a_first_run_makes_missed_days_back_to_the_backfill_window_and_they_are_overdue(self):
        series = self.series(starts_on=self.day(-30))
        services.materialise(series)
        self.assertEqual(self.days(series)[0], self.day(-BACKFILL))
        self.assertEqual(self.days(series)[-1], self.day(HORIZON))
        listing = self.client.get(reverse('tasks:task_list'))
        self.assertEqual(sum(task.overdue for task in listing.context['objects']), BACKFILL)

    def test_after_a_gap_the_missed_days_are_made_up_to_the_backfill_window(self):
        series = self.series(starts_on=self.day(-60))
        TaskSeries.objects.filter(pk=series.pk).update(generated_until=self.day(-20))
        services.materialise_due()
        self.assertEqual(self.days(series)[0], self.day(-BACKFILL))
        TaskSeries.objects.filter(pk=series.pk).update(generated_until=self.day(-3))
        Task.objects.filter(series=series).delete()
        services.materialise(series)
        self.assertEqual(self.days(series)[0], self.day(-2))

    def test_a_task_deleted_by_a_person_is_not_made_again(self):
        series = self.series()
        services.materialise(series)
        task = Task.objects.get(series=series, occurrence_date=self.day(3))
        self.client.post(reverse('tasks:task_delete', args=[task.pk]))
        TaskSeries.objects.filter(pk=series.pk).update(generated_until=None)
        services.materialise(series)
        self.assertFalse(Task.objects.filter(series=series, occurrence_date=self.day(3)).exists())

    def test_an_ended_or_paused_series_makes_nothing_more(self):
        ended = self.series(ends_on=self.day(2))
        services.materialise(ended)
        self.assertEqual(self.days(ended)[-1], self.day(2))
        paused = self.series(title='Paused', is_active=False)
        self.assertEqual(services.materialise(paused), [])

    def test_deleting_the_place_deletes_the_recurring_task_and_its_planned_tasks_and_keeps_the_rest(self):
        series = self.series()
        services.materialise(series)
        first = Task.objects.get(series=series, occurrence_date=self.today)
        services.start(self.ali, first)
        old = Task.objects.get(series=series, occurrence_date=self.day(1))
        Task.objects.filter(pk=old.pk).update(due_date=self.day(-1))       # untouched, but due yesterday: history
        single = self.make_task(place=self.ras, title='One-off')
        plan = softdelete.plan_delete(self.ras)
        deleted = {group['label']: len(group['records']) for group in plan.deleted_groups()}
        self.assertEqual(deleted, {'Recurring tasks': 1, 'Tasks': HORIZON - 1})
        self.assertEqual(plan.kept_groups(), [{'label': 'Tasks', 'count': 3, 'note': Task.kept_note}])
        softdelete.execute(plan, self.boss)
        self.assertTrue(TaskSeries.all_objects.get(pk=series.pk).is_deleted)
        self.assertEqual(set(Task.objects.filter(system=self.ras)), {first, old, single})
        self.assertEqual(Task.objects.get(pk=first.pk).status, Status.IN_PROGRESS)
