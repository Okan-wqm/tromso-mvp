"""A probe that stops sending, on every page that says how fresh a water value is (owner decision of 2026-11-20; the second
review of the water-chemistry audit, question 3): one behaviour for every pH scale, and its silence is said by its
default "No fresh value" rule, critical for the dissolved oxygen and a warning for every other quantity.

A pH probe calibrated with TRIS (the total scale) that stopped after a critically low value keeps that value, put on
the NBS scale at its own moment, as the last word on the water: the Small and Big cards, the wall, the pane, the band's
chip, the water page's table, Production units and the production overview say "Critical, no recent data" exactly as
for the same water from a probe on NBS, and never "cannot be evaluated" (what they said before the decision, a warning
that hid the critical). The probe's silence is an alarm of its own, and a silent oxygen probe a critical one, named with
its channel and its place on Company › Alarms.

Real sensor channels (the sensors app's provider, not a stand-in), the real pages and the real alarm engine: T-01 and
T-02 of the worked example made sea tanks, each with its own probes."""
from datetime import timedelta

from django.db import connection
from django.urls import reverse
from django.utils import timezone

from alarms import engine
from alarms.models import Alarm
from farm.models import Tank
from farm.templatetags.water import water_value
from farm.tests.helpers import point_of
from farm.water import read as water_read
from sensors import bindings
from sensors.models import ChannelState
from sensors.tests import make_channel, make_connection, make_device, make_format

from .. import read
from ..cards import builtin
from ..cards.resolve import Choice
from . import MonitoringCase
from .test_band import band_of
from .test_small import card_of, text

PAGE, PANE = reverse('monitoring:monitor'), reverse('monitoring:pane')
TOTAL = 'total'
# What the stopped probe last sent, on the total scale, and the water of that moment: 6.00 is 6.11 on the NBS scale at
# 12 °C and S 34 (formula 4), below the salmon's critical 6.20.
LOW, TEMPERATURE, SALINITY, OXYGEN = 6.00, 12.0, 34.0, 9.0
CRITICAL_OLD = 'pH (NBS scale): Critical, no recent data'
REFUSED = 'cannot be evaluated'


class StoppedProbeCase(MonitoringCase):
    """T-01 and T-02 sea tanks of salmon with a pH limit, each middle point fed by probes of its own."""

    def setUp(self):
        super().setUp()
        Tank.objects.filter(pk__in=[self.t1.pk, self.t2.pk]).update(water_type='saltwater', water_origin='seawater')
        self.t1.refresh_from_db()
        self.t2.refresh_from_db()
        self.limit('ph', critical_low='6.20', warning_low='6.50', warning_high='8.50')
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7)
        self.limit('temperature_c', warning_high=15, critical_high=18)
        self.now = timezone.now()
        self.then = self.now - timedelta(hours=1)
        self.connection, self.format = make_connection(), make_format()
        # The value the same water gives on the NBS scale (the one conversion, farm.water.read.ph_on_nbs).
        self.nbs_low = water_read.ph_on_nbs(LOW, TOTAL, TEMPERATURE, SALINITY, 'seawater').value
        self.assertLess(self.nbs_low, 6.20)

    def send(self, channel, value, at):
        """The channel's value at `at`, as the ingest leaves it: its state and its reading."""
        ChannelState.objects.update_or_create(channel_no=channel.channel_no, defaults=dict(
            last_value=value, last_value_ts=at, last_good_at=at, last_seen_at=at))
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO sensors_reading (channel_no, ts, value) VALUES (%s, %s, %s)',
                           [channel.channel_no, at, value])

    def probes(self, unit, code, ph, scale='', oxygen_goes_on=True):
        """A device on the unit's middle point: a pH probe on `scale` that sent `ph` an hour ago and nothing since, and
        a temperature, a salinity and an oxygen probe that sent then and go on sending (the oxygen probe stops too
        unless `oxygen_goes_on`). Returns {name: channel}."""
        device = make_device(self.connection, self.format, self.bergen, code=code)
        made = {'ph': make_channel(device, 'ph', code='PH', **({'ph_scale': scale} if scale else {})),
                'temperature': make_channel(device, 'temperature_c', code='TEMP'),
                'salinity': make_channel(device, 'salinity_ppt', code='SAL'),
                'oxygen': make_channel(device, 'oxygen_mg_l', code='O2')}
        for channel in made.values():
            bindings.move(self.user, channel, point=point_of(unit), at=self.now - timedelta(hours=2))
        sent = {'ph': ph, 'temperature': TEMPERATURE, 'salinity': SALINITY, 'oxygen': OXYGEN}
        for name, channel in made.items():
            self.send(channel, sent[name], self.then)
        going_on = ['temperature', 'salinity', *(['oxygen'] if oxygen_goes_on else [])]
        for name in going_on:
            self.send(made[name], sent[name], self.now - timedelta(seconds=30))
        return made

    def stopped(self):
        """T-02's pH probe is on the total scale, T-01's on NBS: the same water, each probe silent for an hour."""
        self.probes(self.t2, 'PROBE-T', LOW, TOTAL)
        self.probes(self.t1, 'PROBE-N', float(self.nbs_low))


