"""A unit with fish whose oxygen has no fresh value is critical (owner decisions of 2026-11-23; they reverse, for the
oxygen alone, the "no recent data … never red" of 2026-11-04):

1. On every page that says the water's status: the Small and Big cards, the wall, the pane, the band's chip, the water
   page's table, Production units and the production overview turn red, saying "Dissolved oxygen (mg/L O₂): no recent
   data" (with its age where it has an old value): one judgement, farm.water.read.PointWater.silent_oxygen.
2. In the alarms: a silent oxygen probe is its default "No fresh value" rule's critical alarm; a typed oxygen sample
   grown old, or a unit with no oxygen probe, is a critical alarm of the alarm system, one per unit, never a second
   one beside the probe's.
3. Only where the unit holds fish on its own day: a fallow or empty unit stays grey "no recent data" and raises no
   alarm, the sensors' default rule included.
The other parameters keep their rule: a silent pH probe is a warning, and the card's state is as it was.

Real sensor channels, the real pages and the real alarm engine (the fixture of test_stopped_probe)."""
from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import translation

from alarms import engine
from alarms.models import Alarm
from farm.models import SamplingPoint, System, Tank
from farm.stock import services as stock_services
from farm.tests.helpers import point_of, stock_fish
from farm.tests.test_stock import make_unit
from farm.water import parameters, read as water_read, services as water_services
from sensors import bindings
from sensors.models import AlarmEvent
from sensors.tests import make_channel, make_device

from .. import read
from ..cards import builtin
from ..cards.resolve import Choice
from . import D
from .test_band import band_of
from .test_small import card_of, text
from .test_stopped_probe import PAGE, PANE, OXYGEN, SALINITY, TEMPERATURE, StoppedProbeCase

SILENT = 'Dissolved oxygen (mg/L O₂): no recent data'
NO_FRESH_OXYGEN = 'no_fresh_oxygen'
PROBE_SILENT = 'oxygen_probe_silent'


