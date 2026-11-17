"""Monitoring's reads with sensors (owner amendment A4), the services and plain endpoints the card designer will place:
the Deffeyes inputs of a unit at a past moment in the A1 order with origins and ages relative to that moment (never a
value from after it, a moved sensor counting for the tank it was in then), a system's own Deffeyes, the trail of a unit's
point on the diagram from the hour tier, the channel that feeds each input, and binding a channel from a card's place
through the Move dialog."""
import json
import re
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from farm.models import System
from farm.tests.helpers import point_of, role
from farm.tests.test_stock import make_unit
from farm.water import calculation, chemistry, deffeyes, read as water_read, services as water_services

from sensors import bindings, trail
from sensors.models import Binding

from . import SensorsCase, make_channel

D = Decimal


def insert(channel_no, rows):
    with connection.cursor() as cursor:
        cursor.executemany('INSERT INTO sensors_reading (channel_no, ts, value) VALUES (%s, %s, %s)',
                           [(channel_no, at, value) for at, value in rows])


class HistoryCase(SensorsCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ras = System.objects.create(name='RAS 1', code='R1', site=cls.site, production_department=cls.hall)
        cls.t1 = make_unit('T-01', cls.hall, system=cls.ras)
        cls.t2 = make_unit('T-02', cls.hall, system=cls.ras)
        cls.mid1, cls.mid2, cls.loop = point_of(cls.t1), point_of(cls.t2), point_of(cls.ras)
        cls.now = timezone.now().replace(minute=0, second=0, microsecond=0)
        cls.since = cls.now - timedelta(days=5)
        cls.ph = make_channel(cls.device, 'ph')
        bindings.move(cls.user, cls.ph, point=cls.mid1, at=cls.since)
        bindings.move(cls.user, cls.channel, system=cls.ras, at=cls.since)          # the system's temperature

    def sample(self, point, at, **values):
        return water_services.record(self.user, point=point, measured_at=at, source='manual',
                                     values={code: D(str(value)) for code, value in values.items()})


class PastMomentTests(HistoryCase):
    def test_the_inputs_at_a_past_moment_are_what_each_source_said_then(self):
        moment = self.now - timedelta(hours=6)
        insert(self.ph.channel_no, [(moment - timedelta(minutes=2), 7.31), (moment + timedelta(minutes=5), 6.0)])
        insert(self.channel.channel_no, [(moment - timedelta(seconds=40), 9.46)])
        self.sample(self.mid1, moment - timedelta(days=1), alkalinity_mg_l='90', salinity_ppt='0', ph='6.5')
        self.sample(self.mid1, moment + timedelta(hours=1), alkalinity_mg_l='200')               # after: not seen
        water = water_read.latest([self.mid1], at=moment)[self.mid1.pk]
        ph, temperature, alkalinity = (water.get(code) for code in ('ph', 'temperature_c', 'alkalinity_mg_l'))
        self.assertEqual((ph.value, ph.origin, ph.at), (D('7.31'), water_read.Origin.SENSOR, moment - timedelta(minutes=2)))
        self.assertEqual((temperature.value, temperature.origin), (D('9.5'), water_read.Origin.SYSTEM_SENSOR))
        self.assertEqual((alkalinity.value, alkalinity.origin), (D('90'), water_read.Origin.MANUAL))
        self.assertTrue(ph.fresh(moment))
        chart = calculation.chart_of(self.t1, at=moment)
        inputs = {item.field: item.value for item in chart.inputs}
        self.assertEqual((inputs['ph'], inputs['temperature_c'], inputs['alkalinity_mg_l']), (D('7.31'), D('9.5'), D('90')))
        self.assertEqual(chart.now, moment)

    def test_a_stale_sensor_at_the_moment_gives_way_to_the_sample_of_then(self):
        moment = self.now - timedelta(hours=6)
        insert(self.ph.channel_no, [(moment - timedelta(hours=2), 7.3)])                    # fresh for 15 min only
        self.sample(self.mid1, moment - timedelta(hours=3), ph='6.9')
        ph = water_read.latest([self.mid1], at=moment)[self.mid1.pk].get('ph')
        self.assertEqual((ph.value, ph.origin), (D('6.90'), water_read.Origin.MANUAL))

    def test_a_moved_sensor_counts_for_the_tank_it_was_in_then(self):
        moved = self.now - timedelta(days=1)
        bindings.move(self.user, self.ph, point=self.mid2, at=moved)
        insert(self.ph.channel_no, [(moved - timedelta(hours=1, minutes=1), 7.1), (moved + timedelta(hours=1), 7.7)])
        before = moved - timedelta(hours=1)
        self.assertEqual(water_read.latest([self.mid1], at=before)[self.mid1.pk].get('ph').value, D('7.10'))
        self.assertIsNone(water_read.latest([self.mid2], at=before)[self.mid2.pk].get('ph'))
        after = moved + timedelta(hours=1, minutes=1)
        self.assertEqual(water_read.latest([self.mid2], at=after)[self.mid2.pk].get('ph').value, D('7.70'))

    def test_the_window_endpoint_draws_the_moment_asked(self):
        reader = get_user_model().objects.create_user('reader', 'reader@example.com', 'x')
        reader.groups.add(role('Reader', 'view_watermeasurement'))
        self.client.force_login(reader)
        moment = self.now - timedelta(hours=6)
        insert(self.ph.channel_no, [(moment - timedelta(minutes=2), 7.31)])
        insert(self.channel.channel_no, [(moment - timedelta(seconds=40), 9.46)])
        self.sample(self.mid1, moment - timedelta(days=1), alkalinity_mg_l='90', salinity_ppt='0')
        local = timezone.localtime(moment, timezone.get_default_timezone()).strftime('%Y-%m-%dT%H:%M')
        page = self.client.get(reverse('farm:water_unit_chart', args=[self.t1.pk]), {'at': local})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, '7.31')
        self.assertRegex(re.sub(r'<[^>]+>', '', page.content.decode()), r'unit sensor #\d+ · 2\s?minutes ago')
        self.assertEqual(self.client.get(reverse('farm:water_unit_chart', args=[self.t1.pk]),
                                         {'at': 'yesterday'}).status_code, 400)


