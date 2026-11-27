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
from pathlib import Path
from unittest import mock

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import translation

from alarms import engine
from alarms.models import Alarm
from alarms.tests import farm_alarms
from core.island_props import props_of
from core.pagesays import unsaid
from core.testing import one_moment
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
MANIFEST = str(Path(__file__).resolve().parents[2] / 'core' / 'testdata' / 'islands-prodrest-manifest.json')


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


class WeakerRuleTests(SilentOxygenCase):
    """Review 6, M1: the alarm system's critical stands aside for a probe only where a rule that raises a CRITICAL at the
    freshness covers it (sensors.alarms.watched): a farm's own warning or delayed rule, or the default lowered to a
    warning, would leave a red card with only a warning, or nothing for an hour."""

    def setUp(self):
        super().setUp()
        self.typed(self.t1, 1, oxygen_mg_l='9.0', temperature_c='12.0')     # T-01 is measured: only T-02 is silent

    def kinds(self):
        return sorted((source, severity) for source, severity, _parameter, _summary in self.alarms())

    def test_a_farms_own_warning_rule_an_hour_late_leaves_the_critical_to_the_alarm_system(self):
        from sensors.models import AlarmRule
        AlarmRule.objects.create(quantity='oxygen_mg_l', kind='no_data', for_s=3600, severity='warning')
        self.sensors(self.t2, 'PROBE-T')
        self.assertEqual(self.card(self.t2).state.key, 'critical')
        self.assertEqual(self.kinds(), [('system', 'critical')])        # the default stands aside, the farm's waits

    def test_the_default_rule_lowered_to_a_warning_leaves_the_critical_to_the_alarm_system(self):
        from sensors.models import AlarmRule
        AlarmRule.objects.filter(quantity='oxygen_mg_l', is_default=True).update(severity='warning')
        self.sensors(self.t2, 'PROBE-T')
        self.assertEqual(self.kinds(), [('sensor_rule', 'warning'), ('system', 'critical')])

    def test_a_farms_own_critical_rule_at_the_freshness_is_the_one_alarm(self):
        from sensors.models import AlarmRule
        AlarmRule.objects.create(quantity='oxygen_mg_l', kind='no_data', for_s=0, severity='critical')
        self.sensors(self.t2, 'PROBE-T')
        self.assertEqual(self.kinds(), [('sensor_rule', 'critical')])

    def test_an_oxygen_channel_only_a_weaker_rule_covers_is_not_listed_as_uncovered(self):
        """sensors.alarms.uncovered and the check sensors.W001 still leave the oxygen out: whatever rule covers its probe,
        a unit with fish whose oxygen has no fresh value is the alarm system's critical where no critical rule at the
        freshness says it."""
        from sensors import alarms as sensor_alarms
        from sensors.models import AlarmRule
        AlarmRule.objects.filter(quantity='oxygen_mg_l', is_default=True).update(severity='warning')
        self.sensors(self.t2, 'PROBE-T')
        self.assertEqual([channel for channel in sensor_alarms.uncovered() if channel.quantity == 'oxygen_mg_l'], [])
        self.assertEqual(sensor_alarms.watched(('oxygen_mg_l',), self.now), set())


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
        self.assertEqual(sorted(farm_alarms().filter(clearance__isnull=True).values_list('source', 'severity',
                                                                                         'parameter')),
                         [('system', 'warning', PROBE_SILENT)] * 2)


class ProbeCostTests(SilentOxygenCase):
    """Review 4 of the branch (L2): the warnings of the silent oxygen probes cost the same queries whatever their number;
    where each one is (its site and department) is read with the probes, once per pass, and only for a warning that
    holds."""

    def probes(self, count, code):
        device = make_device(self.connection, self.format, self.bergen, code=code)
        for number in range(count):                     # each at an outlet of T-02 of its own (one primary a place)
            outlet = SamplingPoint.objects.create(unit=self.t2, name=f'{code} outlet {number}', kind='side_outlet')
            probe = make_channel(device, 'oxygen_mg_l', code=f'O2-{number}')
            bindings.move(self.user, probe, point=outlet, at=self.now - timedelta(hours=2))
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