class CardTests(StoppedProbeCase):
    def test_the_cards_say_the_last_critical_of_a_stopped_tris_probe_as_of_an_nbs_one(self):
        self.stopped()
        found = {card.unit.pk: card for card in read.cards([self.t1, self.t2], self.reader, Choice(view=builtin.SMALL))}
        for unit in (self.t1, self.t2):
            with self.subTest(unit=unit.code):
                state, middle = found[unit.pk].state, found[unit.pk].middle_water
                self.assertEqual((state.key, state.reasons, state.stale), ('critical', (CRITICAL_OLD,), (CRITICAL_OLD,)))
                ph = middle.get('ph')
                self.assertEqual((ph.value, ph.status, ph.judged, ph.old_alert, ph.unevaluated),
                                 (self.nbs_low, 'stale', 'critical', 'critical', False))
                self.assertEqual(middle.why_unevaluated, [])
        self.assertEqual(found[self.t2.pk].middle_water.get('ph').measured, 'measured 6.00 on the total scale')
        figure = water_value(self.nbs_low, 'ph')
        units = f'{self.t1.pk},{self.t2.pk}'
        for name, query in (('small', {'mode': 'small'}), ('big', {'mode': 'big'}),
                            ('wall', {'mode': 'small', 'wall': '1'})):
            html = self.client.get(PAGE, {**query, 'units': units}).content.decode()
            for unit in (self.t1, self.t2):
                with self.subTest(screen=name, unit=unit.code):
                    card = card_of(html, unit)
                    self.assertEqual(card.attrs['data-state'], 'critical')
                    self.assertIn(figure, text(card))
                    self.assertNotIn(REFUSED, text(card).lower())
            with self.subTest(screen=name, part='band'):
                # Past the same bound of the same value, both old: one chip, the stopped TRIS probe's tank beside the
                # NBS one's (review R2), never a "cannot be evaluated" warning of its own.
                strip = next(each for each in band_of(html).walk() if 'monitor-strip' in each.classes)
                chips = [text(each) for each in strip.children if not isinstance(each, str)]
                self.assertEqual(chips, [f'Critical T-01 T-02 pH {figure} < critical limit 6.20, no recent data'])
        # The pane: T-02's Big card beside the overview, gone into from its Small card.
        big = card_of(self.client.get(PANE, {'focus': str(self.t2.pk), 'mode': 'small'}).content.decode(), self.t2)
        self.assertEqual((big.tag, big.attrs['data-state'], big.attrs['data-template']),
                         ('article', 'critical', str(builtin.BIG)))
        self.assertIn(figure, text(big))
        self.assertNotIn(REFUSED, text(big).lower())


class WaterPagesTests(StoppedProbeCase):
    def test_the_water_page_production_units_and_the_overview_count_it_as_the_nbs_probes(self):
        self.stopped()
        rows = {row['owner'].pk: row for row in self.client.get(reverse('farm:water')).context['rows']
                if row['point'] is not None and row['owner'].pk in (self.t1.pk, self.t2.pk)
                and row['point'].kind == water_read.MIDDLE}
        for unit in (self.t1, self.t2):
            with self.subTest(page='water', unit=unit.code):
                water = rows[unit.pk]['water']
                self.assertEqual((water.status, water.old_alert, water.why_unevaluated), ('critical', True, []))
        self.assertFalse('data-unevaluated' in self.client.get(reverse('farm:water')).content.decode(),
                         'a row of the water page says a value cannot be evaluated')
        units = {row['unit'].pk: row for row in self.client.get(reverse('farm:production_units')).context['rows']}
        for unit in (self.t1, self.t2):
            with self.subTest(page='production units', unit=unit.code):
                self.assertEqual((units[unit.pk]['water'].status, units[unit.pk]['water'].old_alert), ('critical', True))
        water = self.client.get(reverse('production_home')).context['water']
        self.assertEqual((water['critical'], water['unevaluated']), (2, []))
        self.assertEqual({row['owner'].pk for row in water['alerts']}, {self.t1.pk, self.t2.pk})


class AlarmTests(StoppedProbeCase):
    def test_a_silent_oxygen_probe_is_a_critical_alarm_a_silent_ph_probe_a_warning_each_naming_its_place(self):
        """Company › Alarms: the stopped probes of T-02 (a pH on the total scale and the oxygen), each named with its
        channel and the place it was bound to; the probes that go on sending raise nothing."""
        made = self.probes(self.t2, 'PROBE-T', 7.95, TOTAL, oxygen_goes_on=False)
        summary = engine.run_once(self.now)
        self.assertEqual(summary.failed_steps, [])
        found = {alarm.sensor_event.channel_no: (alarm.severity, alarm.summary) for alarm in Alarm.objects.filter(
            clearance__isnull=True, source='sensor_rule').select_related('sensor_event')}
        self.assertEqual(set(found), {made['ph'].channel_no, made['oxygen'].channel_no})
        severity, said = found[made['oxygen'].channel_no]
        self.assertEqual(severity, 'critical')
        self.assertTrue(said.startswith('Dissolved oxygen (mg/L O₂): No fresh value · PROBE-T › O2: T-02 › '), said)
        severity, said = found[made['ph'].channel_no]
        self.assertEqual(severity, 'warning')
        self.assertTrue(said.startswith('pH (NBS scale): No fresh value · PROBE-T › PH: T-02 › '), said)
        self.as_person('alarm-reader', 'view_alarm')
        page = self.client.get(reverse('alarms:alarm_list')).content.decode()
        oxygen_row = next(row for row in page.split('<tr>') if 'O2: T-02' in row)
        self.assertIn('badge-critical', oxygen_row)
        ph_row = next(row for row in page.split('<tr>') if 'PH: T-02' in row)
        self.assertNotIn('badge-critical', ph_row)
