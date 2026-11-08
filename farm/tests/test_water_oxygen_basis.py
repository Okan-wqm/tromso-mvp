"""What an oxygen entry is worked out with (second cross review, finding 1): the temperature and the salinity an oxygen
in the other unit is worked out from are stored on the sample as its PROVENANCE (`oxygen_basis_*`: the value, where it
came from, when it was measured), never as a measurement of the sample. Only a value the person types is a
measurement. The basis is found by the server when the sample is written, at the sample's own point and time, by the
one resolver (owner rule A9): the point's latest temperature and salinity fresh AT the sample's time, else fresh water's
0 for the salinity; with none, the person is asked for it. So an offer is never re-stamped as a fresh value (P3), a
backdated entry never takes a value measured after it (P4), and another point's values never land on the point chosen
(P5); a temperature typed alone is a measurement and is stored (P6)."""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from ..feeding.temperature import temperature_for
from ..models import Tank, WaterMeasurement
from ..water import parameters, read, services
from .helpers import point_of
from .test_water_sources import SourcesCase

D = Decimal


class OxygenBasisCase(SourcesCase):
    def post(self, url, data):
        return self.client.post(url, data, headers={'X-Modal': '1'})

    def record_data(self, hours=1, **values):
        local = timezone.localtime(self.ago(hours=hours)).strftime('%Y-%m-%dT%H:%M')
        data = {'token': str(uuid.uuid4()), 'point': str(self.mid1.pk), 'measured_at': local, 'source': 'manual',
                'notes': '', **{code: '' for code in parameters.COLUMNS}}
        data.update(values)
        return data

    @property
    def url(self):
        return f'{reverse("farm:water_record")}?unit={self.t1.pk}'

    def oxygen_row(self):
        return WaterMeasurement.objects.filter(oxygen_mg_l__isnull=False).get()


class StoredAsProvenanceTests(OxygenBasisCase):
    def test_the_form_offers_the_latest_values_in_the_help_and_leaves_the_fields_empty(self):
        self.sample(hours=2, temperature_c='9.5')
        form = self.client.get(self.url, headers={'X-Modal': '1'}).context['form']
        self.assertEqual((form['temperature_c'].value(), form['salinity_ppt'].value()), (None, None))
        self.assertNotIn('temperature_offered', form.fields)
        help_text = str(form.fields['temperature_c'].help_text)
        self.assertIn('9.5', help_text)
        self.assertIn('manual · 2', help_text)

    def test_an_oxygen_alone_is_stored_with_its_basis_and_no_measured_temperature(self):
        earlier = self.sample(hours=2, temperature_c='9.5')
        self.assertEqual(self.post(self.url, self.record_data(oxygen_mg_l='8')).status_code, 204)
        row = self.oxygen_row()
        self.assertEqual((row.temperature_c, row.salinity_ppt), (None, None))           # nothing measured
        self.assertEqual((row.oxygen_basis_temperature_c, row.oxygen_basis_temperature_source,
                          row.oxygen_basis_temperature_at), (D('9.5'), 'manual', earlier.measured_at))
        self.assertEqual((row.oxygen_basis_salinity_ppt, row.oxygen_basis_salinity_source,
                          row.oxygen_basis_salinity_at), (D('0.0'), 'fresh_water', None))
        percent = read.history([WaterMeasurement.objects.select_related(*read.POINT_RELATED).get(pk=row.pk)])[0]
        note = percent.readings['oxygen_saturation_pct'].note
        self.assertIn('Worked out from 9.5 °C, 0.0 ‰ and 1.000 atm.', note)
        self.assertIn('The temperature is manual', note)
        self.assertIsNotNone(percent.readings['oxygen_saturation_pct'].value)

    def test_a_typed_temperature_is_a_measurement_and_no_basis_is_stored(self):
        self.sample(hours=2, temperature_c='9.5')
        self.post(self.url, self.record_data(oxygen_mg_l='8', temperature_c='9.5'))
        row = self.oxygen_row()
        self.assertEqual((row.temperature_c, row.oxygen_basis_temperature_c, row.oxygen_basis_temperature_source),
                         (D('9.5'), None, ''))

    def test_p6_a_temperature_retyped_alone_is_stored(self):
        self.sample(hours=20, temperature_c='9.5')
        # the old form sent its offer back in a hidden field and dropped a value equal to it: no longer
        data = self.record_data(hours=0, temperature_c='9.5', temperature_offered='9.5', salinity_offered='0')
        self.assertEqual(self.post(self.url, data).status_code, 204)
        self.assertEqual(WaterMeasurement.objects.filter(temperature_c=D('9.5')).count(), 2)

    def test_p3_a_basis_never_becomes_the_units_latest_temperature(self):
        self.on(self.ras, self.value('temperature_c', 9.5, seconds=30))
        self.assertEqual(self.post(self.url, self.record_data(hours=0, oxygen_mg_l='8')).status_code, 204)
        self.assertEqual((self.oxygen_row().oxygen_basis_temperature_c,
                          self.oxygen_row().oxygen_basis_temperature_source,
                          self.oxygen_row().oxygen_basis_temperature_channel), (D('9.5'), 'system_sensor', 1))
        self.provider.now_values.clear()
        self.on(self.ras, self.value('temperature_c', 16.0, seconds=5))
        reading = self.latest().get('temperature_c')
        self.assertEqual((reading.value, reading.origin), (D('16.0'), read.Origin.SYSTEM_SENSOR))

    def test_p4_a_backdated_entry_takes_the_temperature_fresh_at_its_own_time(self):
        self.sample(hours=0, temperature_c='12.0')                  # measured after the oxygen below
        response = self.post(self.url, self.record_data(hours=48, oxygen_mg_l='8'))
        self.assertEqual(response.status_code, 422)                 # nothing fresh at that time: asked for
        self.assertIn('temperature_c', response.context['form'].errors)
        self.assertFalse(WaterMeasurement.objects.filter(oxygen_mg_l__isnull=False).exists())
        then = self.sample(hours=50, temperature_c='10.0')          # fresh at -48 h
        self.post(self.url, self.record_data(hours=48, oxygen_mg_l='8'))
        row = self.oxygen_row()
        self.assertEqual((row.temperature_c, row.oxygen_basis_temperature_c, row.oxygen_basis_temperature_at),
                         (None, D('10.0'), then.measured_at))
        self.assertEqual(temperature_for([self.t1], self.ago(hours=47))[self.t1.pk].value_c, D('10.0'))

    def test_p5_the_basis_is_the_chosen_points_never_the_offered_ones(self):
        outlet = point_of(self.t1, 'side_outlet')
        self.sample(hours=2, temperature_c='9.5')                   # the middle's: the form's offer
        self.sample(point=outlet, hours=2, temperature_c='11.0')
        self.post(self.url, self.record_data(point=str(outlet.pk), oxygen_mg_l='8'))
        row = self.oxygen_row()
        self.assertEqual((row.point_id, row.temperature_c, row.oxygen_basis_temperature_c), (outlet.pk, None, D('11.0')))

    def test_in_sea_water_a_salinity_is_asked_for_when_none_is_fresh(self):
        Tank.objects.filter(pk=self.t1.pk).update(water_type='saltwater')
        self.sample(hours=2, temperature_c='9.5')
        response = self.post(self.url, self.record_data(oxygen_saturation_pct='95'))
        self.assertEqual(response.context['form'].errors['salinity_ppt'],
                         ['Needed with the oxygen: no fresh salinity here at that time to work the other unit out '
                          'with.'])
        self.assertFalse(WaterMeasurement.objects.filter(oxygen_saturation_pct__isnull=False).exists())

    def test_the_database_holds_a_basis_only_beside_an_oxygen_and_never_beside_its_own_value(self):
        sample = self.sample(hours=1, ph='7')
        for values in ({'oxygen_basis_temperature_c': D('9'), 'oxygen_basis_temperature_source': 'manual'},
                       {'oxygen_mg_l': D('8'), 'temperature_c': D('9'), 'oxygen_basis_temperature_c': D('9'),
                        'oxygen_basis_temperature_source': 'manual'},
                       {'oxygen_mg_l': D('8'), 'oxygen_basis_temperature_c': D('9')}):
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                WaterMeasurement.objects.filter(pk=sample.pk).update(**values)


