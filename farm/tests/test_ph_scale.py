"""The scale of a pH (the K_NH4 panel's decision of 2026-11-10, row 6; the owner's decision of 2026-11-11 on the scale
selector; chemcore/findings/pH-scale.md).

Every pH the application stores, shows and judges is on the NBS scale: what a meter calibrated with NBS/NIST buffers
reads. The panel found the largest single hazard of the ammonia chemistry here, larger than any question about a
constant: a total-scale pH (a seawater sensor calibrated with TRIS) typed in as NBS. So the input says its scale, and
where a pH is typed (a sample, a round, the calculator) its scale can be chosen: NBS, the default, changes nothing; a
pH on the total, the seawater or the free scale is put on the NBS scale by the core at that door, with the
temperature and the salinity of the same sample, for sea water of 5 ‰ or more only, and what was measured is kept
beside it. No page ever holds a pH on another scale than NBS, so none can mix them."""
import math
import uuid
from decimal import Decimal as D

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone, translation

from core.models import AuditLog, Profile

from ..forms.water import CalculatorForm
from ..models import Tank, WaterMeasurement
from ..water import native, parameters, read, services
from .helpers import point_of
from .test_stock import make_unit
from .test_water import WaterTestCase

HELP = ('As a pH meter or kit calibrated with NBS/NIST buffers reads it, at the water’s own temperature. A total-scale '
        'pH (a seawater sensor calibrated with TRIS) reads 0.10 to 0.14 lower in water of 5 to 35 ‰: typed here as NBS, '
        'the NH₃ worked out is 20 to 27 % too low.')
NOT_SEA = ('A pH on this scale is taken for sea water of 5 ‰ or more only (not fresh water with salt added): give the '
           'pH a meter calibrated with NBS/NIST buffers reads.')
NEEDED = 'Needed with a pH on another scale than NBS: the conversion takes the temperature and the salinity of the same sample.'


def nbs(ph, scale, temp_c, salinity):
    return native.water_equilibria(temp_c, salinity).ph_nbs(ph, scale)


class HelpTests(SimpleTestCase):
    def test_the_ph_says_its_scale_and_the_hazard_in_three_languages(self):
        ph = parameters.get('ph')
        self.assertEqual(str(ph.label), 'pH (NBS scale)')
        self.assertEqual(str(ph.help), HELP)
        for language, words in (('nb', ('NBS/NIST', 'TRIS', '0,10', '0,14', '5 til 35 ‰', '20 til 27 %')),
                                ('tr', ('NBS/NIST', 'TRIS', '0,10', '0,14', '5–35 ‰', '% 20–27'))):
            with self.subTest(language=language), translation.override(language):
                said = str(ph.help)
                self.assertNotEqual(said, HELP)
                for word in words:
                    self.assertIn(word, said)

    def test_the_numbers_in_the_help_are_the_cores_own(self):
        """By the core's own factors (formula 3) over 5 to 35 ‰ and 0 to 30 °C: the NBS pH less the total-scale pH,
        log10([H⁺]total / [H⁺]free) less the offset free − NBS, is 0.10 to 0.14; a total-scale pH of 8 typed as NBS
        makes the judged NH₃ 20 to 27 % lower than at the NBS pH the water really has."""
        apart, low = [], []
        for salinity in (5.0, 10.0, 20.0, 30.0, 35.0):
            for temp_c in (0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0):
                eq = native.water_equilibria(temp_c, salinity, 115.0)
                difference = math.log10(native.free_to_total(temp_c, salinity)) - eq.ph_offset
                apart.append(difference)
                low.append(1 - eq.nh3_share(8.0) / eq.nh3_share(8.0 + difference))
        self.assertEqual((round(min(apart), 2), round(max(apart), 2)), (0.10, 0.14))
        self.assertEqual((round(100 * min(low)), round(100 * max(low))), (20, 27))


