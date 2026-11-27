"""The open alarms' own queue (alarms.OpenAlarm, alarms 0025; review 1, F1): the database keeps it, whoever writes, and
what reads the open alarms reads it, never every alarm, clearance and acknowledgement ever recorded. Measured beside
50,000 and again beside 100,000 alarms of history (each cleared and acknowledged), counted by PostgreSQL
(core.testing.reads): the pass's notify step, the pages' floods, the open list and the overview's open alarms read
fewer than a hundred rows more of each history table, where a scan reads the 50,000 more. A difference, so what does not
depend on the history counts alike on both sides (the open alarms' own work, the planner's look at an index's ends)."""

from django.db import connection

from core.testing import assert_reads_do_not_grow, reads

from .. import engine, floods, read, services
from ..models import OPEN, Alarm, AlarmClearance, OpenAlarm
from ..rules import current
from . import AlarmsCase

STEP = 50_000
HISTORY_TABLES = ('alarms', 'alarm_clearances', 'alarm_acknowledgements')


class OpenQueueTests(AlarmsCase):
    def open(self, name, severity='critical'):
        return services.open_alarm(source='system', farm_wide=True, parameter=name, severity=severity, at=self.now,
                                   summary=name, site=self.bergen)

    def grow(self):
        """STEP more alarms opened 30 days before the test's moment, each cleared and acknowledged."""
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO alarms (source, parameter, severity, opened_at, summary) SELECT 'system', 'old', "
                           "'warning', %s::timestamptz - interval '30 days', 'old ' || n FROM generate_series(1, %s) n",
                           [self.now, STEP])
            cursor.execute("INSERT INTO alarm_clearances (alarm_id, cleared_at, cause) SELECT a.id, a.opened_at "
                           "+ interval '1 hour', 'returned' FROM alarms a WHERE a.parameter = 'old' AND NOT EXISTS "
                           '(SELECT 1 FROM alarm_clearances c WHERE c.alarm_id = a.id)')
            cursor.execute("INSERT INTO alarm_acknowledgements (alarm_id, user_id, acknowledged_at, device, app) "
                           "SELECT a.id, %s, a.opened_at + interval '5 minutes', '', 'console' FROM alarms a "
                           "WHERE a.parameter = 'old' AND NOT EXISTS (SELECT 1 FROM alarm_acknowledgements k "
                           'WHERE k.alarm_id = a.id)', [self.operator.pk])
            cursor.execute('ANALYZE alarms; ANALYZE alarm_clearances; ANALYZE alarm_acknowledgements; '
                           'ANALYZE alarm_open')

    def test_the_database_keeps_the_queue_whoever_writes(self):
        made = [self.open(f'open{number}') for number in range(3)]
        services.clear(made[0], self.now, 'returned')
        with connection.cursor() as cursor:                  # raw SQL, as a migration or a fixture writes
            cursor.execute("INSERT INTO alarms (source, parameter, severity, opened_at, summary) VALUES ('system', "
                           "'raw', 'warning', %s, 'raw') RETURNING id", [self.now])
            (raw,) = cursor.fetchone()
        unclear = set(Alarm.objects.exclude(pk__in=AlarmClearance.objects.values('alarm')).values_list('pk', flat=True))
        self.assertEqual(set(OpenAlarm.objects.values_list('alarm', flat=True)), unclear)
        self.assertEqual(unclear, {made[1].pk, made[2].pk, raw})
        self.assertEqual(set(Alarm.objects.filter(OPEN).values_list('pk', flat=True)), unclear)
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO alarm_clearances (alarm_id, cleared_at, cause) VALUES (%s, %s, 'restored')",
                           [raw, self.now])
        self.assertEqual(set(OpenAlarm.objects.values_list('alarm', flat=True)), {made[1].pk, made[2].pk})

    def test_the_pass_notify_step_reads_the_open_alarms_never_the_history(self):
        steps, opened = [], []

        def notify():
            for alarm in opened:                             # the last look's cleared: three open at every look
                services.clear(alarm, self.now, 'returned')
            opened[:] = [self.open(f'open{len(steps)}{number}') for number in range(3)]
            summary = engine.Summary()
            with reads() as found:
                engine.notify(self.now, summary, current())
            self.assertFalse(summary.failed_steps)
            steps.append(found)
            return found
        assert_reads_do_not_grow(self, self.grow, notify, HISTORY_TABLES, 'the notify step')

    def test_the_pages_read_the_open_alarms_never_the_history(self):
        opened = {self.open(f'open{number}').pk for number in range(3)}
        for what, call in (('the floods', lambda: floods.open_floods(current())),
                           ('the open list', lambda: list(read.listing('open'))),
                           ('the open alarms', read.open_alarms)):
            def measure(what=what, call=call):
                with reads() as found:
                    got = call()
                if what == 'the open list':
                    self.assertEqual({alarm.pk for alarm in got}, opened)
                if what == 'the open alarms':
                    self.assertEqual(len(got), 3)
                return found
            assert_reads_do_not_grow(self, self.grow, measure, HISTORY_TABLES, what)
