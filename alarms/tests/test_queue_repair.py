"""The alarm worker repairs the alarms' two queues itself (review 3 follow-up): on its schedule (worker.QUEUE_CHECK_EVERY,
and at its first pass) the pass begins with the check of alarms.W001 and W002 (alarms.checks._queue_holds); a queue out
of step, by what passed the database's triggers by (a TRUNCATE, a disabled trigger), is repaired from what it stands for
by a repair row's trigger (alarms 0027, as the owner: the statements W001 and W002 print), in the same pass, and said by
the alarm system's own critical alarm to the holders of Oversee. A clean state writes nothing and raises nothing."""
from datetime import timedelta
from importlib import import_module
from unittest import mock

from django.db import connection

from core.models import AuditLog
from sensors.models import AlarmEvent, AlarmRule
from sensors.tests import make_channel, make_connection, make_device, make_format

from .. import checks, engine, routing, worker
from ..health import OWN_HEALTH
from ..models import Alarm, AlarmQueueRepair
from . import AlarmsCase
from .test_worker import WorkerCase, make, unlock_all

REPAIRED = routing.QUEUES_REPAIRED


def rows(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall() if cursor.description else None


class QueueRepairTests(AlarmsCase):
    def setUp(self):
        super().setUp()
        self.channel = make_channel(make_device(make_connection(), make_format(), self.bergen), 'flow_m3_h')
        self.rule = AlarmRule.objects.create(kind='low', severity='warning', channel=self.channel, threshold=10)

    def open(self, name):
        from .. import services
        return services.open_alarm(source='system', farm_wide=True, parameter=name, severity='warning', at=self.now,
                                   summary=name, site=self.bergen)

    def held(self):
        return [checks._queue_holds(queue) for queue in checks.QUEUES]

    def said(self):
        return Alarm.objects.filter(source='system', parameter=REPAIRED)

    def test_a_clean_state_is_checked_and_nothing_is_written_or_raised(self):
        self.open('fine')
        summary = engine.run_once(self.now, check_queues=True)
        self.assertNotIn('queues', summary.failed_steps)
        self.assertEqual((summary.repaired, AlarmQueueRepair.objects.count(), self.said().count()), (0, 0, 0))
        self.assertEqual(self.held(), [([], []), ([], [])])

    def test_a_truncated_queue_is_repaired_by_the_next_scheduled_pass_and_said_to_oversee(self):
        made = [self.open(f'open{number}') for number in range(2)]
        rows('SET CONSTRAINTS ALL IMMEDIATE')         # (the test's own pending key checks, or TRUNCATE waits)
        rows('TRUNCATE alarm_open')                   # what a superuser's TRUNCATE leaves
        self.assertEqual(self.held()[0], ([made[0].pk, made[1].pk], []))
        engine.run_once(self.now)                     # a pass the check is not due in: nothing repaired
        self.assertFalse(AlarmQueueRepair.objects.exists())
        summary = engine.run_once(self.now + timedelta(minutes=1), check_queues=True)
        self.assertEqual(summary.repaired, 2)
        self.assertEqual(self.held(), [([], []), ([], [])])
        self.assertLessEqual({(made[0].pk,), (made[1].pk,)}, set(rows('SELECT alarm_id FROM alarm_open')))
        repair = AlarmQueueRepair.objects.get()
        self.assertEqual((repair.rows_repaired, repair.found), (2, 'alarm_open: 2 missing'))
        alarm = self.said().get()
        self.assertEqual((alarm.severity, alarm.unit_id, alarm.system_id), ('critical', None, None))   # farm-wide
        self.assertIn('2 row(s) repaired', alarm.summary)
        self.assertIn(REPAIRED, routing.TO_OVERSEERS)                    # to every holder of Oversee besides the rules
        self.assertIn(REPAIRED, OWN_HEALTH)                              # never snoozed
        self.assertTrue(AuditLog.objects.filter(entity_label='Alarm queues repaired',
                                                severity=AuditLog.Severity.CRITICAL).exists())

    def test_an_event_a_disabled_trigger_left_out_is_queued_and_mirrored_in_the_same_pass(self):
        rows('SET CONSTRAINTS ALL IMMEDIATE')
        rows('ALTER TABLE sensors_alarm_event DISABLE TRIGGER trg_sensors_alarm_event_unmirrored')
        event = AlarmEvent.objects.create(rule=self.rule, channel_no=self.channel.channel_no, opened_at=self.now,
                                          peak=4)
        rows('SET CONSTRAINTS ALL IMMEDIATE')
        rows('ALTER TABLE sensors_alarm_event ENABLE TRIGGER trg_sensors_alarm_event_unmirrored')
        engine.run_once(self.now)
        self.assertFalse(Alarm.objects.filter(sensor_event=event).exists())   # missed by the mirror: not queued
        summary = engine.run_once(self.now + timedelta(minutes=1), check_queues=True)
        self.assertEqual(summary.repaired, 1)
        self.assertTrue(Alarm.objects.filter(sensor_event=event).exists())    # the queues' step ran first
        self.assertEqual(AlarmQueueRepair.objects.get().found, 'alarm_unmirrored_events: 1 missing')
        self.assertTrue(self.said().exists())

    def test_a_wrong_row_is_removed_both_queues_at_once(self):
        cleared = self.open('cleared')
        rows('SET CONSTRAINTS ALL IMMEDIATE')
        rows('ALTER TABLE alarm_clearances DISABLE TRIGGER trg_alarm_clearances_open')
        from .. import services
        services.clear(cleared, self.now, 'returned')
        rows('SET CONSTRAINTS ALL IMMEDIATE')
        rows('ALTER TABLE alarm_clearances ENABLE TRIGGER trg_alarm_clearances_open')
        AlarmEvent.objects.create(rule=self.rule, channel_no=self.channel.channel_no, opened_at=self.now, peak=4)
        rows('SET CONSTRAINTS ALL IMMEDIATE')
        rows('TRUNCATE alarm_unmirrored_events')
        self.assertEqual([[len(ids) for ids in held] for held in self.held()], [[0, 1], [1, 0]])
        summary = engine.run_once(self.now, check_queues=True)
        self.assertEqual(summary.repaired, 2)
        self.assertEqual(AlarmQueueRepair.objects.get().found, 'alarm_open: 1 wrong; alarm_unmirrored_events: 1 missing')
        self.assertEqual(self.held(), [([], []), ([], [])])

    def test_the_repair_runs_exactly_the_statements_w001_and_w002_print(self):
        body = import_module('alarms.migrations.0027_queue_repairs').REPAIR
        (source,) = rows("SELECT prosrc FROM pg_proc WHERE proname = 'alarm_queues_repair'")[0]
        for queue in checks.QUEUES:
            for _said, statement in (queue.missing, queue.stale):
                with self.subTest(statement=statement):
                    self.assertIn(statement, body)
                    self.assertIn(statement, source)
        self.assertEqual(len([line for line in body.splitlines() if line.strip()]), 4)
        self.assertEqual(rows("SELECT has_function_privilege('public', 'public.alarm_queues_repair()', 'EXECUTE')"),
                         [(False,)])


class ScheduleTests(WorkerCase):
    def test_the_check_is_at_the_first_pass_then_once_every_queue_check_every_and_again_while_it_fails(self):
        results = iter([engine.Summary(), engine.Summary(), engine.Summary(failed_steps=['queues'])]
                       + [engine.Summary()] * 20)
        made = make(100, run_pass=mock.Mock(side_effect=lambda **kw: next(results)))
        with mock.patch.object(worker, 'QUEUE_CHECK_EVERY', 30):
            self.assertEqual(made.run(), 0)
        checked = [bool(call.kwargs.get('check_queues')) for call in made.run_pass.call_args_list]
        # passes every 15 s (the sweep): at 0 (the first: checked), 15, 30 (due: checked), 45 (due again: the check of 30
        # failed), 60, 75 (30 s after 45: due), 90
        self.assertEqual(checked, [True, False, True, True, False, True, False])


class WorkerRepairTests(AlarmsCase):
    """End to end, as the worker runs: its first pass repairs a queue a superuser's TRUNCATE emptied, with nobody running
    `manage.py check`, and the alarm system says so."""

    def setUp(self):
        super().setUp()
        self.addCleanup(unlock_all)

    def test_the_workers_first_pass_repairs_a_truncated_queue_and_says_so(self):
        from .. import services
        made = [services.open_alarm(source='system', farm_wide=True, parameter=f'open{number}', severity='warning',
                                    at=self.now, summary=f'open{number}', site=self.bergen) for number in range(2)]
        rows('SET CONSTRAINTS ALL IMMEDIATE')
        rows('TRUNCATE alarm_open')
        self.assertEqual(make(1, run_pass=engine.run_once).run(), 0)
        queued = {alarm_id for (alarm_id,) in rows('SELECT alarm_id FROM alarm_open')}
        self.assertLessEqual({made[0].pk, made[1].pk}, queued)
        said = Alarm.objects.get(source='system', parameter='alarm_queues_repaired')
        self.assertEqual(said.severity, 'critical')