class StandingWaterTests(SilentOxygenCase):
    """A unit with no point of its own has its water from its system (A9's second tier) as a first-class result of the
    water read (farm.water.read.latest, `units`): the loop point's samples and probes, or the system's probes, judged
    for the unit's own fish and marked as its system's; the card, the status, the pages and the alarms read it there
    (review 4 of the branch, L1)."""

    NOTE = {'en': 'From its system, {place}: the unit has no sampling point of its own.',
            'nb': 'Fra systemet, {place}: enheten har ikke noe eget prøvepunkt.',
            'tr': 'Sisteminden, {place}: birimin kendi numune noktası yok.'}

    def setUp(self):
        super().setUp()
        self.typed(self.t1, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        self.typed(self.t2, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        self.ras = System.objects.create(name='RAS 5', code='R5', site=self.bergen, production_department=self.hall)
        self.loop = point_of(self.ras)
        self.unit = make_unit('N-05', self.hall, system=self.ras)
        stock_fish(self.user, self.unit, 500, '50', 10, species=self.salmon)

    def test_its_card_says_the_loops_water_judged_for_its_fish_and_marked_as_its_systems(self):
        self.typed(self.ras, 1, temperature_c='12.0', oxygen_mg_l='9.0')
        self.assertFalse(SamplingPoint.objects.filter(unit=self.unit).exists())
        for language in ('en', 'nb', 'tr'):
            with self.subTest(language=language), translation.override(language):
                card = self.card(self.unit)
                self.assertNotIn(card.state.key, ('critical', 'warning', 'blind'))
                oxygen, temperature = (card.middle_water.get(code) for code in ('oxygen_mg_l', 'temperature_c'))
                self.assertEqual((oxygen.value, oxygen.status, temperature.value, temperature.status),
                                 (D('9.00'), 'ok', D('12.0'), 'ok'))
                self.assertIn(self.NOTE[language].format(place=self.loop), oxygen.note)
        small = self.screens(self.unit)['small']
        self.assertEqual(small.attrs['data-state'], self.card(self.unit).state.key)
        self.assertIn('9.00', text(small))
        self.assertEqual(self.alarms(), [])
        self.assertFalse(Alarm.objects.filter(parameter='no_water_point').exists())

    def test_a_warning_oxygen_in_its_loop_is_its_warning(self):
        self.typed(self.ras, 1, temperature_c='12.0', oxygen_mg_l='6.5')
        water = water_read.unit_water([self.unit], self.now)[self.unit.pk]
        self.assertEqual((water.status, water.get('oxygen_mg_l').judged), ('warning', 'warning'))
        self.assertEqual(self.card(self.unit).state.key, 'warning')
        found = self.alarms(self.now, self.now + timedelta(seconds=31))
        self.assertEqual([(source, severity, parameter) for source, severity, parameter, _summary in found],
                         [('water_limit', 'warning', parameters.OXYGEN_MG_L)])
        self.assertTrue(found[0][3].startswith('N-05, from R5 · '), found[0][3])

    def test_a_stale_loop_says_no_recent_data_and_the_one_critical_is_its_probes(self):
        device = make_device(self.connection, self.format, self.bergen, code='PROBE-5')
        probe = make_channel(device, 'oxygen_mg_l', code='O2')
        bindings.move(self.user, probe, system=self.ras, at=self.now - timedelta(hours=2))
        self.send(probe, OXYGEN, self.then)
        card = self.card(self.unit)
        self.assertEqual(card.state.key, 'critical')
        self.assertTrue(card.state.reasons[0].startswith(f'{SILENT}, 1'), card.state.reasons)
        self.assertEqual(card.middle_water.get('oxygen_mg_l').status, 'stale')
        found = [each for each in self.alarms() if 'N-05' in each[3] or 'R5' in each[3]]
        self.assertEqual([(source, severity) for source, severity, _parameter, _summary in found],
                         [('sensor_rule', 'critical')])

    def test_a_pass_costs_the_same_for_two_such_units_and_for_six(self):
        self.typed(self.ras, 1, temperature_c='12.0', oxygen_mg_l='9.0')

        def more(count, prefix):
            for number in range(count):
                stock_fish(self.user, make_unit(f'{prefix}-{number}', self.hall, system=self.ras), 100, '50', 10,
                           species=self.salmon)

        def queries(at):
            with CaptureQueriesContext(connection) as found:
                self.assertEqual(engine.run_once(at).failed_steps, [])
            return len(found)
        more(1, 'NA')
        engine.run_once(self.now - timedelta(seconds=2))
        few = queries(self.now - timedelta(seconds=1))
        more(4, 'NB')
        engine.run_once(self.now)
        self.assertEqual(queries(self.now + timedelta(seconds=1)), few)


class CardHasItsAlarmTests(SilentOxygenCase):
    """Review 5 of the branch (M1): a card at critical or at warning has its alarm at that level, whatever way a unit with
    no point of its own is read (its loop point, its system's probes with no loop point, nothing). Its water's levels are
    raised through the one path (alarms/sources.py `_water_subjects`): at the loop point, or, with none, without a point,
    on the unit's site and department."""

    def setUp(self):
        super().setUp()
        self.typed(self.t1, 1, oxygen_mg_l='9.0', temperature_c='12.0')
        self.typed(self.t2, 1, oxygen_mg_l='9.0', temperature_c='12.0')

    def bare(self, code, loop=False, system=True):
        """A unit with fish and no point of its own (N-<code>), in a system of its own (with a loop point when `loop`)."""
        ras = System.objects.create(name=f'RAS {code}', code=code, site=self.bergen,
                                    production_department=self.hall) if system else None
        if loop:
            point_of(ras)
        unit = make_unit(f'N-{code}', self.hall, system=ras)
        stock_fish(self.user, unit, 500, '50', 10, species=self.salmon)
        return unit, ras

    def probe(self, ras, code, value, at):
        device = make_device(self.connection, self.format, self.bergen, code=f'P-{code}')
        probe = make_channel(device, 'oxygen_mg_l', code='O2')
        bindings.move(self.user, probe, system=ras, at=self.now - timedelta(hours=2))
        self.send(probe, value, at)
        return probe

    def levels(self, unit, code):
        """The highest level of the open alarms about the unit (its own, its system's probe's), 'none' without one."""
        found = {alarm.severity for alarm in Alarm.objects.filter(clearance__isnull=True)
                 if alarm.summary.startswith(f'{unit.code}') or f'P-{code}' in alarm.summary}
        return 'critical' if 'critical' in found else 'warning' if 'warning' in found else 'none'

    def passes(self):
        for at in (self.now, self.now + timedelta(seconds=31)):
            self.assertEqual(engine.run_once(at).failed_steps, [])

    def test_a_low_oxygen_from_the_systems_probe_without_a_loop_point_is_one_critical(self):
        """q1: 3.0 mg/L from the system's probe, no loop point: a red card, and its critical (and its warning twin)."""
        unit, ras = self.bare('Q1')
        self.probe(ras, 'Q1', 3.0, self.now - timedelta(seconds=30))
        self.assertEqual(self.card(unit).state.key, 'critical')
        self.passes()
        found = sorted((alarm.source, alarm.severity, alarm.point_id) for alarm in Alarm.objects.filter(
            clearance__isnull=True, summary__startswith='N-Q1'))
        self.assertEqual(found, [('water_limit', 'critical', None), ('water_limit', 'warning', None)])
        alarm = Alarm.objects.get(clearance__isnull=True, summary__startswith='N-Q1', severity='critical')
        self.assertEqual((alarm.site, alarm.production_department), (self.bergen, self.hall))
        self.assertTrue(alarm.summary.startswith('N-Q1, from its system: '), alarm.summary)
        self.assertFalse(Alarm.objects.filter(parameter='no_water_point').exists())

    def test_a_warning_oxygen_from_the_systems_probe_without_a_loop_point_is_one_warning(self):
        """q2: 6.5 mg/L: a warning card and its warning."""
        unit, ras = self.bare('Q2')
        self.probe(ras, 'Q2', 6.5, self.now - timedelta(seconds=30))
        self.assertEqual(self.card(unit).state.key, 'warning')
        self.passes()
        self.assertEqual(sorted((alarm.source, alarm.severity) for alarm in Alarm.objects.filter(
            clearance__isnull=True, summary__startswith='N-Q2')), [('water_limit', 'warning')])
        self.assertFalse(Alarm.objects.filter(parameter='no_water_point').exists())

    def test_every_unit_without_a_point_has_the_alarm_its_card_says(self):
        """The card's state is the highest level of its open alarms (critical, warning, else none), for every way a unit
        with no point of its own is read."""
        fresh, stale = self.now - timedelta(seconds=30), self.now - timedelta(hours=30)
        cases = {}
        unit, ras = self.bare('C1', loop=True)                          # loop point, fresh OK
        self.typed(ras, 1, temperature_c='12.0', oxygen_mg_l='9.0')
        cases['C1'] = unit
        unit, ras = self.bare('C2', loop=True)                          # loop point, fresh low
        self.typed(ras, 1, temperature_c='12.0', oxygen_mg_l='3.0')
        cases['C2'] = unit
        unit, ras = self.bare('C3', loop=True)                          # loop point, typed warning-band, old
        self.typed(ras, 30, oxygen_mg_l='6.5')
        cases['C3'] = unit
        unit, ras = self.bare('C4', loop=True)                          # loop point, a silent system probe
        self.probe(ras, 'C4', OXYGEN, stale)
        cases['C4'] = unit
        unit, ras = self.bare('C5')                                     # no loop point, no probe
        cases['C5'] = unit
        cases['C6'], _none = self.bare('C6', system=False)              # no system at all
        unit, ras = self.bare('C7')                                     # no loop point, probe low
        self.probe(ras, 'C7', 3.0, fresh)
        cases['C7'] = unit
        unit, ras = self.bare('C8')                                     # no loop point, probe warning-band
        self.probe(ras, 'C8', 6.5, fresh)
        cases['C8'] = unit
        unit, ras = self.bare('C9')                                     # no loop point, probe fine
        self.probe(ras, 'C9', OXYGEN, fresh)
        cases['C9'] = unit
        states = {code: self.card(unit).state.key for code, unit in cases.items()}
        self.passes()
        for code, unit in cases.items():
            with self.subTest(code=code, card=states[code]):
                card = states[code] if states[code] in ('critical', 'warning') else 'none'
                self.assertEqual(self.levels(unit, code), card)
        self.assertFalse(Alarm.objects.filter(clearance__isnull=True, parameter='no_water_point').exists())

    def test_the_overview_lists_the_critical_unit_without_a_point_it_counts(self):
        """q6: a unit with fish, no point and no system, its oxygen unknown: counted critical and listed."""
        unit, _none = self.bare('Q6', system=False)
        water = self.overview()
        self.assertIn(unit.pk, {row['owner'].pk for row in water['alerts']})

    @override_settings(ISLANDS_MANIFEST=MANIFEST)
    def test_the_new_look_overview_lists_it_and_says_why_as_the_classic_one_does(self):
        """The new look's Production › Overview (config/production_props.py) lists that unit too, without a point, on its
        department and site, saying why it is critical, and says all the classic page says (core.pagesays)."""
        from farm.tests.test_production_overview_next import as_next, figures, said_another_way
        unit, _none = self.bare('Q6', system=False)
        with one_moment():                    # both looks say the same time ("Stock records at 21:59")
            old = as_next(self.client.get(reverse('production_home'), {'ui': 'classic'}).content.decode())
            new = self.client.get(reverse('production_home'), {'ui': 'next'}).content.decode()
        props = props_of(new, 'production')
        self.assertEqual(unsaid(old, props, new_html=new, ignore=said_another_way(old), once=figures(old)), [])
        [row] = [row for row in props['attention']['rows'] if row['title'] == unit.code and row['kind'] == 'water']
        self.assertEqual((row['key'], row['kind'], row['status']), (f'water-unit-{unit.pk}', 'water', 'critical'))
        self.assertTrue(row['sub'].startswith(f'{self.hall.name}, '), row['sub'])
        self.assertIn(SILENT, row['sub'])

    def test_the_drawer_and_the_card_name_the_system_the_values_come_from(self):
        """A unit read at its system: the drawer says "From its system, …" (never "no water is shown"), and the card's
        water table names the place."""
        unit, ras = self.bare('Q9', loop=True)
        self.typed(ras, 1, temperature_c='12.0', oxygen_mg_l='9.0')
        loop = point_of(ras)
        drawer = self.client.get(reverse('farm:production_units'), {'unit': unit.pk}).content.decode()
        self.assertNotIn('so no water is shown for it', drawer)
        self.assertIn(f'From its system, {loop}: the unit has no sampling point of its own.', drawer)
        detailed = self.client.get(PAGE, {'mode': 'detailed', 'units': str(unit.pk), 'full': '1'}).content.decode()
        blocks = [node for node in card_of(detailed, unit).walk() if 'monitor-point' in node.classes]
        names = [text(child) for block in blocks for child in block.children
                 if not isinstance(child, str) and 'row-sub' in child.classes]
        self.assertTrue(names and all(names), names)
        self.assertIn(str(loop), ' '.join(names))

    def test_a_unit_read_at_an_outlet_alone_says_the_same_on_every_page(self):
        """Review 6, M2: a unit with fish whose only point is a side outlet carrying its oxygen probe (no middle point,
        no typed sample): when the probe stops, the Water page, the production overview and the company overview say
        it critical at that outlet, as its card, the strip and the alarms do (one point stands for it: read.anchors)."""
        from config.company_props import overview_props
        unit = make_unit('N-OUT', self.hall)
        stock_fish(self.user, unit, 500, '50', 10, species=self.salmon)
        outlet = SamplingPoint.objects.create(unit=unit, name='Side outlet', kind='side_outlet')
        device = make_device(self.connection, self.format, self.bergen, code='P-OUT')
        probe = make_channel(device, 'oxygen_mg_l', code='O2')
        bindings.move(self.user, probe, point=outlet, at=self.now - timedelta(hours=2))
        self.send(probe, OXYGEN, self.then)                       # then silent
        self.assertEqual(self.card(unit).state.key, 'critical')
        rows = [row for row in self.client.get(reverse('farm:water')).context['rows'] if row['owner'].pk == unit.pk]
        self.assertEqual([row['point'] for row in rows], [outlet])
        self.assertEqual(rows[0]['water'].status, 'critical')
        self.assertTrue(rows[0]['water'].why_silent)
        with self.settings(ISLANDS_MANIFEST=MANIFEST):      # the new look's Water page says why too (review 6, m1)
            props = props_of(self.client.get(reverse('farm:water'), {'ui': 'next'}).content.decode(), 'list-page')
        [said] = [row for row in props['table']['rows'] if row['cells']['point']['text'] == unit.code]
        self.assertEqual(said['cells']['status']['chip']['kind'], 'critical')
        self.assertTrue(any(line.startswith(SILENT) for line in said['cells']['status']['sub']), said['cells']['status'])
        self.assertIn(unit.pk, {row['owner'].pk for row in self.overview()['alerts']})
        from django.contrib.auth import get_user_model
        boss = get_user_model().objects.create_superuser('test.boss', 'test.boss@example.com', 'x')
        chips = {row['code']: row['water'] for row in overview_props(boss)['sites']['rows']}
        self.assertEqual(chips[self.bergen.code]['kind'], 'critical')
        self.assertEqual([found[:2] for found in self.alarms()], [('sensor_rule', 'critical')])
