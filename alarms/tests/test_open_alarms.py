"""The open alarms' own queue (alarms.OpenAlarm, alarms 0025; review 1, F1; review 2, H2): the database keeps it, whoever
writes and in whatever order, a check finds it out of step, and what reads the open alarms reads it, never every
alarm, clearance, acknowledgement, notification, escalation and snooze ever recorded. Measured beside 50,000 and again
beside 100,000 alarms of history (each with its notification, escalation, clearance, acknowledgement and an ended
snooze) and as many sensor rule events (each closed, its alarm cleared), counted by PostgreSQL (core.testing.reads): a
whole pass of the alarm worker (`engine.run_once`, its sensor events' mirror included: review 3, M1), its notify step,
the pages' floods, the open list and the overview's open alarms read no more of each history table beside the one than
beside the other (core.testing.assert_reads_do_not_grow)."""
from datetime import timedelta

from django.db import DatabaseError, connection, transaction
from django.test import TransactionTestCase, override_settings

from core.testing import assert_reads_do_not_grow, reads
from sensors.models import AlarmEvent, AlarmRule
from sensors.tests import make_channel, make_connection, make_device, make_format

from .. import checks, engine, floods, read, services, sources
from ..models import OPEN, Alarm, AlarmClearance
from ..rules import current
from . import RECORDING, AlarmsCase, AlarmsWorld

STEP = 50_000
HISTORY_TABLES = ('alarms', 'alarm_clearances', 'alarm_acknowledgements', 'alarm_notifications', 'alarm_escalations',
                  'alarm_shelves', 'alarm_shelve_ends', 'sensors_alarm_event')