class SystemChartTests(HistoryCase):
    def test_a_system_has_its_own_deffeyes_from_its_loop_and_its_sensors(self):
        ph = make_channel(self.device, 'ph', code='PH-LOOP')
        bindings.move(self.user, ph, system=self.ras, at=self.since)
        now = timezone.now()
        from sensors.models import ChannelState
        for channel, value in ((ph, 7.4), (self.channel, 9.5)):
            ChannelState.objects.create(channel_no=channel.channel_no, last_value=value, last_value_ts=now,
                                        last_good_at=now)
        self.sample(self.loop, now - timedelta(hours=1), alkalinity_mg_l='80', salinity_ppt='0')
        chart = calculation.chart_of(self.ras, now=now)
        inputs = {item.field: item for item in chart.inputs}
        self.assertEqual(inputs['ph'].value, D('7.40'))
        self.assertEqual(inputs['ph'].reading.origin, water_read.Origin.SYSTEM_SENSOR)
        reader = get_user_model().objects.create_user('reader', 'reader@example.com', 'x')
        reader.groups.add(role('Reader', 'view_watermeasurement'))
        self.client.force_login(reader)
        self.assertContains(self.client.get(reverse('farm:water_system_chart', args=[self.ras.pk])), '7.40')


class TrailTests(HistoryCase):
    def test_the_trail_is_the_units_point_hour_by_hour_from_the_hour_tier(self):
        start = self.now - timedelta(hours=4)
        rows = []
        for hour in range(4):
            for minute in (10, 40):
                rows.append((start + timedelta(hours=hour, minutes=minute), 7.0 + hour * 0.1 + minute / 1000))
        insert(self.ph.channel_no, rows)
        insert(self.channel.channel_no, [(start + timedelta(hours=hour, minutes=5), 10.0) for hour in range(4)])
        self.sample(self.mid1, start - timedelta(days=1), alkalinity_mg_l='100', salinity_ppt='0')
        found = trail.trail(self.t1, start, self.now)
        self.assertEqual(len(found.points), 4)
        for hour, point in enumerate(found.points):
            expected_ph = 7.0 + hour * 0.1 + (0.010 + 0.040) / 2
            self.assertEqual(point.at, start + timedelta(hours=hour))
            self.assertAlmostEqual(point.ph, expected_ph, places=9)
            eq = chemistry.water_equilibria(10.0, 0.0, 100.0)                    # formula 3: the alkalinity's ions
            self.assertAlmostEqual(point.dic, eq.dic(100 / chemistry.MG_CACO3_PER_MEQ, expected_ph), places=9)
        self.assertEqual(found.missing, [])

    def test_an_hour_without_an_input_is_listed_not_guessed(self):
        start = self.now - timedelta(hours=2)
        insert(self.ph.channel_no, [(start + timedelta(minutes=10), 7.2)])
        insert(self.channel.channel_no, [(start + timedelta(minutes=5), 10.0), (start + timedelta(hours=1, minutes=5),
                                                                                10.0)])
        self.sample(self.mid1, start - timedelta(days=1), alkalinity_mg_l='100', salinity_ppt='0')
        found = trail.trail(self.t1, start, self.now)
        self.assertEqual([point.at for point in found.points], [start])
        self.assertEqual(found.missing, [start + timedelta(hours=1)])

    def test_an_hour_whose_ph_and_alkalinity_cannot_go_together_is_listed_never_drawn(self):
        """The core refuses a water below the alkalinity floor of its pH (the correction of 2026-11-10): the trail lists
        that hour as impossible; before, it drew a point with a DIC below 0."""
        start = self.now - timedelta(hours=2)
        insert(self.ph.channel_no, [(start + timedelta(minutes=10), 7.2), (start + timedelta(hours=1, minutes=10), 11.5)])
        insert(self.channel.channel_no, [(start + timedelta(hours=hour, minutes=5), 10.0) for hour in range(2)])
        self.sample(self.mid1, start - timedelta(days=1), alkalinity_mg_l='20', salinity_ppt='0')
        self.assertTrue(deffeyes.why_impossible(10.0, 0.0, 11.5, 20.0))
        found = trail.trail(self.t1, start, self.now)
        self.assertEqual([point.at for point in found.points], [start])
        self.assertEqual(found.impossible, [start + timedelta(hours=1)])
        self.assertEqual(found.missing, [])
        self.assertTrue(all(point.dic > 0 for point in found.points))
        user = get_user_model().objects.create_user('reader', 'reader@example.com', 'x')
        user.groups.add(role('Reader', 'view_watermeasurement'), role('Readings', 'view_reading'))
        self.client.force_login(user)
        response = self.client.get(reverse('sensors:trail'), {'target': f'unit:{self.t1.pk}', 'range': '6h'})
        self.assertEqual(response.status_code, 200)
        answer = json.loads(response.content)
        self.assertEqual(answer['impossible'], [(start + timedelta(hours=1)).isoformat()])
        self.assertEqual(len(answer['points']), 1)

    def test_an_hour_the_core_refuses_is_listed_with_its_reason_never_a_server_error(self):
        """The review's R1: a stored conductivity past the Davies range on a fresh water. The trail lists the hour with
        the core's reason (deffeyes.unworkable, the gate a unit's chart asks); before, the whole trail raised."""
        start = self.now - timedelta(hours=2)
        insert(self.ph.channel_no, [(start + timedelta(hours=hour, minutes=10), 7.2) for hour in range(2)])
        insert(self.channel.channel_no, [(start + timedelta(hours=hour, minutes=5), 12.0) for hour in range(2)])
        self.sample(self.mid1, start - timedelta(days=1), alkalinity_mg_l='80', salinity_ppt='0',
                    conductivity_25_us_cm='40000')
        why = deffeyes.unworkable(12.0, 0.0, 80.0, conductivity_25_us_cm=40000.0)
        self.assertIn('Cannot be worked out: ionic strength above 0.5', why)
        found = trail.trail(self.t1, start, self.now)
        self.assertEqual(found.points, [])
        self.assertEqual(found.missing, [])
        self.assertEqual(found.impossible, [])
        self.assertEqual(found.unworkable, [(start, why), (start + timedelta(hours=1), why)])
        user = get_user_model().objects.create_user('reader', 'reader@example.com', 'x')
        user.groups.add(role('Reader', 'view_watermeasurement'), role('Readings', 'view_reading'))
        self.client.force_login(user)
        response = self.client.get(reverse('sensors:trail'), {'target': f'unit:{self.t1.pk}', 'range': '6h'})
        self.assertEqual(response.status_code, 200)
        answer = json.loads(response.content)
        self.assertEqual(answer['unworkable'], [{'at': start.isoformat(), 'why': why},
                                                {'at': (start + timedelta(hours=1)).isoformat(), 'why': why}])
        self.assertEqual(answer['points'], [])

    def test_the_trail_endpoint_needs_both_rights_and_gives_the_points(self):
        start = self.now - timedelta(hours=1)
        insert(self.ph.channel_no, [(start + timedelta(minutes=10), 7.2)])
        insert(self.channel.channel_no, [(start + timedelta(minutes=5), 10.0)])
        self.sample(self.mid1, start - timedelta(days=1), alkalinity_mg_l='100', salinity_ppt='0')
        user = get_user_model().objects.create_user('reader', 'reader@example.com', 'x')
        user.groups.add(role('Reader', 'view_watermeasurement'))
        self.client.force_login(user)
        url = reverse('sensors:trail')
        self.assertEqual(self.client.get(url, {'target': f'unit:{self.t1.pk}', 'range': '24h'}).status_code, 403)
        user.groups.add(role('Readings', 'view_reading'))
        user = get_user_model().objects.get(pk=user.pk)
        self.client.force_login(user)
        found = json.loads(self.client.get(url, {'target': f'unit:{self.t1.pk}', 'range': '6h'}).content)
        self.assertEqual(len(found['points']), 1)
        self.assertAlmostEqual(found['points'][0]['ph'], 7.2)