class SilentOxygenCase(StoppedProbeCase):
    def sensors(self, unit, code, silent=('oxygen',)):
        """A device on the unit's middle point: oxygen, temperature, salinity and pH (NBS) probes that sent an hour ago;
        those not in `silent` go on sending. Returns {name: channel}."""
        device = make_device(self.connection, self.format, self.bergen, code=code)
        made = {'oxygen': make_channel(device, 'oxygen_mg_l', code='O2'),
                'temperature': make_channel(device, 'temperature_c', code='TEMP'),
                'salinity': make_channel(device, 'salinity_ppt', code='SAL'),
                'ph': make_channel(device, 'ph', code='PH')}
        sent = {'oxygen': OXYGEN, 'temperature': TEMPERATURE, 'salinity': SALINITY, 'ph': 7.2}
        for name, channel in made.items():
            bindings.move(self.user, channel, point=point_of(unit), at=self.now - timedelta(hours=2))
            self.send(channel, sent[name], self.then)
            if name not in silent:
                self.send(channel, sent[name], self.now - timedelta(seconds=30))
        return made

    def typed(self, unit, hours, **values):
        """A typed sample at the unit's middle point, `hours` ago."""
        return water_services.record(self.user, point=point_of(unit), measured_at=self.now - timedelta(hours=hours),
                                     source='manual', values={code: D(str(value)) for code, value in values.items()})

    def card(self, unit):
        return read.cards([unit], self.reader, Choice(view=builtin.SMALL))[0]

    def screens(self, unit):
        """{screen: the unit's card} on the Small and Big screens, the wall and the pane."""
        found = {}
        for name, query in (('small', {'mode': 'small'}), ('big', {'mode': 'big'}),
                            ('wall', {'mode': 'small', 'wall': '1'})):
            found[name] = card_of(self.client.get(PAGE, {**query, 'units': str(unit.pk), 'full': '1'}).content.decode(), unit)
        found['pane'] = card_of(self.client.get(PANE, {'focus': str(unit.pk), 'mode': 'small'}).content.decode(), unit)
        return found

    def chips(self, unit):
        html = self.client.get(PAGE, {'mode': 'small', 'units': str(unit.pk), 'full': '1'}).content.decode()
        strip = next(each for each in band_of(html).walk() if 'monitor-strip' in each.classes)
        return [text(each) for each in strip.children if not isinstance(each, str)]

    def water_row(self, unit):
        rows = self.client.get(reverse('farm:water')).context['rows']
        return next(row for row in rows if row['point'] is not None and row['owner'].pk == unit.pk
                    and row['point'].pk == point_of(unit).pk)

    def unit_row(self, unit):
        rows = self.client.get(reverse('farm:production_units')).context['rows']
        return next(row for row in rows if row['unit'].pk == unit.pk)

    def overview(self):
        return self.client.get(reverse('production_home')).context['water']

    def alarms(self, *times):
        """The open alarms after a pass of the alarm loop at each of `times` (now by default): [(source, severity,
        parameter, summary)] about oxygen, the sensor rules' and the alarm system's."""
        for at in times or (self.now,):
            self.assertEqual(engine.run_once(at).failed_steps, [])
        found = []
        for alarm in Alarm.objects.filter(clearance__isnull=True).select_related('sensor_event__rule'):
            rule = alarm.sensor_event.rule if alarm.sensor_event_id else None
            if alarm.parameter in (parameters.OXYGEN_MG_L, parameters.OXYGEN_PCT, PROBE_SILENT) or (
                    rule is not None and rule.quantity_code in (parameters.OXYGEN_MG_L, parameters.OXYGEN_PCT)):
                found.append((alarm.source, alarm.severity, alarm.parameter, alarm.summary))
        return sorted(found)

    def assert_red(self, unit, said):
        """Every page that says the unit's water status says it critical, with `said` (the reason's start)."""
        card = self.card(unit)
        self.assertEqual(card.state.key, 'critical')
        self.assertTrue(any(reason.startswith(said) for reason in card.state.reasons), card.state.reasons)
        self.assertTrue(any(reason.startswith(said) for reason in card.state.stale), card.state.stale)
        for screen, article in self.screens(unit).items():
            with self.subTest(screen=screen):
                self.assertEqual(article.attrs['data-state'], 'critical')
        self.assertIn(f'Critical {unit.code} O₂ (mg/L): no recent data', self.chips(unit))
        row = self.water_row(unit)
        self.assertEqual((row['water'].status, row['water'].old_alert), ('critical', True))
        self.assertTrue(row['water'].why_silent[0].startswith(said), row['water'].why_silent)
        water = self.unit_row(unit)['water']
        self.assertEqual((water.status, water.old_alert), ('critical', True))
        overview = self.overview()
        self.assertIn(unit.pk, {row['owner'].pk for row in overview['alerts']})
        self.assertGreaterEqual(overview['critical'], 1)