class ConversionTests(SimpleTestCase):
    """The core's door (chemcore/core/src/scale.rs; its own tests are chemcore/core/tests/scale.rs)."""

    def test_the_scales(self):
        self.assertEqual(native.PH_SCALES, ('nbs', 'total', 'sws', 'free'))

    def test_an_nbs_ph_is_itself_in_every_water(self):
        for temp_c, salinity, more in ((12.0, 0.0, {}), (12.0, 3.0, {}), (2.0, 34.0, {}),
                                       (12.0, 20.0, {'water_origin': 'salt_added'})):
            eq = native.water_equilibria(temp_c, salinity, 80.0, **more)
            for ph in (6.5, 7.123456789, 8.31):
                self.assertEqual(eq.ph_nbs(ph, 'nbs'), ph)
                self.assertEqual(eq.ph_on(ph, 'nbs'), ph)

    def test_a_seawater_scale_by_its_definition(self):
        eq = native.water_equilibria(12.0, 34.0)
        total, sws = (math.log10(factor(12.0, 34.0)) for factor in (native.free_to_total, native.free_to_sws))
        self.assertEqual(eq.ph_nbs(7.95, 'total'), 7.95 + total - eq.ph_offset)
        self.assertEqual(eq.ph_nbs(7.95, 'sws'), 7.95 + sws - eq.ph_offset)
        self.assertEqual(eq.ph_nbs(7.95, 'free'), 7.95 - eq.ph_offset)
        self.assertAlmostEqual(eq.ph_nbs(7.95, 'total'), 8.0845, delta=0.001)       # 0.135 above, at 12 °C and 34 ‰
        self.assertAlmostEqual(eq.ph_on(eq.ph_nbs(7.95, 'total'), 'total'), 7.95, delta=1e-12)
        # The free [H⁺] the water's own constants then take is the total-scale pH's by the published definition: the
        # core's in-house NBS conversion cancels.
        self.assertAlmostEqual(eq.hydrogen(eq.ph_nbs(7.95, 'total')) / (10 ** -7.95 / native.free_to_total(12.0, 34.0)),
                               1.0, delta=1e-12)

    def test_only_sea_water_takes_another_scale(self):
        for salinity, more in ((0.0, {}), (3.0, {}), (4.99, {}), (20.0, {'water_origin': 'salt_added'})):
            eq = native.water_equilibria(12.0, salinity, 80.0, **more)
            for scale in ('total', 'sws', 'free'):
                self.assertFalse(eq.takes_ph_scale(scale))
                with self.assertRaises(native.SeawaterScaleError):
                    eq.ph_nbs(8.0, scale)
            self.assertTrue(eq.takes_ph_scale('nbs'))
        self.assertTrue(native.water_equilibria(12.0, 5.0).takes_ph_scale('total'))
        self.assertTrue(issubclass(native.SeawaterScaleError, ValueError))
        with self.assertRaises(ValueError):
            native.water_equilibria(12.0, 34.0).ph_nbs(8.0, 'NBS')                  # an unknown code is refused
        with self.assertRaises(native.NonFiniteError):
            native.water_equilibria(12.0, 34.0).ph_nbs(float('nan'), 'total')


class SeaTestCase(WaterTestCase):
    """A sea unit beside the fresh ones, and one of fresh water with salt added."""

    def setUp(self):
        super().setUp()
        self.sea = make_unit('S-01', self.hall)
        Tank.objects.filter(pk=self.sea.pk).update(water_type='saltwater', water_origin='seawater')
        self.sea.refresh_from_db()
        self.salted = make_unit('S-02', self.hall)
        Tank.objects.filter(pk=self.salted.pk).update(water_type='brackish', water_origin='salt_added')
        self.salted.refresh_from_db()
        self.sea_point, self.salted_point = point_of(self.sea), point_of(self.salted)

    def record(self, point=None, ph_scale='total', hours=1, **values):
        return services.record(self.user, point=point or self.sea_point, measured_at=self.ago(hours=hours),
                               source='manual', values={code: D(value) for code, value in values.items()},
                               ph_scale=ph_scale)

    def refused(self, **kwargs):
        with self.assertRaises(ValidationError) as caught:
            self.record(**kwargs)
        return caught.exception.message_dict


