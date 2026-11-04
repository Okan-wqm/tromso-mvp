"""The tasks of many units at once (tasks.read.per_unit): equal to what the Tasks page's own filters count for each
unit, one query however many units, on each site's own clock."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import connection
from django.test.utils import CaptureQueriesContext

from farm.models import Site

from .. import read, services
from ..models import Task
from . import TasksTestCase

UTC = ZoneInfo('UTC')


class PerUnitTests(TasksTestCase):
    def setUp(self):
        super().setUp()
        self.late = self.make_task(self.t1, due_date=self.day(-2), title='Late')
        self.today_task = self.make_task(self.t1, due_date=self.today, title='Today')
        self.soon = self.make_task(self.t1, due_date=self.day(3), title='Soon')
        self.done = self.make_task(self.t1, due_date=self.day(-1), title='Done')
        services.complete(self.boss, self.done)
        self.t2_task = self.make_task(self.t2, due_date=self.day(-1), title='At sea')
        self.progress = self.make_task(self.t2, due_date=self.day(2), title='Going')
        services.start(self.boss, self.progress)
        self.on_hall = self.make_task(self.hall, due_date=self.day(-1), title='Not a unit')
        self.deleted = self.make_task(self.t1, due_date=self.day(-3), title='Gone')
        self.deleted.delete()

    def old(self, unit_id, moment):
        """What the Tasks page's filters count for the unit (the code the cards must not repeat)."""
        now = read.clocks(moment)
        tasks = Task.objects.with_site().filter(unit_id=unit_id)
        return read.UnitTasks(tasks.filter(status__in=read.OPEN_STATUSES).count(), tasks.filter(read.overdue(now)).count(),
                              tasks.filter(read.due_today(now)).count())

    def test_the_counts_equal_the_pages_filters_for_each_unit(self):
        moment = datetime.combine(self.today, time(12), tzinfo=ZoneInfo('Europe/Oslo'))
        found = read.per_unit([self.t1.pk, self.t2.pk, self.t9.pk], moment)
        self.assertEqual(found[self.t1.pk], read.UnitTasks(3, 1, 1))
        self.assertEqual(found[self.t2.pk], read.UnitTasks(2, 1, 0))
        self.assertNotIn(self.t9.pk, found)                  # nothing open: left out, the reader defaults to zero
        for unit in (self.t1, self.t2):
            self.assertEqual(found[unit.pk], self.old(unit.pk, moment))

    def test_the_due_time_decides_on_the_sites_clock(self):
        Task.objects.filter(pk=self.today_task.pk).update(due_time=time(9, 0))
        morning = datetime.combine(self.today, time(8, 0), tzinfo=ZoneInfo('Europe/Oslo'))
        evening = morning + timedelta(hours=12)
        self.assertEqual(read.per_unit([self.t1.pk], morning)[self.t1.pk], read.UnitTasks(3, 1, 1))
        self.assertEqual(read.per_unit([self.t1.pk], evening)[self.t1.pk], read.UnitTasks(3, 2, 0))
        self.assertEqual(read.per_unit([self.t1.pk], evening)[self.t1.pk], self.old(self.t1.pk, evening))

    def test_a_site_on_another_clock_has_its_own_today(self):
        Site.objects.filter(pk=self.tromso.pk).update(timezone='Pacific/Auckland')
        Task.objects.filter(pk=self.t2_task.pk).update(due_date=self.day(0))
        moment = datetime.combine(self.today, time(20, 0), tzinfo=UTC)     # already tomorrow in Auckland
        self.assertEqual(read.per_unit([self.t2.pk], moment)[self.t2.pk], self.old(self.t2.pk, moment))
        self.assertEqual(read.per_unit([self.t2.pk], moment)[self.t2.pk].overdue, 1)

    def test_one_query_however_many_units(self):
        counts = []
        for ids in ([self.t1.pk], [self.t1.pk, self.t2.pk], [self.t1.pk, self.t2.pk, self.t9.pk]):
            read.per_unit(ids)
            with CaptureQueriesContext(connection) as queries:
                read.per_unit(ids)
            counts.append(len(queries))
        self.assertEqual(counts, [counts[0]] * 3)
        self.assertEqual(counts[0], 1 + 1)                   # the sites' zones, then the one grouped query
