"""The water's ionic-strength inputs (chemcore/findings/I2-comparison.md, cross review F8): the conductivity compensated to
25 °C (specific conductance) and the total hardness are measured parameters of a sample and of a sensor, read as every
other parameter is (the latest per point, the calculator's offers), and the only conductivity the chemistry reads is the
compensated one: the process quantity `conductivity_us_cm` (a reading at the water's own temperature) never is."""
from decimal import Decimal as D

from django.db import IntegrityError, transaction

from sensors import quantities

from ..forms.water import CalculatorForm
from ..models import WaterMeasurement
from ..water import calculation, parameters, read
from .test_water import WaterTestCase
from farm import withdrawal_gate

CONDUCTIVITY, HARDNESS = 'conductivity_25_us_cm', 'hardness_mg_l'


class ParameterTests(WaterTestCase):
    def test_two_measured_parameters_with_their_unit_basis_and_range(self):
        conductivity, hardness = parameters.get(CONDUCTIVITY), parameters.get(HARDNESS)
        self.assertIn('25 °C', str(conductivity.label))
        self.assertIn('compensated', str(conductivity.label))
        self.assertEqual((conductivity.decimals, conductivity.low, conductivity.high, conductivity.fresh_hours),
                         (0, D(0), D(100000), 168))
        self.assertIn('as CaCO₃', str(hardness.label))
        self.assertEqual((hardness.decimals, hardness.low, hardness.high, hardness.fresh_hours), (0, D(0), D(10000), 336))
        self.assertTrue({CONDUCTIVITY, HARDNESS} <= set(parameters.COLUMNS))

    def test_a_sensor_measures_them_and_the_uncompensated_conductivity_stays_a_process_quantity(self):
        self.assertTrue(quantities.get(CONDUCTIVITY).water)
        self.assertEqual(quantities.get(CONDUCTIVITY).unit, 'µS/cm')
        self.assertTrue(quantities.get(HARDNESS).water)
        raw = quantities.get('conductivity_us_cm')
        self.assertFalse(raw.water)
        self.assertIsNone(raw.parameter)
        self.assertIn('water’s temperature', str(raw.label))
        self.assertNotIn('conductivity_us_cm', parameters.COLUMNS)

    def test_a_sample_records_them_and_they_are_the_points_latest(self):
        self.sample(hours=2, conductivity_25_us_cm='310', hardness_mg_l='120', alkalinity_mg_l='80')
        stored = WaterMeasurement.objects.get()
        self.assertEqual((stored.conductivity_25_us_cm, stored.hardness_mg_l), (D(310), D(120)))
        latest = read.latest([self.mid1])[self.mid1.pk]
        self.assertEqual((latest.get(CONDUCTIVITY).value, latest.get(HARDNESS).value), (D(310), D(120)))

    @withdrawal_gate.opened('test fixture: a value outside its range written straight in the database')
    def test_the_database_refuses_a_value_outside_the_range(self):
        for code, value in ((CONDUCTIVITY, D(100001)), (HARDNESS, D(-1))):
            with self.subTest(code=code), self.assertRaisesMessage(IntegrityError, f'chk_water_measurements_{code}'), \
                    transaction.atomic():
                WaterMeasurement.objects.create(point=self.mid1, measured_at=self.now, source='manual', **{code: value})

    def test_the_calculator_takes_them_and_a_unit_offers_its_own(self):
        form = CalculatorForm()
        self.assertTrue({CONDUCTIVITY, HARDNESS} <= set(form.fields))
        water_tab = next(names for key, _label, names in CalculatorForm.TABS if key == 'water')
        self.assertTrue({CONDUCTIVITY, HARDNESS} <= set(water_tab))
        self.assertTrue({CONDUCTIVITY, HARDNESS} <= set(calculation.MEASURED_FIELDS))
        self.sample(hours=2, conductivity_25_us_cm='310', hardness_mg_l='120')
        offered = calculation.offers(self.t1)
        self.assertEqual((offered[CONDUCTIVITY].value, offered[HARDNESS].value), (D(310), D(120)))
