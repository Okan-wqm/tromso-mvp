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

from django.urls import reverse
from django.utils import translation

from alarms import engine
from alarms.models import Alarm
from farm.tests.helpers import point_of
from farm.tests.test_stock import make_unit
from farm.water import parameters, services as water_services
from farm.models import Tank
from sensors import bindings
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
            found[name] = card_of(self.client.get(PAGE, {**query, 'units': str(unit.pk)}).content.decode(), unit)
        found['pane'] = card_of(self.client.get(PANE, {'focus': str(unit.pk), 'mode': 'small'}).content.decode(), unit)
        return found

    def chips(self, unit):
        html = self.client.get(PAGE, {'mode': 'small', 'units': str(unit.pk)}).content.decode()
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
            if alarm.parameter in (parameters.OXYGEN_MG_L, parameters.OXYGEN_PCT) or (
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
