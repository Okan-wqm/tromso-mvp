"""The default "No fresh value" rule (owner decision of 2026-11-20; the second review of the water-chemistry audit,
question 3): a probe of a quantity the water limits judge that stops sending is warned of, whatever its pH scale.

- Seeded by sensors 0014 for every quantity a limit can be set on (quantities.JUDGED_CODES, derived from
  farm/water/parameters.py LIMITED), one per quantity, on every channel of it: a channel made later, by any door, is
  covered from its first pass.
- It holds exactly when the place's value is no longer fresh, at the channel's own freshness (heartbeat times fresh
  heartbeats), counted as the page counts it: the page says "no recent data" and the event opens at the same moment;
  a backlog replayed at a reconnect, a server restart or a change of a pH channel's scale opens or closes nothing.
- The database keeps it: never deleted (a check, a trigger), never unmarked or moved to another quantity (the trigger),
  never more than one per quantity, nothing past the freshness, switched off only with a reason.
- Its severity is the farm's; switching it off takes the Delete right on Alarm rules and a reason, logged as critical;
  a channel no active rule covers is the system check sensors.W001's warning and said on the Alarm rules page."""
import importlib
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.checks import run_checks
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog
from farm.models import System
from farm.tests.helpers import role
from farm.water import parameters, read as water_read

from sensors import alarms, bindings, quantities
from sensors.models import AlarmEvent, AlarmRule, Channel, ChannelState

from . import SensorsCase, make_channel

KEEPER = ('view_alarmrule', 'change_alarmrule', 'view_channel')


def default(code):
    return AlarmRule.objects.get(quantity=code, is_default=True)