def rows(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall() if cursor.description else None


class OpenWorld(AlarmsWorld):
    def open(self, name, severity='critical'):
        """A new alarm of the alarm system, of its own kind, open."""
        return services.open_alarm(source='system', farm_wide=True, parameter=name, severity=severity, at=self.now,
                                   summary=name, site=self.bergen)


class OpenQueueTests(OpenWorld, AlarmsCase):
    def queue(self):
        return {alarm_id for (alarm_id,) in rows('SELECT alarm_id FROM alarm_open')}

    def test_the_database_keeps_the_queue_whoever_writes(self):
        made = [self.open(f'open{number}') for number in range(3)]
        services.clear(made[0], self.now, 'returned')
        (raw,) = rows("INSERT INTO alarms (source, parameter, severity, opened_at, summary) VALUES ('system', 'raw', "
                      "'warning', %s, 'raw') RETURNING id", [self.now])[0]        # raw SQL, as a fixture writes
        unclear = set(Alarm.objects.exclude(pk__in=AlarmClearance.objects.values('alarm')).values_list('pk', flat=True))
        self.assertEqual(self.queue(), unclear)
        self.assertEqual(unclear, {made[1].pk, made[2].pk, raw})
        self.assertEqual(set(Alarm.objects.filter(OPEN).values_list('pk', flat=True)), unclear)
        rows("INSERT INTO alarm_clearances (alarm_id, cleared_at, cause) VALUES (%s, %s, 'restored')", [raw, self.now])
        self.assertEqual(self.queue(), {made[1].pk, made[2].pk})

    def test_a_clearance_written_before_its_alarm_keeps_it_out_of_the_queue(self):
        """The keys are checked at the transaction's end, so a fixture, a repair or a restore may write a clearance
        before its alarm (H2 a): the alarm's trigger leaves an alarm that has its clearance out."""
        (alarm,) = rows("SELECT nextval(pg_get_serial_sequence('alarms', 'id'))")[0]
        rows("INSERT INTO alarm_clearances (alarm_id, cleared_at, cause) VALUES (%s, %s, 'restored')", [alarm, self.now])
        rows("INSERT INTO alarms (id, source, parameter, severity, opened_at, summary) VALUES (%s, 'system', 'early', "
             "'warning', %s, 'early')", [alarm, self.now])
        self.assertNotIn(alarm, self.queue())
        self.assertEqual(checks.open_alarms_hold(None), [])

    def test_a_temporary_table_can_neither_call_the_triggers_nor_be_written_by_them(self):
        """The two attacks on a SECURITY DEFINER trigger (core.operations.DefinerTrigger), made here as the owner, who
        may: deploy/scripts/check-roles.sh makes them as the app role, who may not even make the forged trigger."""
        rows('SET CONSTRAINTS ALL IMMEDIATE')
        with self.assertRaisesMessage(DatabaseError, 'runs for public.alarms only'), transaction.atomic():
            rows('CREATE TEMP TABLE alarms (LIKE public.alarms INCLUDING DEFAULTS INCLUDING IDENTITY)')   # forged
            rows('CREATE TRIGGER forged AFTER INSERT ON pg_temp.alarms REFERENCING NEW TABLE AS opened '
                 'FOR EACH STATEMENT EXECUTE FUNCTION public.alarm_open_opened()')
            rows("INSERT INTO pg_temp.alarms (source, parameter, severity, opened_at, summary) VALUES ('system', "
                 "'forged', 'warning', now(), 'forged')")

        class Shadowed(Exception):
            pass
        with self.assertRaises(Shadowed), transaction.atomic():                  # turned aside: a table of the name
            rows('CREATE TEMP TABLE alarm_open (alarm_id bigint)')
            (alarm,) = rows("INSERT INTO public.alarms (source, parameter, severity, opened_at, summary) VALUES "
                            "('system', 'shadowed', 'warning', now(), 'shadowed') RETURNING id")[0]
            self.assertEqual(rows('SELECT count(*) FROM public.alarm_open WHERE alarm_id = %s', [alarm]), [(1,)])
            self.assertEqual(rows('SELECT count(*) FROM pg_temp.alarm_open'), [(0,)])
            raise Shadowed

    def test_a_queue_out_of_step_with_the_clearances_is_named_both_ways(self):
        made = [self.open(f'open{number}') for number in range(2)]
        self.assertEqual(checks.open_alarms_hold(None), [])
        rows('SET CONSTRAINTS ALL IMMEDIATE')         # (the test's own pending key checks, or TRUNCATE and ALTER wait)
        rows('TRUNCATE alarm_open')                                       # what a superuser's TRUNCATE leaves
        (missing,) = checks.open_alarms_hold(None)
        self.assertEqual(missing.id, 'alarms.W001')
        self.assertIn('2 open alarm(s) are missing', missing.msg)
        self.assertIn(f'{made[0].pk}, {made[1].pk}', missing.msg)
        rows(missing.hint.split(': ', 1)[1])                              # the repair, as the hint says it
        self.assertEqual(checks.open_alarms_hold(None), [])
        rows('SET CONSTRAINTS ALL IMMEDIATE')
        rows('ALTER TABLE alarm_clearances DISABLE TRIGGER trg_alarm_clearances_open')   # a trigger set aside
        services.clear(made[0], self.now, 'returned')
        rows('SET CONSTRAINTS ALL IMMEDIATE')
        rows('ALTER TABLE alarm_clearances ENABLE TRIGGER trg_alarm_clearances_open')
        (cleared,) = checks.open_alarms_hold(None)
        self.assertIn('1 cleared alarm(s) are still in', cleared.msg)
        rows(cleared.hint.split(': ', 1)[1])
        self.assertEqual(checks.open_alarms_hold(None), [])
        self.assertEqual(self.queue(), {made[1].pk})


class MirrorQueueTests(OpenWorld, AlarmsCase):
    """The sensor events still to mirror (alarms.UnmirroredEvent, alarms 0026; review 3, M1)."""

    def setUp(self):
        super().setUp()
        self.channel = make_channel(make_device(make_connection(), make_format(), self.bergen), 'flow_m3_h')
        self.rule = AlarmRule.objects.create(kind='low', severity='warning', channel=self.channel, threshold=10)

    def event(self, closed=True):
        return AlarmEvent.objects.create(rule=self.rule, channel_no=self.channel.channel_no, opened_at=self.now,
                                         closed_at=self.now if closed else None, peak=4)

    def queue(self):
        return {event_id for (event_id,) in rows('SELECT event_id FROM alarm_unmirrored_events')}

    def test_the_database_keeps_the_events_to_mirror_whoever_writes(self):
        written = self.event()
        (raw,) = rows("INSERT INTO sensors_alarm_event (rule_id, channel_no, opened_at, closed_at) VALUES (%s, %s, %s, "
                      '%s) RETURNING id', [self.rule.pk, self.channel.channel_no, self.now, self.now])[0]
        self.assertEqual(self.queue(), {written.pk, raw})
        self.assertEqual(sources.sensor_events(), (2, 2))                        # mirrored, and cleared at once
        self.assertEqual(self.queue(), set())
        self.assertEqual(sources.sensor_events(), (0, 0))
        gone = self.event()
        rows('DELETE FROM sensors_alarm_event WHERE id = %s', [gone.pk])         # (no code deletes one; a repair may)
        self.assertEqual(self.queue(), set())

    def test_an_alarm_written_before_its_event_keeps_it_out_of_the_queue(self):
        """The keys are checked at the transaction's end, so a fixture, a repair or a restore may write an alarm before
        its event: the event's trigger leaves an event that has its alarm out."""
        (event,) = rows("SELECT nextval(pg_get_serial_sequence('sensors_alarm_event', 'id'))")[0]
        rows("INSERT INTO alarms (source, sensor_event_id, parameter, severity, opened_at, summary) VALUES "
             "('sensor_rule', %s, '', 'warning', %s, 'early')", [event, self.now])
        rows('INSERT INTO sensors_alarm_event (id, rule_id, channel_no, opened_at) VALUES (%s, %s, %s, %s)',
             [event, self.rule.pk, self.channel.channel_no, self.now])
        self.assertEqual(self.queue(), set())
        self.assertEqual(checks.unmirrored_events_hold(None), [])

    def test_a_queue_out_of_step_with_the_alarms_is_named_both_ways(self):
        made = [self.event() for _ in range(2)]
        self.assertEqual(checks.unmirrored_events_hold(None), [])
        rows('SET CONSTRAINTS ALL IMMEDIATE')         # (the test's own pending key checks, or TRUNCATE and ALTER wait)
        rows('TRUNCATE alarm_unmirrored_events')                          # what a superuser's TRUNCATE leaves
        (missing,) = checks.unmirrored_events_hold(None)
        self.assertEqual(missing.id, 'alarms.W002')
        self.assertIn('2 sensor alarm event(s) without an alarm are missing', missing.msg)
        self.assertIn(f'{made[0].pk}, {made[1].pk}', missing.msg)
        rows(missing.hint.split(': ', 1)[1])                              # the repair, as the hint says it
        self.assertEqual(checks.unmirrored_events_hold(None), [])
        rows('SET CONSTRAINTS ALL IMMEDIATE')
        rows('ALTER TABLE alarms DISABLE TRIGGER trg_alarms_mirrored')    # a trigger set aside
        sources.mirror(made[0])
        rows('SET CONSTRAINTS ALL IMMEDIATE')
        rows('ALTER TABLE alarms ENABLE TRIGGER trg_alarms_mirrored')
        (stale,) = checks.unmirrored_events_hold(None)
        self.assertEqual(stale.id, 'alarms.W002')
        self.assertIn('1 sensor alarm event(s) an alarm mirrors already are still in', stale.msg)
        self.assertEqual(sources.sensor_events(), (1, 1))                 # the stale one passed over, never twice
        rows(stale.hint.split(': ', 1)[1])
        self.assertEqual(checks.unmirrored_events_hold(None), [])
        self.assertEqual(self.queue(), set())


@override_settings(ALARM_TRANSPORTS=RECORDING)
class OpenHistoryTests(OpenWorld, TransactionTestCase):
    """What the readers read beside a growing history, committed and vacuumed as a farm's is (written in the measuring
    transaction, its rows are not all-visible and the planner's looks at the ends of indexes over them read thousands of
    rows each: a cost of the test's own making, review 2, M2)."""
    serialized_rollback = True

    def grow(self):
        """STEP more alarms opened 30 days before the test's moment, each notified, escalated, snoozed (the snooze
        ended), acknowledged and cleared, and STEP more sensor rule events of then, each closed and mirrored by its
        alarm, cleared (review 3, M1); committed and vacuumed. Returns STEP: the fewest rows a history table gained."""
        if not hasattr(self, 'sensor_rule'):
            channel = make_channel(make_device(make_connection(), make_format(), self.bergen), 'flow_m3_h')
            self.sensor_rule = AlarmRule.objects.create(kind='low', severity='warning', channel=channel, threshold=10)
        steps = [
            ("INSERT INTO sensors_alarm_event (rule_id, channel_no, opened_at, closed_at, peak) SELECT %s, %s, "
             "%s::timestamptz - interval '30 days' + n * interval '1 second', %s::timestamptz - interval '30 days' + "
             "n * interval '1 second' + interval '1 minute', 4 FROM generate_series(1, %s) n",
             [self.sensor_rule.pk, self.sensor_rule.channel.channel_no, self.now, self.now, STEP]),
            ("INSERT INTO alarms (source, sensor_event_id, parameter, severity, opened_at, summary) SELECT "
             "'sensor_rule', e.id, '', 'warning', e.opened_at, 'old event' FROM sensors_alarm_event e WHERE NOT "
             'EXISTS (SELECT 1 FROM alarms a WHERE a.sensor_event_id = e.id)', None),
            ("INSERT INTO alarm_clearances (alarm_id, cleared_at, cause) SELECT a.id, e.closed_at, 'event_closed' "
             "FROM alarms a JOIN sensors_alarm_event e ON e.id = a.sensor_event_id WHERE NOT EXISTS (SELECT 1 FROM "
             'alarm_clearances c WHERE c.alarm_id = a.id)', None),
            ("INSERT INTO alarms (source, parameter, severity, opened_at, summary) SELECT 'system', 'old', 'warning', "
             "%s::timestamptz - interval '30 days', 'old ' || n FROM generate_series(1, %s) n", [self.now, STEP]),
            ('INSERT INTO alarm_notifications (alarm_id, recipient_id, channel, level, queued_at, kind) SELECT a.id, %s, '
             "'push', 0, a.opened_at, 'alarm' FROM alarms a WHERE a.parameter = 'old' AND NOT EXISTS (SELECT 1 FROM "
             'alarm_notifications n WHERE n.alarm_id = a.id)', [self.operator.pk]),
            ("INSERT INTO alarm_escalations (alarm_id, level, escalated_at) SELECT a.id, 1, a.opened_at + interval "
             "'10 minutes' FROM alarms a WHERE a.parameter = 'old' AND NOT EXISTS (SELECT 1 FROM alarm_escalations e "
             'WHERE e.alarm_id = a.id)', None),
            ("INSERT INTO alarm_shelves (alarm_id, user_id, shelved_at, until, reason) SELECT a.id, %s, a.opened_at + "
             "interval '2 minutes', a.opened_at + interval '32 minutes', 'old' FROM alarms a WHERE a.parameter = 'old' "
             'AND NOT EXISTS (SELECT 1 FROM alarm_shelves s WHERE s.alarm_id = a.id)', [self.operator.pk]),
            ("INSERT INTO alarm_shelve_ends (shelve_id, user_id, ended_at) SELECT s.id, %s, s.shelved_at + interval "
             "'3 minutes' FROM alarm_shelves s WHERE NOT EXISTS (SELECT 1 FROM alarm_shelve_ends x WHERE x.shelve_id = "
             's.id)', [self.operator.pk]),
            ("INSERT INTO alarm_acknowledgements (alarm_id, user_id, acknowledged_at, device, app) SELECT a.id, %s, "
             "a.opened_at + interval '5 minutes', '', 'console' FROM alarms a WHERE a.parameter = 'old' AND NOT EXISTS "
             '(SELECT 1 FROM alarm_acknowledgements k WHERE k.alarm_id = a.id)', [self.operator.pk]),
            ("INSERT INTO alarm_clearances (alarm_id, cleared_at, cause) SELECT a.id, a.opened_at + interval '1 hour', "
             "'returned' FROM alarms a WHERE a.parameter = 'old' AND NOT EXISTS (SELECT 1 FROM alarm_clearances c "
             'WHERE c.alarm_id = a.id)', None),
        ]
        for sql, params in steps:
            rows(sql, params)
        rows('VACUUM ANALYZE ' + ', '.join(HISTORY_TABLES) + ', alarm_open, alarm_unmirrored_events')
        return STEP

    def fresh(self, opened, name):
        """Three open criticals for a look, the last look's cleared: the same work at every look."""
        for alarm in opened:
            services.clear(alarm, self.now, 'returned')
        opened[:] = [self.open(f'{name}{len(self.looks)}{number}') for number in range(3)]
        self.looks.append(1)

    def test_a_whole_pass_reads_the_open_alarms_never_the_history(self):
        """engine.run_once, every step of it: the notify step, the sensor events' mirror (a new event to mirror at
        each look, among the history's mirrored ones; review 3, M1) and the supervision of the criticals told to
        nobody included (review 2, M1)."""
        self.looks, opened = [], []

        def run_once():
            self.fresh(opened, 'pass')
            event = AlarmEvent.objects.create(rule=self.sensor_rule, channel_no=self.sensor_rule.channel.channel_no,
                                              opened_at=self.now - timedelta(minutes=2), closed_at=self.now, peak=4)
            with transaction.atomic(), reads() as found:
                summary = engine.run_once(self.now)
            self.assertFalse(summary.failed_steps)
            self.assertTrue(Alarm.objects.filter(sensor_event=event).exists())         # the new one was mirrored
            return found
        assert_reads_do_not_grow(self, self.grow, run_once, HISTORY_TABLES, 'a whole pass')

    def test_the_pass_notify_step_reads_the_open_alarms_never_the_history(self):
        self.looks, opened = [], []

        def notify():
            self.fresh(opened, 'open')
            summary = engine.Summary()
            with transaction.atomic(), reads() as found:
                engine.notify(self.now, summary, current())
            self.assertFalse(summary.failed_steps)
            return found
        assert_reads_do_not_grow(self, self.grow, notify, HISTORY_TABLES, 'the notify step')

    def test_the_scheduled_check_of_the_queues_reads_each_table_it_compares_at_most_twice(self):
        """The worker's check of both queues (alarms.checks._queue_holds, once every worker.QUEUE_CHECK_EVERY) reads the
        history, by design, never in every pass: its cost is bounded by two scans of each table it compares (each of
        its two queries one at most), beside 50,000 and beside 100,000 rows of each, never a scan per row."""
        compared = ('alarms', 'alarm_clearances', 'sensors_alarm_event', 'alarm_open', 'alarm_unmirrored_events')
        for _grow in range(2):
            self.grow()
            sizes = {table: rows(f'SELECT count(*) FROM {table}')[0][0] for table in compared}
            with transaction.atomic(), reads() as found:
                self.assertEqual([checks._queue_holds(queue) for queue in checks.QUEUES], [([], []), ([], [])])
            for table in compared:
                with self.subTest(table=table, alarms=sizes['alarms']):
                    self.assertLessEqual(found.read(table), 2 * sizes[table] + 100, found.described(table))

    def test_the_pages_read_the_open_alarms_never_the_history(self):
        opened = {self.open(f'open{number}').pk for number in range(3)}

        def look(what, call):
            def measure():
                with transaction.atomic(), reads() as found:
                    got = call()
                if what == 'the open list':
                    self.assertEqual({alarm.pk for alarm in got}, opened)
                if what == 'the open alarms':
                    self.assertEqual(len(got), 3)
                return found
            return measure
        for what, call in (('the floods', lambda: floods.open_floods(current())),
                           ('the open list', lambda: list(read.listing('open'))),
                           ('the open alarms', read.open_alarms)):
            assert_reads_do_not_grow(self, self.grow, look(what, call), HISTORY_TABLES, what)