class RecordTests(SeaTestCase):
    def test_a_total_scale_ph_is_stored_on_the_nbs_scale_with_what_was_measured(self):
        sample = self.record(ph='7.95', temperature_c='12', salinity_ppt='34', tan_mg_l='1')
        wanted = D(str(round(nbs(7.95, 'total', 12.0, 34.0), 2)))
        self.assertEqual(wanted, D('8.08'))
        stored = WaterMeasurement.objects.get(pk=sample.pk)
        self.assertEqual((stored.ph, stored.ph_scale, stored.ph_as_measured, stored.ph_converted_formula),
                         (wanted, 'total', D('7.95'), 3))
        # The activity log holds both.
        changes = AuditLog.objects.get().changes
        self.assertEqual(str(changes['PH (NBS scale)'][1]), '8.08')                      # the log's capfirst
        self.assertEqual(str(changes['PH as measured, on its own scale'][1]), '7.95')
        self.assertIn('otal', str(changes['Scale the pH was measured on'][1]))
        self.assertEqual(str(changes['Formula the pH was put on the NBS scale by'][1]), '3')

    def test_every_scale(self):
        for hours, scale in enumerate(('total', 'sws', 'free'), start=1):
            sample = self.record(ph_scale=scale, hours=hours, ph='7.95', temperature_c='25', salinity_ppt='35')
            self.assertEqual(sample.ph, D(str(round(nbs(7.95, scale, 25.0, 35.0), 2))), scale)
            self.assertEqual((sample.ph_scale, sample.ph_as_measured), (scale, D('7.95')))

    def test_left_at_nbs_a_sample_is_stored_as_it_always_was(self):
        for hours, more in enumerate(({}, {'ph_scale': 'nbs'}), start=1):
            sample = services.record(self.user, point=self.sea_point, measured_at=self.ago(hours=hours), source='manual',
                                     values={'ph': D('7.95'), 'temperature_c': D('12'), 'salinity_ppt': D('34')}, **more)
            self.assertEqual((sample.ph, sample.ph_scale, sample.ph_as_measured, sample.ph_converted_formula),
                             (D('7.95'), '', None, None))
        fresh = services.record(self.user, point=self.mid1, measured_at=self.ago(hours=1), source='manual',
                                values={'ph': D('7.10')}, ph_scale='nbs')
        self.assertEqual((fresh.ph, fresh.ph_scale), (D('7.10'), ''))

    def test_it_needs_the_temperature_and_the_salinity_of_the_same_sample(self):
        self.record(ph_scale='nbs', hours=2, temperature_c='12', salinity_ppt='34')      # fresh values at the point
        self.assertEqual(self.refused(ph='7.95'), {'temperature_c': [NEEDED], 'salinity_ppt': [NEEDED]})
        self.assertEqual(self.refused(ph='7.95', temperature_c='12'), {'salinity_ppt': [NEEDED]})
        self.assertEqual(self.refused(ph='7.95', salinity_ppt='34'), {'temperature_c': [NEEDED]})
        self.assertEqual(WaterMeasurement.objects.count(), 1)

    def test_only_sea_water_of_5_permil_or_more(self):
        self.assertEqual(self.refused(ph='7.95', temperature_c='12', salinity_ppt='4.9'), {'ph_scale': [NOT_SEA]})
        self.assertEqual(self.refused(point=self.mid1, ph='7.10', temperature_c='12', salinity_ppt='0'),
                         {'ph_scale': [NOT_SEA]})
        self.assertEqual(self.refused(point=self.salted_point, ph='7.95', temperature_c='12', salinity_ppt='20'),
                         {'ph_scale': [NOT_SEA]})
        self.assertEqual(self.record(ph='7.95', temperature_c='12', salinity_ppt='5').ph_scale, 'total')
        self.assertEqual(self.refused(ph_scale='nonsense', ph='7.95', temperature_c='12', salinity_ppt='34'),
                         {'ph_scale': ['Choose a pH scale.']})

    def test_a_converted_ph_outside_the_phs_range_is_refused(self):
        errors = self.refused(ph='11.95', temperature_c='12', salinity_ppt='34')
        self.assertEqual(list(errors), ['ph'])

    def test_a_scale_without_a_ph_is_not_stored(self):
        sample = self.record(temperature_c='12', salinity_ppt='34')
        self.assertEqual((sample.ph, sample.ph_scale, sample.ph_as_measured), (None, '', None))

    def test_the_database_holds_the_scale_the_measurement_and_what_it_needs_together(self):
        sample = self.record(ph='7.95', temperature_c='12', salinity_ppt='34')
        def change(pk, column, value):
            # Straight to the table (a queryset update of a sample is the withdrawal guard's): the database alone answers.
            with self.assertRaises(IntegrityError, msg=(column, value)), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(f'UPDATE water_measurements SET {column} = %s WHERE id = %s', [value, pk])

        for column, value in (('ph_as_measured', None), ('ph_scale', ''), ('ph_scale', 'nbs'), ('ph_scale', 'other'),
                              ('salinity_ppt', None), ('temperature_c', None), ('salinity_ppt', D('4.9')),
                              ('ph_converted_formula', None), ('ph', None)):
            change(sample.pk, column, value)
        plain = self.record(ph_scale='nbs', hours=2, ph='7.95')
        change(plain.pk, 'ph_as_measured', D('7.80'))
        change(plain.pk, 'ph_converted_formula', 3)

    def test_the_round_takes_one_scale_for_its_phs(self):
        rows = [(self.sea_point, {'ph': D('7.95'), 'temperature_c': D('12'), 'salinity_ppt': D('34')}, ''),
                (self.mid1, {'temperature_c': D('9')}, '')]
        samples = services.record_round(self.user, measured_at=self.ago(hours=1), source='manual', rows=rows,
                                        ph_scale='total')
        by_point = {sample.point_id: sample for sample in samples}
        self.assertEqual((by_point[self.sea_point.pk].ph, by_point[self.sea_point.pk].ph_scale), (D('8.08'), 'total'))
        self.assertEqual((by_point[self.mid1.pk].ph, by_point[self.mid1.pk].ph_scale), (None, ''))
        with self.assertRaises(ValidationError) as caught:
            services.record_round(self.user, measured_at=self.ago(hours=2), source='manual', ph_scale='total',
                                  rows=[(self.sea_point, {'ph': D('7.95'), 'temperature_c': D('12')}, ''),
                                        (self.mid1, {'ph': D('7.1'), 'temperature_c': D('9'), 'salinity_ppt': D('0')}, '')])
        self.assertEqual(caught.exception.message_dict, {'0-salinity_ppt': [NEEDED], '1-ph_scale': [NOT_SEA]})