class FreshRuleCase(SensorsCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ras = System.objects.create(name='RAS 1', code='R1', site=cls.site, production_department=cls.hall)
        cls.ph = make_channel(cls.device, 'ph', code='PH', heartbeat_s=60)              # fresh for 3 x 60 s
        cls.placed_at = timezone.now() - timedelta(days=1)
        bindings.move(cls.user, cls.ph, cls.placed_at, system=cls.ras)

    def setUp(self):
        self.now = timezone.now()

    def send(self, channel, value, at, received=None):
        """The channel's last good value as the ingest leaves it: measured at `at`, received at `received` (then)."""
        received = received or at
        ChannelState.objects.update_or_create(channel_no=channel.channel_no, defaults=dict(
            last_value=value, last_value_ts=at, last_good_at=received, last_seen_at=received))

    def open_events(self, channel=None):
        found = AlarmEvent.objects.filter(closed_at__isnull=True, rule__is_default=True)
        return list(found.filter(channel_no=(channel or self.ph).channel_no))


class SeededTests(FreshRuleCase):
    def test_every_quantity_the_limits_judge_has_its_default_rule_a_warning_at_the_freshness(self):
        found = AlarmRule.objects.filter(is_default=True)
        self.assertEqual(sorted(rule.quantity for rule in found), sorted(quantities.JUDGED_CODES))
        self.assertEqual({(rule.kind, rule.channel_id, rule.threshold, rule.for_s, rule.hysteresis, rule.severity,
                           rule.is_active) for rule in found}, {('no_data', None, None, 0, 0.0, 'warning', True)})

    def test_the_judged_quantities_are_derived_from_the_limits_and_hold_every_input_of_the_nh3(self):
        limited = {parameter.code for parameter in parameters.LIMITED}
        self.assertEqual(quantities.JUDGED_CODES, [code for code in quantities.WATER_CODES if code in limited])
        # What the judged NH₃ and a sensor pH's conversion are worked out from: each a quantity of its own rule.
        inputs = {parameters.TAN, parameters.PH, parameters.TEMPERATURE, parameters.SALINITY, *water_read.IONIC_INPUTS}
        self.assertLessEqual(inputs, set(quantities.JUDGED_CODES))
        self.assertFalse({quantity.code for quantity in quantities.PROCESS} & set(quantities.JUDGED_CODES))

    def test_the_migration_seeds_the_quantities_as_the_code_lists_them(self):
        """A migration never reads live code; this holds its list to the code's, so a quantity a limit can judge that
        is added later fails here until its migration seeds its rule."""
        migration = importlib.import_module('sensors.migrations.0014_default_no_data_rules')
        self.assertEqual(migration.JUDGED, quantities.JUDGED_CODES)


class DatabaseKeepsItTests(FreshRuleCase):
    def assertRefused(self, constraint, change):
        with self.assertRaises(IntegrityError) as caught, transaction.atomic():
            change()
        if constraint is not None:
            name = getattr(getattr(caught.exception.__cause__, 'diag', None), 'constraint_name', None)
            self.assertEqual(name, constraint, str(caught.exception))
        return str(caught.exception)

    def test_it_is_never_deleted_nor_unmarked_nor_moved(self):
        rule = default('ph')
        rows = AlarmRule.all_objects.filter(pk=rule.pk)
        self.assertIn('never deleted', self.assertRefused(None, rows.delete))
        self.assertRefused('chk_sensors_alarm_rule_default', lambda: rows.update(is_deleted=True))
        self.assertIn('stays the default rule', self.assertRefused(None, lambda: rows.update(is_default=False)))
        self.assertIn('stays the default rule', self.assertRefused(None, lambda: rows.update(quantity='flow_m3_h')))
        self.assertRefused('uq_sensors_alarm_rule_default', lambda: AlarmRule.objects.create(
            quantity='ph', kind='no_data', is_default=True))

    def test_it_stays_at_the_freshness_and_is_switched_off_only_with_a_reason(self):
        rows = AlarmRule.objects.filter(pk=default('ph').pk)
        for change in ({'for_s': 60}, {'hysteresis': 1}, {'threshold': 7}, {'kind': 'device_offline'},
                       {'is_active': False}, {'is_active': False, 'off_reason': ''}):
            with self.subTest(change=change):
                self.assertRefused('chk_sensors_alarm_rule_default', lambda: rows.update(**change))
        rows.update(is_active=False, off_reason='The pH probes are out for service until Friday.')
        rows.update(severity='critical', is_active=True, off_reason='')
        self.assertEqual((default('ph').severity, default('ph').is_active), ('critical', True))

    def test_a_process_quantity_takes_none(self):
        self.assertRefused('chk_sensors_alarm_rule_default', lambda: AlarmRule.objects.create(
            quantity='flow_m3_h', kind='no_data', is_default=True))

    def test_an_ordinary_rule_is_deleted_as_before(self):
        rule = AlarmRule.objects.create(quantity='ph', kind='no_data', for_s=600)
        AlarmRule.all_objects.filter(pk=rule.pk).delete()
        self.assertFalse(AlarmRule.all_objects.filter(pk=rule.pk).exists())


class HoldsTests(FreshRuleCase):
    def test_it_holds_once_the_value_is_no_longer_fresh_as_the_page_says_it(self):
        fresh_s = Channel.objects.get(pk=self.ph.pk).fresh_s
        self.assertEqual(fresh_s, 180)
        measured = self.now - timedelta(seconds=fresh_s)
        self.send(self.ph, 7.5, measured)
        alarms.evaluate(self.now)
        self.assertEqual(self.open_events(), [])                    # exactly at its freshness: still fresh
        alarms.evaluate(self.now + timedelta(seconds=1))
        [event] = self.open_events()
        self.assertEqual((event.rule, event.opened_at), (default('ph'), self.now + timedelta(seconds=1)))
        state = alarms.read.latest([self.ph.channel_no], self.now + timedelta(seconds=1))[self.ph.channel_no]
        self.assertFalse(state.fresh)
        self.send(self.ph, 7.6, self.now + timedelta(seconds=2))   # the probe sends again
        alarms.evaluate(self.now + timedelta(seconds=3))
        self.assertEqual(self.open_events(), [])
        self.assertEqual(AlarmEvent.objects.get().closed_at, self.now + timedelta(seconds=3))

    def test_the_channels_own_fresh_heartbeats_are_its_threshold(self):
        Channel.objects.filter(pk=self.ph.pk).update(fresh_heartbeats=10)            # 600 s
        self.send(self.ph, 7.5, self.now - timedelta(seconds=599))
        alarms.evaluate(self.now)
        self.assertEqual(self.open_events(), [])
        alarms.evaluate(self.now + timedelta(seconds=2))
        self.assertEqual(len(self.open_events()), 1)

    def test_a_channel_made_later_is_covered_from_its_first_pass_whatever_its_scale(self):
        """No row per channel: the rule is its quantity's, so a channel made by any door (here straight in the
        database, as the demo setup and a restore make them) is covered; a pH on the total scale as one on NBS."""
        tris = Channel.objects.create(device=self.device, quantity='ph', code='PH-T', name='TRIS pH', value_path='/ph_t',
                                      ph_scale='total', **{**quantities.defaults('ph'), 'heartbeat_s': 60})
        oxygen = make_channel(self.device, 'oxygen_mg_l', code='O2')
        flow = make_channel(self.device, 'flow_m3_h', code='FLOW')
        bindings.move(self.user, tris, self.now - timedelta(hours=1), role='backup', system=self.ras)
        for channel in (oxygen, flow):
            bindings.move(self.user, channel, self.now - timedelta(hours=1), system=self.ras)
        self.send(self.ph, 7.5, self.now)
        alarms.evaluate(self.now)
        opened = {event.channel_no: event.rule.quantity for event in AlarmEvent.objects.filter(closed_at__isnull=True)}
        self.assertEqual(opened, {tris.channel_no: 'ph', oxygen.channel_no: 'oxygen_mg_l'})   # never sent; no flow rule

    def test_a_backlog_replayed_at_a_reconnect_keeps_it_open(self):
        """The ingest reconnects and a gateway delivers what it held: received now, measured an hour ago. The page says
        "no recent data" (State.fresh), so the rule keeps holding, never closed and opened again."""
        self.send(self.ph, 7.5, self.now - timedelta(hours=1))
        alarms.evaluate(self.now)
        [event] = self.open_events()
        self.send(self.ph, 7.4, self.now - timedelta(minutes=50), received=self.now + timedelta(seconds=5))
        alarms.evaluate(self.now + timedelta(seconds=10))
        self.assertEqual(self.open_events(), [event])
        self.assertEqual(AlarmEvent.objects.count(), 1)

    def test_a_restart_or_a_second_pass_opens_nothing_again(self):
        self.send(self.ph, 7.5, self.now - timedelta(hours=1))
        for seconds in (0, 0, 30, 60):
            alarms.evaluate(self.now + timedelta(seconds=seconds))
        self.assertEqual(AlarmEvent.objects.count(), 1)

    def test_a_change_of_the_ph_scale_opens_or_closes_nothing(self):
        """The scale's change touches no state: a probe that goes on sending raises nothing, and one that stops is warned
        of at its own value's freshness, counted from the value and not from the change."""
        measured = self.now - timedelta(seconds=60)
        self.send(self.ph, 7.95, measured)
        channel = Channel.objects.get(pk=self.ph.pk)
        channel.ph_scale = 'total'
        channel.save()
        alarms.evaluate(self.now)
        self.assertEqual(self.open_events(), [])
        alarms.evaluate(measured + timedelta(seconds=181))
        self.assertEqual(len(self.open_events()), 1)

    def test_a_channel_in_maintenance_or_out_of_the_water_is_not_checked(self):
        Channel.objects.filter(pk=self.ph.pk).update(state='maintenance')
        alarms.evaluate(self.now)
        self.assertEqual(self.open_events(), [])
        Channel.objects.filter(pk=self.ph.pk).update(state='active')
        bindings.unbind(self.user, Channel.objects.get(pk=self.ph.pk), self.now - timedelta(hours=1))
        alarms.evaluate(self.now)
        self.assertEqual(self.open_events(), [])


class CoverageCheckTests(FreshRuleCase):
    def switch_off(self, code='ph'):
        AlarmRule.objects.filter(pk=default(code).pk).update(is_active=False, off_reason='Probes out for service.')

    def test_a_channel_no_active_rule_covers_is_listed_and_warned_of_by_the_check(self):
        self.assertEqual(alarms.uncovered(), [])
        self.assertEqual([found for found in run_checks(databases=['default']) if found.id == 'sensors.W001'], [])
        self.switch_off()
        self.assertEqual(alarms.uncovered(), [self.ph])
        [warning] = [found for found in run_checks(databases=['default']) if found.id == 'sensors.W001']
        self.assertIn('PROBE-1 › PH (pH (NBS scale))', warning.msg)
        self.send(self.ph, 7.5, self.now - timedelta(hours=1))
        alarms.evaluate(self.now)
        self.assertEqual(self.open_events(), [])                    # switched off: nothing holds
        AlarmRule.objects.create(channel=self.ph, kind='no_data', for_s=300)        # a rule of the channel's own
        self.assertEqual(alarms.uncovered(), [])

    def test_a_channel_in_maintenance_or_on_an_inactive_device_is_not_listed(self):
        self.switch_off()
        Channel.objects.filter(pk=self.ph.pk).update(state='maintenance')
        self.assertEqual(alarms.uncovered(), [])
        Channel.objects.filter(pk=self.ph.pk).update(state='active')
        type(self.device).objects.filter(pk=self.device.pk).update(is_active=False)
        self.assertEqual(alarms.uncovered(), [])


class PageTests(FreshRuleCase):
    def setUp(self):
        super().setUp()
        self.keeper = get_user_model().objects.create_user('keeper', 'keeper@example.com', 'x')
        self.keeper.groups.add(role('Alarm keeper', *KEEPER))
        self.client.force_login(self.keeper)
        self.rule = default('ph')

    def post(self, **changed):
        values = {'severity': self.rule.severity, 'is_active': 'on', 'off_reason': '', 'version': self.rule.version,
                  **changed}
        values = {key: value for key, value in values.items() if value is not None}
        return self.client.post(reverse('sensors:alarmrule_edit', args=[self.rule.pk]), values)

    def allow_switching_off(self):
        self.keeper.groups.add(role('Alarm admin', 'delete_alarmrule'))
        self.keeper = get_user_model().objects.get(pk=self.keeper.pk)              # its rights read again
        self.client.force_login(self.keeper)

    def test_the_list_marks_it_and_offers_no_delete(self):
        self.allow_switching_off()
        page = self.client.get(reverse('sensors:alarmrule_list'))
        self.assertContains(page, 'Default')
        self.assertNotContains(page, reverse('sensors:alarmrule_delete', args=[self.rule.pk]))
        self.assertEqual(self.client.get(reverse('sensors:alarmrule_delete', args=[self.rule.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('sensors:alarmrule_delete', args=[self.rule.pk])).status_code, 403)
        self.assertTrue(AlarmRule.objects.filter(pk=self.rule.pk).exists())

    def test_its_severity_is_the_farms_and_what_it_is_cannot_be_changed(self):
        response = self.post(severity='critical', for_s='600', kind='rate', threshold='1', quantity='tan_mg_l')
        self.assertIn(response.status_code, (204, 302), response.context and response.context['form'].errors)
        rule = default('ph')
        self.assertEqual((rule.severity, rule.for_s, rule.kind, rule.threshold, rule.quantity),
                         ('critical', 0, 'no_data', None, 'ph'))
        entry = AuditLog.objects.get(entity_id=str(rule.pk))
        self.assertEqual(entry.severity, AuditLog.Severity.NORMAL)

    def test_switching_it_off_takes_the_delete_right(self):
        response = self.post(is_active=None, off_reason='Probes out for service.')
        self.assertContains(response, 'Switching a default rule off takes the Delete right on Alarm rules.', status_code=200)
        self.assertTrue(default('ph').is_active)

    def test_switching_it_off_takes_a_reason_and_is_logged_as_critical(self):
        self.allow_switching_off()
        response = self.post(is_active=None)
        self.assertContains(response, 'Say why the default rule is switched off', status_code=200)
        self.assertTrue(default('ph').is_active)
        response = self.post(is_active=None, off_reason='The pH probes are out for service until Friday.')
        self.assertIn(response.status_code, (204, 302), response.context and response.context['form'].errors)
        rule = default('ph')
        self.assertEqual((rule.is_active, rule.off_reason), (False, 'The pH probes are out for service until Friday.'))
        entry = AuditLog.objects.get(entity_id=str(rule.pk))
        self.assertEqual((entry.severity, entry.user), (AuditLog.Severity.CRITICAL, self.keeper))
        self.assertEqual(entry.changes['Why it is switched off'], [None, 'The pH probes are out for service until Friday.'])
        # The list says it, and which channel is left without a rule.
        page = self.client.get(reverse('sensors:alarmrule_list'))
        self.assertContains(page, 'The pH probes are out for service until Friday.')
        self.assertContains(page, 'has no active “No fresh value” rule')
        self.assertContains(page, 'PROBE-1 › PH')

    def test_switched_on_again_its_reason_goes(self):
        AlarmRule.objects.filter(pk=self.rule.pk).update(is_active=False, off_reason='Probes out for service.')
        self.rule = default('ph')
        response = self.post(off_reason='Probes out for service.')
        self.assertIn(response.status_code, (204, 302), response.context and response.context['form'].errors)
        self.assertEqual((default('ph').is_active, default('ph').off_reason), (True, ''))
        self.assertEqual(AuditLog.objects.get(entity_id=str(self.rule.pk)).severity, AuditLog.Severity.NORMAL)

    def test_an_ordinary_rules_form_has_no_reason_and_is_deleted_as_before(self):
        self.allow_switching_off()
        rule = AlarmRule.objects.create(channel=self.ph, kind='no_data', for_s=600)
        page = self.client.get(reverse('sensors:alarmrule_edit', args=[rule.pk]))
        self.assertNotContains(page, 'name="off_reason"')
        self.assertContains(page, 'name="for_s"')
        self.client.post(reverse('sensors:alarmrule_delete', args=[rule.pk]))
        self.assertFalse(AlarmRule.objects.filter(pk=rule.pk).exists())


class MigrationTests(TransactionTestCase):
    """sensors 0014 forward, back and forward again: going back removes the rules it made, so a migration further back
    that narrows the quantities a rule may name finds none (alarms/tests/test_migration_reverse.py goes back to sensors
    0007), keeps one with events or changed by a person (logged), and going forward again marks a kept one the default."""
    serialized_rollback = True

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([target] if target else executor.loader.graph.leaf_nodes())

    def tearDown(self):
        self.migrate(None)

    def test_back_and_forward_again(self):
        ph = default('ph').pk
        AlarmEvent.objects.create(rule_id=ph, channel_no=1, opened_at=timezone.now())
        AlarmRule.objects.filter(pk=default('tan_mg_l').pk).update(severity='critical', version=2)
        self.migrate(('sensors', '0013_channel_ph_scale'))
        with connection.cursor() as cursor:
            cursor.execute('SELECT id, quantity, severity FROM sensors_alarm_rule ORDER BY quantity')
            kept = cursor.fetchall()
        self.assertEqual([(quantity, severity) for _id, quantity, severity in kept],
                         [('ph', 'warning'), ('tan_mg_l', 'critical')])
        notes = AuditLog.objects.filter(entity_type='alarm rule', user_name='system').values_list('changes', flat=True)
        self.assertEqual(sorted(note['Note'][1] for note in notes),
                         ['sensors 0014 reversed: kept as an ordinary "No fresh value" rule, changed by a person since.',
                          'sensors 0014 reversed: kept as an ordinary "No fresh value" rule, its alarms are history.'])
        self.migrate(None)
        self.assertEqual(sorted(rule.quantity for rule in AlarmRule.objects.filter(is_default=True)),
                         sorted(quantities.JUDGED_CODES))
        self.assertEqual(default('ph').pk, ph)                         # marked again, no second rule
        self.assertEqual(default('tan_mg_l').severity, 'critical')
        self.assertEqual(AlarmRule.objects.count(), len(quantities.JUDGED_CODES))