class SilentProbeTests(SilentOxygenCase):
    def test_a_silent_oxygen_probe_with_fish_is_red_everywhere_and_one_critical_alarm(self):
        made = self.sensors(self.t2, 'PROBE-T')
        self.typed(self.t1, 1, oxygen_mg_l='9.0', temperature_c='12.0')     # T-01 is measured: only T-02 is silent
        self.assert_red(self.t2, f'{SILENT}, 1')
        found = self.alarms()
        self.assertEqual([(source, severity) for source, severity, _parameter, _summary in found],
                         [('sensor_rule', 'critical')])                      # the probe's alone: never a second one
        self.assertTrue(found[0][3].startswith(
            'Dissolved oxygen (mg/L O₂): No fresh value · PROBE-T › O2: T-02 › '), found[0][3])
        self.assertIn(made['oxygen'].channel_no, set(Alarm.objects.values_list('sensor_event__channel_no', flat=True)))

    def test_without_fish_a_silent_probe_is_grey_and_raises_no_alarm(self):
        """A fallow tank with its probes off: no red, and its probe's default rule holds nothing."""
        fallow = make_unit('E-01', self.hall)
        Tank.objects.filter(pk=fallow.pk).update(water_type='saltwater', water_origin='seawater')
        fallow.refresh_from_db()
        self.typed(self.t1, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        self.typed(self.t2, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        self.sensors(fallow, 'PROBE-E', silent=('oxygen', 'temperature', 'salinity', 'ph'))
        row = self.water_row(fallow)
        self.assertNotEqual(row['water'].status, 'critical')
        self.assertEqual((row['water'].silent_oxygen, row['water'].why_silent), (None, []))
        self.assertEqual(read.cards([fallow], self.reader, Choice(view=builtin.SMALL), occupancy=read.ALL)[0].state.key,
                         'empty')
        self.assertEqual(self.alarms(), [])
        self.assertFalse(Alarm.objects.filter(source='sensor_rule').exists())     # no warning of its silent pH either

    def test_a_silent_ph_probe_stays_a_warning_and_leaves_the_card_as_it_was(self):
        """The other parameters keep their rule: a silent pH probe of a unit with fish is a warning; the card is not
        red for it."""
        made = self.sensors(self.t2, 'PROBE-T', silent=('ph',))
        self.typed(self.t1, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        self.assertNotEqual(self.card(self.t2).state.key, 'critical')
        self.assertEqual(self.alarms(), [])
        self.assertEqual(list(Alarm.objects.filter(clearance__isnull=True, sensor_event__channel_no=made['ph'].channel_no)
                              .values_list('severity', flat=True)), ['warning'])


class TypedOxygenTests(SilentOxygenCase):
    def test_a_typed_oxygen_sample_grown_old_with_fish_is_red_and_a_critical_alarm(self):
        """T-01 has no probe: its oxygen is typed, the last 30 hours ago (past its freshness), its temperature fresh."""
        self.typed(self.t1, 30, oxygen_mg_l='9.0')
        self.typed(self.t1, 1, temperature_c='12.0')
        self.typed(self.t2, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        self.assert_red(self.t1, f'{SILENT}, 1')
        found = self.alarms()
        self.assertEqual([(source, severity, parameter) for source, severity, parameter, _summary in found],
                         [('system', 'critical', parameters.OXYGEN_MG_L)])
        self.assertTrue(found[0][3].startswith(f'T-01: {SILENT}, 1'), found[0][3])
        # A fresh oxygen sample ends it, "restored", after the critical's off-delay.
        self.typed(self.t1, 0, oxygen_mg_l='9.0')
        self.assertEqual(self.alarms(self.now + timedelta(seconds=1), self.now + timedelta(minutes=10)), [])
        self.assertEqual(Alarm.objects.get(parameter=parameters.OXYGEN_MG_L).clearance.cause, 'restored')

    def test_a_unit_without_sensors_and_no_oxygen_at_all_with_fish_is_red_and_a_critical_alarm(self):
        self.typed(self.t1, 1, temperature_c='12.0')
        self.typed(self.t2, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        self.assert_red(self.t1, SILENT)
        found = self.alarms()
        self.assertEqual([(source, severity, summary) for source, severity, _parameter, summary in found],
                         [('system', 'critical', f'T-01: {SILENT}')])

    def test_the_words_in_norwegian_and_turkish(self):
        self.typed(self.t1, 1, temperature_c='12.0')
        for language, words in (('nb', 'ingen ferske data'), ('tr', 'güncel veri yok')):
            with self.subTest(language=language), translation.override(language):
                label = str(parameters.get(parameters.OXYGEN_MG_L).label)
                self.assertIn(f'{label}: {words}', self.card(self.t1).state.reasons)


class ReviewTwoTests(SilentOxygenCase):
    """Review 2 of the branch (2026-11-23), the coordinator's calls on the owner's intent."""

    def test_a_unit_harvested_this_morning_is_not_red_and_raises_no_alarm(self):
        """R1: "holds fish" is now, after the day's operations: T-02 emptied today, its probes off, is neither red nor
        an alarm (it was, until midnight, as fish present that day)."""
        self.typed(self.t1, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        self.sensors(self.t2, 'PROBE-T')
        stock_services.record_mortality(self.user, unit=self.t2, batch=self.fish, day=self.today, count=12000,
                                        cause='disease')
        water = self.water_row(self.t2)['water']
        self.assertEqual((water.holds_fish, water.silent_oxygen), (False, None))
        self.assertNotEqual(water.status, 'critical')
        self.assertEqual(self.alarms(), [])

    def test_a_unit_with_fish_and_no_sampling_point_is_red_and_one_critical_alarm(self):
        """R2: no point to read its water at, so its oxygen has no fresh value: critical on the card, the water page and
        as the alarm system's critical, never beside the "no active sampling point" warning."""
        self.typed(self.t1, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        self.typed(self.t2, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        bare = make_unit('N-01', self.hall)
        stock_fish(self.user, bare, 500, '50', 10, species=self.salmon)
        self.assertFalse(SamplingPoint.objects.filter(unit=bare).exists())
        card = self.card(bare)
        self.assertEqual((card.state.key, card.state.reasons), ('critical', (SILENT,)))
        row = next(row for row in self.client.get(reverse('farm:water')).context['rows'] if row['owner'].pk == bare.pk)
        self.assertEqual((row['point'], row['water'].status, row['water'].why_silent), (None, 'critical', [SILENT]))
        self.assertEqual(self.alarms(), [('system', 'critical', parameters.OXYGEN_MG_L, f'N-01: {SILENT}')])
        self.assertFalse(Alarm.objects.filter(parameter='no_water_point').exists())

    def test_a_silent_probe_beside_a_fresh_typed_oxygen_is_a_warning_and_critical_again_once_that_is_old(self):
        """R3 p3: the card follows the fresh typed value (not red); the probe's silence is a warning while that value is
        fresh, the default rule's critical once it is not (and the warning ends)."""
        self.typed(self.t1, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        made = self.sensors(self.t2, 'PROBE-T')
        self.typed(self.t2, 1, oxygen_mg_l='8.5')
        self.assertNotEqual(self.card(self.t2).state.key, 'critical')
        found = self.alarms(self.now, self.now + timedelta(seconds=31))          # past the warning's on-delay
        self.assertEqual([(source, severity, parameter) for source, severity, parameter, _summary in found],
                         [('system', 'warning', PROBE_SILENT)])
        self.assertTrue(found[0][3].startswith('PROBE-T › O2: T-02 › '), found[0][3])
        self.assertTrue(found[0][3].endswith(': the oxygen probe is silent; the oxygen is measured otherwise (by hand or '
                                             'by another probe).'), found[0][3])
        later = self.now + timedelta(hours=25)                     # the typed oxygen is old: nothing else is fresh
        found = [each for each in self.alarms(later, later + timedelta(minutes=10)) if 'T-01' not in each[3]]
        self.assertEqual([(source, severity) for source, severity, _parameter, _summary in found],
                         [('sensor_rule', 'critical')])
        self.assertEqual(Alarm.objects.get(parameter=PROBE_SILENT).clearance.cause, 'restored')
        self.assertTrue(AlarmEvent.objects.filter(channel_no=made['oxygen'].channel_no, closed_at__isnull=True).exists())

    def test_an_old_oxygen_past_its_limit_is_its_levels_alone(self):
        """R4 p5: a typed oxygen past its critical limit, grown old, keeps its levels of the water limits (the critical
        and the warning, main's two levels of one value, the warning not notified while the critical is open); the
        alarm system's oxygen alarm stands aside for them: one problem, not a third alarm."""
        self.typed(self.t1, 30, oxygen_mg_l='5.0')
        self.typed(self.t1, 1, temperature_c='12.0')
        self.typed(self.t2, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        self.assertEqual(self.card(self.t1).state.key, 'critical')
        found = self.alarms()
        self.assertEqual([(source, severity) for source, severity, _parameter, _summary in found],
                         [('water_limit', 'critical'), ('water_limit', 'warning')])

    def test_the_drawer_and_the_water_at_a_past_moment_say_it(self):
        """R6: Production units' drawer and the water read at a past moment (the replay's `latest(at=...)`)."""
        self.typed(self.t1, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        self.sensors(self.t2, 'PROBE-T')
        drawer = self.client.get(reverse('farm:production_units'), {'unit': self.t2.pk}).context
        self.assertEqual(drawer['water_point'].status, 'critical')
        self.assertTrue(drawer['water_point'].why_silent[0].startswith(f'{SILENT}, 1'))
        point = point_of(self.t2)
        silent = water_read.latest([point], at=self.now - timedelta(minutes=30))[point.pk]
        self.assertEqual((silent.status, silent.silent_oxygen is not None), ('critical', True))
        fresh = water_read.latest([point], at=self.then + timedelta(minutes=1))[point.pk]
        self.assertIsNone(fresh.silent_oxygen)


class ReviewThreeTests(SilentOxygenCase):
    """Review 3 of the branch (2026-11-23)."""

    def test_an_old_oxygen_past_its_warning_limit_only_is_a_warning_level_beside_the_critical(self):
        """N1: a typed oxygen of 6.5 mg/L (critical below 6, warning below 7), 30 hours old: its warning level of the water
        limits, and the alarm system's critical that the oxygen has no fresh value: a critical card is never only a
        warning alarm. (Past its critical limit the critical level says it alone: ReviewTwoTests.)"""
        self.typed(self.t1, 30, oxygen_mg_l='6.5')
        self.typed(self.t1, 1, temperature_c='12.0')
        self.typed(self.t2, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        self.assertEqual(self.card(self.t1).state.key, 'critical')
        found = self.alarms(self.now, self.now + timedelta(seconds=31))       # past the warning's on-delay
        self.assertEqual([(source, severity) for source, severity, _parameter, _summary in found],
                         [('system', 'critical'), ('water_limit', 'warning')])

    def test_a_silent_probe_at_an_inlet_is_a_warning_while_the_units_typed_oxygen_is_fresh(self):
        """N2: an oxygen probe at T-02's inlet (no unit reads that point's water as its own), silent, while T-02's typed
        oxygen is fresh: its default rule leaves it to the alarm system's warning, which says the probe and its place."""
        self.typed(self.t1, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        self.typed(self.t2, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        device = make_device(self.connection, self.format, self.bergen, code='PROBE-I')
        probe = make_channel(device, 'oxygen_mg_l', code='O2')
        bindings.move(self.user, probe, point=point_of(self.t2, 'inlet'), at=self.now - timedelta(hours=2))
        self.send(probe, OXYGEN, self.then)
        found = self.alarms(self.now, self.now + timedelta(seconds=31))
        self.assertEqual([(source, severity, parameter) for source, severity, parameter, _summary in found],
                         [('system', 'warning', PROBE_SILENT)])
        self.assertTrue(found[0][3].startswith('PROBE-I › O2: T-02 › '), found[0][3])
        self.assertFalse(AlarmEvent.objects.filter(channel_no=probe.channel_no, closed_at__isnull=True).exists())


class LoopAndPassTests(SilentOxygenCase):
    """After review 3 (the coordinator's calls of 2026-11-23): a unit with no point of its own reads its system's oxygen as
    the water read resolves a loop's water for any unit (A9's second tier); one pass reads where the oxygen is known
    once, for the sensor rules and the alarm system alike."""

    def test_a_unit_without_a_point_in_a_loop_that_measures_its_oxygen_is_not_critical(self):
        self.typed(self.t1, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        self.typed(self.t2, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        for code, measured in (('R8', 'loop sample'), ('R9', 'system probe')):
            with self.subTest(measured=measured):
                ras = System.objects.create(name=f'RAS {code}', code=code, site=self.bergen,
                                            production_department=self.hall)
                unit = make_unit(f'N-{code}', self.hall, system=ras)
                stock_fish(self.user, unit, 500, '50', 10, species=self.salmon)
                self.assertFalse(SamplingPoint.objects.filter(unit=unit).exists())
                if measured == 'loop sample':
                    self.typed(ras, 1, oxygen_mg_l='9.0')                         # the loop point's typed oxygen
                else:
                    device = make_device(self.connection, self.format, self.bergen, code=f'PROBE-{code}')
                    probe = make_channel(device, 'oxygen_mg_l', code='O2')
                    bindings.move(self.user, probe, system=ras, at=self.now - timedelta(hours=2))
                    self.send(probe, OXYGEN, self.now - timedelta(seconds=30))
                water = water_read.unit_water([unit], self.now)[unit.pk]
                self.assertEqual((water.point, water.holds_fish, water.silent_oxygen), (None, True, None))
                self.assertNotEqual(self.card(unit).state.key, 'critical')
        self.assertEqual(self.alarms(), [])
        # Two hours on, the system's probe is old: its default rule's critical says it, the unit's alone never twice.
        later = self.now + timedelta(hours=2)
        self.typed(self.t1, 0, oxygen_mg_l='9.0')
        self.typed(self.t2, 0, oxygen_mg_l='9.0')
        unit = Tank.objects.get(code='N-R9')
        self.assertIsNotNone(water_read.unit_water([unit], later)[unit.pk].silent_oxygen)
        found = [each for each in self.alarms(later) if 'R9' in each[3]]
        self.assertEqual([(source, severity) for source, severity, _parameter, _summary in found],
                         [('sensor_rule', 'critical')])

    def test_one_pass_reads_where_the_oxygen_is_known_once(self):
        """N3: two silent probes, in mg/L and in %, each its default rule, at T-02 whose typed oxygen is fresh: the pass
        asks where the oxygen is known once (it asked once per oxygen rule and again for the warnings), and each
        probe is its warning."""
        self.typed(self.t1, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        self.typed(self.t2, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        device = make_device(self.connection, self.format, self.bergen, code='PROBE-T')
        for quantity, code, value in (('oxygen_mg_l', 'O2', OXYGEN), ('oxygen_saturation_pct', 'O2-PCT', 95.0)):
            probe = make_channel(device, quantity, code=code)
            bindings.move(self.user, probe, point=point_of(self.t2), at=self.now - timedelta(hours=2))
            self.send(probe, value, self.then)
        with mock.patch.object(water_read, 'oxygen_known', wraps=water_read.oxygen_known) as known:
            self.assertEqual(engine.run_once(self.now).failed_steps, [])
            self.assertEqual(engine.run_once(self.now + timedelta(seconds=31)).failed_steps, [])
        self.assertEqual(known.call_count, 2)                                   # once per pass, two passes
        self.assertEqual(sorted(Alarm.objects.filter(clearance__isnull=True).values_list('source', 'severity',
                                                                                         'parameter')),
                         [('system', 'warning', PROBE_SILENT)] * 2)


class ProbeCostTests(SilentOxygenCase):
    """Review 4 of the branch (L2): the warnings of the silent oxygen probes cost the same queries whatever their number;
    where each one is (its site and department) is read with the probes, once per pass, and only for a warning that
    holds."""

    def probes(self, count, code):
        device = make_device(self.connection, self.format, self.bergen, code=code)
        for number in range(count):
            probe = make_channel(device, 'oxygen_mg_l', code=f'O2-{number}')
            bindings.move(self.user, probe, point=point_of(self.t2), at=self.now - timedelta(hours=2))
            self.send(probe, OXYGEN, self.then)

    def queries(self, at):
        with CaptureQueriesContext(connection) as found:
            self.assertEqual(engine.run_once(at).failed_steps, [])
        return len(found)

    def test_a_pass_costs_the_same_for_three_silent_probes_and_for_thirty(self):
        self.typed(self.t1, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        self.typed(self.t2, 1, oxygen_mg_l='9.0', temperature_c='12.0')        # the oxygen known: each a warning
        self.probes(3, 'PROBE-A')
        engine.run_once(self.now - timedelta(seconds=2))
        few = self.queries(self.now - timedelta(seconds=1))
        self.probes(27, 'PROBE-B')
        engine.run_once(self.now)
        self.assertEqual(self.queries(self.now + timedelta(seconds=1)), few)
        engine.run_once(self.now + timedelta(seconds=40))                        # past the warning's on-delay
        self.assertEqual(Alarm.objects.filter(clearance__isnull=True, parameter=PROBE_SILENT).count(), 30)
        self.assertEqual({(alarm.site, alarm.production_department) for alarm in Alarm.objects.filter(
            parameter=PROBE_SILENT)}, {(self.bergen, self.hall)})