class RoundTests(OxygenBasisCase):
    def test_a_round_stores_each_rows_basis_and_asks_where_there_is_none(self):
        self.sample(hours=2, temperature_c='9.5')
        url = f'{reverse("farm:water_round")}?site={self.bergen.pk}&columns=oxygen_mg_l'
        page = self.client.get(url)
        first = page.context['rows'][0]
        self.assertEqual((first.point, first['temperature_c'].value()), (self.mid1, None))
        self.assertIn('9.5', str(first.fields['temperature_c'].offered))
        self.assertNotContains(page, 'temperature_offered')
        local = timezone.localtime(self.ago(hours=1)).strftime('%Y-%m-%dT%H:%M')
        cells = lambda point, **values: {f'point-{point.pk}-{name}': value for name, value in values.items()}
        data = {'token': str(uuid.uuid4()), 'measured_at': local, 'source': 'manual',
                **cells(self.mid1, temperature_c='', oxygen_mg_l='8', salinity_ppt=''),
                **cells(self.mid2, temperature_c='', oxygen_mg_l='7', salinity_ppt=''),
                **cells(self.loop, temperature_c='', oxygen_mg_l='', salinity_ppt='')}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 422)                 # T-02 has no fresh temperature
        self.assertIn('temperature_c', response.context['rows'][1].errors)
        self.assertFalse(WaterMeasurement.objects.filter(oxygen_mg_l__isnull=False).exists())
        data.update(cells(self.mid2, temperature_c='10'))
        self.assertEqual(self.client.post(url, data).status_code, 302)
        stored = sorted(WaterMeasurement.objects.filter(oxygen_mg_l__isnull=False).values_list(
            'point__unit__code', 'temperature_c', 'oxygen_basis_temperature_c', 'oxygen_basis_salinity_ppt'))
        self.assertEqual(stored, [('T-01', None, D('9.5'), D('0.0')), ('T-02', D('10.0'), None, D('0.0'))])

    def test_the_round_reads_the_assumed_salinity_once_for_every_row(self):
        units = [self.t1, self.t2]
        for unit in units:
            self.sample(point=unit, hours=2, temperature_c='9.5')
        url = f'{reverse("farm:water_round")}?site={self.bergen.pk}&columns=oxygen_mg_l'
        from unittest import mock
        with mock.patch.object(read.Context, '_served', wraps=read.Context._served) as served:
            self.client.get(url)
        self.assertLessEqual(served.call_count, 2)                    # the read, and the assumed salinity: once each