class ReadTests(SeaTestCase):
    def test_the_reading_is_nbs_and_says_what_was_measured(self):
        self.record(ph='7.95', temperature_c='12', salinity_ppt='34', tan_mg_l='1')
        water = read.latest([self.sea_point])[self.sea_point.pk]
        ph = water.get('ph')
        self.assertEqual(ph.value, D('8.08'))
        self.assertEqual(ph.provenance, 'Measured 7.95 on the total scale; put on the NBS scale by formula 3 with the '
                                        'sample’s 12.0 °C and 34.0 ‰.')
        # Its NH₃ is the NH₃ of the NBS pH, a quarter more than the reading typed as NBS would have given.
        eq = native.water_equilibria(12.0, 34.0)
        nh3 = water.get('nh3_n_mg_l').value
        self.assertEqual(nh3, D(str(eq.nh3_share(8.08))).quantize(D('0.0001')))
        self.assertGreater(float(nh3) / eq.nh3_share(7.95), 1.25)

    def test_an_nbs_reading_says_nothing(self):
        self.record(ph_scale='nbs', ph='8.08', temperature_c='12', salinity_ppt='34')
        self.assertEqual(read.latest([self.sea_point])[self.sea_point.pk].get('ph').provenance, '')

    def test_in_three_languages(self):
        self.record(ph='7.95', temperature_c='12', salinity_ppt='34')
        english = read.latest([self.sea_point])[self.sea_point.pk].get('ph').provenance
        for language in ('nb', 'tr'):
            with self.subTest(language=language), translation.override(language):
                said = read.latest([self.sea_point])[self.sea_point.pk].get('ph').provenance
                self.assertNotEqual(said, english)
                self.assertIn('7,95', said)
                self.assertIn('NBS', said)


