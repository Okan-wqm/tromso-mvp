"""The rules the database holds for tasks and recurring tasks (each CHECK and unique key), and the recurrence rule's
dates, which are a pure function of the rule."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase
from django.utils import timezone

from ..models import Frequency, Status, Task, TaskChecklistItem, TaskNote, TaskSeries
from . import TasksTestCase


class TaskChecksTests(TasksTestCase):
    def refused(self, **changes):
        task = self.make_task()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Task.objects.filter(pk=task.pk).update(**changes)

    def test_exactly_one_place(self):
        self.refused(unit=None)
        self.refused(site=self.bergen)

    def test_a_title_with_something_in_it(self):
        self.refused(title='   ')

    def test_statuses_and_who_and_when(self):
        now = timezone.now()
        self.refused(status='overdue')
        self.refused(status=Status.IN_PROGRESS)                                    # without who started it
        self.refused(started_at=now, started_by=self.ali)                          # open, yet started
        self.refused(status=Status.DONE)                                           # done without completer
        self.refused(status=Status.DONE, completed_at=now)
        self.refused(completed_at=now, completed_by=self.ali)                      # open, yet completed
        self.refused(completion_note='x')
        self.refused(status=Status.CANCELLED, cancelled_at=now, cancelled_by=self.ali)          # no reason
        self.refused(status=Status.CANCELLED, cancelled_at=now, cancelled_by=self.ali, cancel_reason='  ')
        self.refused(cancel_reason='Why')
        task = self.make_task()
        Task.objects.filter(pk=task.pk).update(status=Status.DONE, completed_at=now, completed_by=self.ali,
                                               started_at=now, started_by=self.ali)
        Task.objects.filter(pk=task.pk).update(status=Status.CANCELLED, completed_at=None, completed_by=None,
                                               cancelled_at=now, cancelled_by=self.boss, cancel_reason='Emptied')

    def test_a_recurring_tasks_day_once(self):
        series = self.make_series()
        self.refused(series=series)                                                 # without its day
        self.refused(occurrence_date=self.today)                                    # a day without a series
        self.make_task(series=series, occurrence_date=self.today)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_task(series=series, occurrence_date=self.today)

    def test_a_checklist_line_and_a_note(self):
        task = self.make_task()
        for line in (TaskChecklistItem(task=task, text=' '), TaskChecklistItem(task=task, text='x', done_at=timezone.now())):
            with self.assertRaises(IntegrityError), transaction.atomic():
                line.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            TaskNote.objects.create(task=task, author=self.ali, body='  ')

    def make_series(self, **fields):
        values = {'title': 'Oxygen round', 'frequency': Frequency.DAILY, 'starts_on': self.today, **fields}
        series = TaskSeries(**values)
        series.set_place(self.t1)
        series.save()
        return series


class SeriesChecksTests(TasksTestCase):
    def refused(self, **fields):
        values = {'title': 'Round', 'frequency': Frequency.DAILY, 'starts_on': self.today, **fields}
        series = TaskSeries(**values)
        series.set_place(self.t1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            series.save()

    def test_each_rule_has_its_own_fields_only(self):
        self.refused(weekdays=[0])                                               # daily with weekdays
        self.refused(frequency=Frequency.WEEKLY)                                 # weekly without
        self.refused(frequency=Frequency.WEEKLY, weekdays=[7])
        self.refused(day_of_month=3)
        self.refused(frequency=Frequency.MONTHLY)
        self.refused(frequency=Frequency.MONTHLY, day_of_month=32)
        self.refused(interval=0)
        self.refused(interval=53)
        self.refused(ends_on=self.day(-1))
        self.refused(title=' ')

    def test_exactly_one_place(self):
        series = TaskSeries(title='Round', frequency=Frequency.DAILY, starts_on=self.today)
        with self.assertRaises(IntegrityError), transaction.atomic():
            series.save()


def rule(frequency, starts_on, interval=1, weekdays=(), day_of_month=None, ends_on=None):
    return TaskSeries(frequency=frequency, starts_on=starts_on, interval=interval, weekdays=list(weekdays),
                      day_of_month=day_of_month, ends_on=ends_on)


class RecurrenceTests(SimpleTestCase):
    def test_every_n_days_from_the_first_day(self):
        series = rule(Frequency.DAILY, date(2026, 11, 2), interval=3)
        self.assertEqual(list(series.dates(date(2026, 11, 1), date(2026, 11, 12))),
                         [date(2026, 11, 2), date(2026, 11, 5), date(2026, 11, 8), date(2026, 11, 11)])
        self.assertEqual(list(series.dates(date(2026, 11, 6), date(2026, 11, 9))), [date(2026, 11, 8)])

    def test_every_other_week_on_monday_and_thursday(self):
        series = rule(Frequency.WEEKLY, date(2026, 11, 4), interval=2, weekdays=[3, 0])     # a Wednesday
        self.assertEqual(list(series.dates(date(2026, 11, 1), date(2026, 11, 30))),
                         [date(2026, 11, 5), date(2026, 11, 16), date(2026, 11, 19), date(2026, 11, 30)])

    def test_the_31st_falls_on_the_last_day_of_a_shorter_month(self):
        series = rule(Frequency.MONTHLY, date(2026, 1, 31), day_of_month=31)
        self.assertEqual(list(series.dates(date(2026, 1, 1), date(2026, 4, 30))),
                         [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)])
        leap = rule(Frequency.MONTHLY, date(2028, 1, 31), day_of_month=31)
        self.assertEqual(list(leap.dates(date(2028, 2, 1), date(2028, 2, 29))), [date(2028, 2, 29)])
        quarterly = rule(Frequency.MONTHLY, date(2026, 1, 15), interval=3, day_of_month=10)
        self.assertEqual(list(quarterly.dates(date(2026, 1, 1), date(2026, 12, 31))),
                         [date(2026, 4, 10), date(2026, 7, 10), date(2026, 10, 10)])

    def test_no_drift_over_400_days(self):
        weekly = rule(Frequency.WEEKLY, date(2026, 1, 5), weekdays=[0])
        mondays = list(weekly.dates(date(2026, 1, 1), date(2027, 2, 5)))
        self.assertTrue(all(day.weekday() == 0 for day in mondays))
        self.assertEqual(len(mondays), 57)
        daily = rule(Frequency.DAILY, date(2026, 1, 1), interval=7)
        self.assertEqual(list(daily.dates(date(2027, 1, 1), date(2027, 1, 31)))[0], date(2027, 1, 7))

    def test_a_dst_weekend_moves_nothing(self):
        series = rule(Frequency.DAILY, date(2026, 10, 23))
        days = list(series.dates(date(2026, 10, 23), date(2026, 10, 27)))
        self.assertEqual(len(days), 5)                       # the clocks went back on 25 Oct in Oslo
        oslo = ZoneInfo('Europe/Oslo')
        times = [datetime.combine(day, time(8, 0), tzinfo=oslo).astimezone(ZoneInfo('UTC')).hour for day in days]
        self.assertEqual(times, [6, 6, 7, 7, 7])             # 08:00 local every day, whatever UTC says

    def test_its_first_and_last_day_bound_it(self):
        series = rule(Frequency.DAILY, date(2026, 11, 10), ends_on=date(2026, 11, 12))
        self.assertEqual(list(series.dates(date(2026, 11, 1), date(2026, 11, 30))),
                         [date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 12)])
        self.assertIsNone(series.next_date(date(2026, 11, 12)))
        self.assertEqual(series.next_date(date(2026, 11, 1)), date(2026, 11, 10))
        monthly = rule(Frequency.MONTHLY, date(2026, 1, 1), interval=12, day_of_month=1)
        self.assertEqual(monthly.next_date(date(2026, 1, 1)), date(2027, 1, 1))
        self.assertEqual(rule(Frequency.WEEKLY, date(2026, 1, 1), interval=3, weekdays=[4]).next_date(
            date(2026, 1, 2)), date(2026, 1, 23))
        self.assertEqual(timedelta(days=21), date(2026, 1, 23) - date(2026, 1, 2))