class BindFromMonitoringTests(HistoryCase):
    def test_a_cards_link_opens_the_move_dialog_with_the_channel_and_the_place(self):
        binder = get_user_model().objects.create_user('binder', 'binder@example.com', 'x')
        binder.groups.add(role('Binder', 'view_binding', 'add_binding'))
        self.client.force_login(binder)
        spare = make_channel(self.device, 'oxygen_mg_l')
        query = {'channel': spare.pk, 'target': f'point:{self.mid2.pk}'}
        form = self.client.get(reverse('sensors:binding_create'), query).context['form']
        self.assertEqual((str(form['channel'].value()), form['target'].value()), (str(spare.pk), f'point:{self.mid2.pk}'))
        local = timezone.localtime(self.now - timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M')
        self.client.post(reverse('sensors:binding_create'), {**query, 'role': 'primary', 'valid_from': local})
        self.assertEqual(Binding.objects.get(channel=spare).point, self.mid2)


class TrailOneRuleTests(HistoryCase):
    def test_each_hour_picks_by_the_one_rule_the_units_own_fresh_sample_before_the_systems_sensor(self):
        """The trail reads each input of an hour by `farm.water.read.choose` (owner rule A9) at the hour's end: the
        unit's own fresh temperature sample comes before the system's sensor, never sensor-before-sample (A1)."""
        start = self.now - timedelta(hours=3)
        insert(self.ph.channel_no, [(start + timedelta(hours=hour, minutes=10), 7.2) for hour in range(3)])
        insert(self.channel.channel_no, [(start + timedelta(hours=hour, minutes=5), 10.0) for hour in range(3)])
        self.sample(self.mid1, start - timedelta(days=1), alkalinity_mg_l='100', salinity_ppt='0')
        self.sample(self.mid1, start + timedelta(minutes=30), temperature_c='9.0')
        found = trail.trail(self.t1, start, self.now)
        self.assertEqual([point.temperature_c for point in found.points], [9.0, 9.0, 9.0])