class PageTests(SeaTestCase):
    def post(self, url, data):
        return self.client.post(url, data, headers={'X-Modal': '1'})

    def record_data(self, **values):
        local = timezone.localtime(self.ago(hours=1)).strftime('%Y-%m-%dT%H:%M')
        return {'token': str(uuid.uuid4()), 'point': str(self.sea_point.pk), 'measured_at': local, 'source': 'manual',
                'notes': '', **{code: '' for code in parameters.COLUMNS}, **values}

    def test_the_record_form_and_the_calculator_say_it_beside_the_ph(self):
        for name in ('farm:water_record', 'farm:water_calculator'):
            with self.subTest(page=name):
                page = self.client.get(reverse(name))
                self.assertEqual(page.status_code, 200)
                self.assertContains(page, 'calibrated with NBS/NIST buffers')
                self.assertContains(page, 'typed here as NBS, the NH₃ worked out is 20 to 27 % too low')
                self.assertContains(page, 'name="ph_scale"')
                self.assertContains(page, 'Total scale (calibrated with TRIS)')

    def test_the_record_form_offers_the_scale_after_the_ph_and_nbs_is_chosen(self):
        form = self.client.get(reverse('farm:water_record')).context['form']
        acid = [field.name for label, fields in form.value_groups() if 'ph' in [field.name for field in fields]
                for field in fields]
        self.assertEqual(acid[:2], ['ph', 'ph_scale'])
        self.assertEqual(form['ph_scale'].value(), 'nbs')
        self.assertEqual([code for code, _label in form.fields['ph_scale'].choices], list(native.PH_SCALES))

    def test_a_sample_through_its_form(self):
        url = reverse('farm:water_record')
        response = self.post(url, self.record_data(ph='7.95', ph_scale='total', temperature_c='12', salinity_ppt='34'))
        self.assertEqual(response.status_code, 204, getattr(response, 'context', None) and response.context['form'].errors)
        sample = WaterMeasurement.objects.get()
        self.assertEqual((sample.ph, sample.ph_scale, sample.ph_as_measured), (D('8.08'), 'total', D('7.95')))
        response = self.post(url, self.record_data(ph='7.95', ph_scale='total', temperature_c='12'))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.context['form'].errors['salinity_ppt'], [NEEDED])
        response = self.post(url, self.record_data(ph='7.95', ph_scale='total', temperature_c='12', salinity_ppt='3'))
        self.assertEqual(response.context['form'].errors['ph_scale'], [NOT_SEA])
        # Without the field at all (an old page, another client) the pH is NBS, as before.
        data = self.record_data(ph='7.95')
        self.assertEqual(self.post(url, data).status_code, 204)
        self.assertEqual(WaterMeasurement.objects.latest('created_at').ph_scale, '')
        self.assertEqual(WaterMeasurement.objects.count(), 2)

    def test_a_round_through_its_page(self):
        url = (f'{reverse("farm:water_round")}?site={self.bergen.pk}&columns=temperature_c&columns=ph'
               '&columns=salinity_ppt')
        page = self.client.get(url)
        self.assertContains(page, 'name="ph_scale"')
        self.assertNotContains(self.client.get(f'{reverse("farm:water_round")}?site={self.bergen.pk}'),
                               'name="ph_scale"')                   # no pH column, no scale to choose
        local = timezone.localtime(self.ago(hours=1)).strftime('%Y-%m-%dT%H:%M')
        data = {'token': str(uuid.uuid4()), 'measured_at': local, 'source': 'manual', 'ph_scale': 'total'}
        for row in page.context['rows']:
            for code in ('temperature_c', 'ph', 'salinity_ppt'):
                data[f'point-{row.point.pk}-{code}'] = ''
        data.update({f'point-{self.sea_point.pk}-ph': '7.95', f'point-{self.sea_point.pk}-temperature_c': '12',
                     f'point-{self.sea_point.pk}-salinity_ppt': '34'})
        self.assertEqual(self.post(url, data).status_code, 204)
        sample = WaterMeasurement.objects.get()
        self.assertEqual((sample.ph, sample.ph_scale, sample.ph_as_measured), (D('8.08'), 'total', D('7.95')))
        data.update({'token': str(uuid.uuid4()), f'point-{self.sea_point.pk}-salinity_ppt': '',
                     'measured_at': timezone.localtime(self.ago(hours=2)).strftime('%Y-%m-%dT%H:%M')})
        response = self.post(url, data)
        self.assertEqual(response.status_code, 422)
        row = next(row for row in response.context['rows'] if row.point == self.sea_point)
        self.assertEqual(row.errors['salinity_ppt'], [NEEDED])

    def test_the_history_and_the_latest_values_say_what_was_measured(self):
        self.record(ph='7.95', temperature_c='12', salinity_ppt='34')
        for query in ({'unit': self.sea.pk}, {'unit': self.sea.pk, 'view': 'history'}):
            page = self.client.get(reverse('farm:water'), query)
            self.assertContains(page, 'Measured 7.95 on the total scale; put on the NBS scale by formula 3',
                                msg_prefix=str(query))
            self.assertContains(page, '8.08', msg_prefix=str(query))


class CalculatorTests(SeaTestCase):
    WATER = {'temperature_c': '12', 'salinity_ppt': '34', 'alkalinity_mg_l': '115', 'tan_mg_l': '1', 'drawn': '1'}

    def page(self, name='farm:water_calculator', **values):
        return self.client.get(reverse(name), {**self.WATER, **values})

    def test_left_at_nbs_the_calculator_is_what_it_was(self):
        plain, chosen = self.page(ph='7.95'), self.page(ph='7.95', ph_scale='nbs')
        self.assertEqual(plain.context['analysis'], chosen.context['analysis'])
        self.assertEqual(plain.context['analysis'].water.ph, 7.95)
        self.assertIsNone(plain.context['ph_conversion'])
        self.assertEqual(CalculatorForm.DEFAULTS['ph_scale'], 'nbs')

    def test_a_total_scale_ph_is_worked_out_as_its_nbs_ph(self):
        wanted = nbs(7.95, 'total', 12.0, 34.0)
        for name in ('farm:water_calculator', 'farm:water_calculator_report'):
            with self.subTest(page=name):
                given, as_nbs = self.page(name, ph='7.95', ph_scale='total'), self.page(name, ph='8.08')
                self.assertEqual(given.status_code, 200)
                # Not rounded on the way: the calculator takes the converted pH itself.
                self.assertAlmostEqual(given.context['analysis'].nh3_n_mg_l,
                                       1.0 * native.water_equilibria(12.0, 34.0, 115.0).nh3_share(wanted), delta=1e-12)
                self.assertAlmostEqual(given.context['analysis'].nh3_n_mg_l, as_nbs.context['analysis'].nh3_n_mg_l,
                                       delta=0.02 * as_nbs.context['analysis'].nh3_n_mg_l)    # 8.0845 against 8.08
                self.assertContains(given, 'pH 7.95 on the total scale is 8.08 on the NBS scale')
                self.assertNotContains(as_nbs, 'on the total scale is')

    def test_it_is_refused_outside_sea_water_with_the_reason(self):
        page = self.page(ph='7.10', ph_scale='total', salinity_ppt='3')
        self.assertEqual(page.context['form'].errors['ph_scale'], [NOT_SEA])
        self.assertIsNone(page.context['result'])
        page = self.page(ph='7.95', ph_scale='total', salinity_ppt='20', water_origin='salt_added')
        self.assertEqual(page.context['form'].errors['ph_scale'], [NOT_SEA])

    def test_values_from_a_unit_are_nbs(self):
        self.record(ph='7.95', temperature_c='12', salinity_ppt='34', alkalinity_mg_l='115')
        page = self.client.get(reverse('farm:water_calculator'),
                               {**self.WATER, 'ph': '7.50', 'ph_scale': 'total', 'point': f'tank:{self.sea.pk}'}, follow=True)
        form = page.context['form']
        self.assertEqual((form.cleaned_data['ph'], form.cleaned_data['ph_scale']), (D('8.08'), 'nbs'))
        self.assertIsNone(page.context['ph_conversion'])

    def test_in_three_languages(self):
        for language, words in (('nb', 'på NBS-skalaen'), ('tr', 'NBS ölçeğinde')):
            with self.subTest(language=language):
                Profile.objects.update_or_create(user=self.user, defaults={'language': language})
                page = self.client.get(reverse('farm:water_calculator'), {**self.WATER, 'ph': '7,95', 'ph_scale': 'total'})
                self.assertContains(page, words)


class SensorTests(WaterTestCase):
    def test_a_ph_channel_says_its_scale(self):
        """The ingest stores what the device sends; a pH channel says the scale its probe reports on (NBS unless set
        otherwise) and the water reads it on the NBS scale (farm/tests/test_sensor_ph_scale.py): the stored pH quantity
        is NBS, and the channel's form says what a total-scale probe taken as NBS would do."""
        from sensors import quantities
        ph = quantities.get('ph')
        self.assertEqual(str(ph.label), 'pH (NBS scale)')
        self.assertIn('total scale', str(quantities.PH_SCALE_NOTE))
        self.assertIn('NBS', str(quantities.PH_SCALE_HELP))
        self.assertIn('is put on the NBS scale', str(quantities.PH_SCALE_HELP))
