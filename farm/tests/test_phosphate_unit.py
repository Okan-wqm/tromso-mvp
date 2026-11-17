"""The phosphate says its unit, and every dose says the phosphate it was worked out with (the independent review of
2026-11-16, R3; decided by the coordinator).

A phosphate kit reads PO₄³⁻ or PO₄-P; the same water is 3.07 times the number as PO₄. The input took mg/L as P only
and said "divide by 3.07" in its help: a PO₄ reading typed as P was taken by every recipe and simulator step. The
review's water (12 °C, S 0, alkalinity 80, pH 7.00, target pH 7.50 and alkalinity 100): a true P of 5 typed as 15.35
gave NaHCO₃ 2.14 + NaOH 14.96 g/m³ where 8.59 + 11.89 is right, a real pH of 7.70 and an NH₃ 58.7 % over the plan.

(a) Where a phosphate is typed (a sample, a round, the calculator) its unit is chosen: "as P (PO₄-P)", the default,
    changes nothing; "as PO₄" is converted to P at that door by the molar masses (farm/water/parameters.py, the one
    place), and a sample keeps what was entered and its unit beside the stored P, as the pH keeps its scale.
(b) Every recipe and simulator step worked out with a phosphate says so beside the result, in both units.
(c) The help names the 3.07-fold slip."""
import uuid
from decimal import Decimal as D

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog, Profile

from ..forms.water import CalculatorForm
from ..models import WaterMeasurement
from ..water import native, parameters, read, services
from .test_water import WaterTestCase

FACTOR = D('94.9714') / D('30.973762')            # PO₄ over P: 3.0662...
# The review's water and target, the calculator's default reagents and 1 m³.
WATER = {'temperature_c': '12', 'salinity_ppt': '0', 'alkalinity_mg_l': '80', 'ph': '7.00', 'target_ph': '7.50',
         'target_alkalinity_mg_l': '100', 'volume_m3': '1', 'reagents': ['nahco3', 'naoh'], 'drawn': '1'}
USED = 'Worked out with phosphate %s mg/L as P (%s as PO₄): a wrong phosphate changes this dose.'


def recipe_of(page):
    """(NaHCO₃, NaOH) in g/m³ of the page's bicarbonate and hydroxide recipe; None when it offers none."""
    for recipe in page.context['result'].recipes:
        doses = {dose.reagent.key: dose.mg_l for dose in recipe.doses}
        if set(doses) == {'nahco3', 'naoh'}:
            return doses['nahco3'], doses['naoh']
    return None


class FactorTests(SimpleTestCase):
    def test_the_factor_is_the_molar_masses(self):
        self.assertEqual(parameters.PO4_PER_P, FACTOR)
        self.assertEqual(float(parameters.P_G_PER_MOL), native.MG_P_PER_MMOL)            # the core's own P
        self.assertEqual(round(parameters.PO4_PER_P, 2), D('3.07'))                      # the number the help says
        self.assertEqual(parameters.phosphate_as_p(D('15.35'), 'po4'), D('15.35') / FACTOR)
        self.assertEqual(parameters.phosphate_as_p(D('15.35'), 'p'), D('15.35'))
        self.assertEqual(parameters.phosphate_as_po4(D('5')), D('5') * FACTOR)
        with self.assertRaises(KeyError):
            parameters.phosphate_as_p(D('1'), 'p2o5')

    def test_the_help_names_the_slip_in_three_languages(self):
        from django.utils import translation
        phosphate = parameters.get('phosphate_p_mg_l')
        said = str(phosphate.help)
        for words in ('3.07 times', 'as PO₄', 'every recipe and dose worked out with it is wrong'):
            self.assertIn(words, said)
        self.assertNotIn('divide by 3.07', said)                 # the unit is chosen, not worked out by hand
        for language, words in (('nb', '3,07 ganger'), ('tr', '3,07 kat')):
            with self.subTest(language=language), translation.override(language):
                self.assertIn(words, str(phosphate.help))
                self.assertNotEqual(str(phosphate.help), said)


class RecordTests(WaterTestCase):
    def record(self, unit='po4', hours=1, **values):
        return services.record(self.user, point=self.mid1, measured_at=self.ago(hours=hours), source='manual',
                               values={code: D(value) for code, value in values.items()}, phosphate_unit=unit)

    def refused_record(self, **kwargs):
        with self.assertRaises(ValidationError) as caught:
            self.record(**kwargs)
        return caught.exception.message_dict

    def test_a_po4_reading_is_stored_as_p_with_what_was_entered(self):
        sample = WaterMeasurement.objects.get(pk=self.record(phosphate_p_mg_l='15.35', ph='7.00').pk)
        self.assertEqual((sample.phosphate_p_mg_l, sample.phosphate_unit, sample.phosphate_as_measured),
                         (D('5.01'), 'po4', D('15.35')))
        self.assertEqual(sample.phosphate_p_mg_l, (D('15.35') / FACTOR).quantize(D('0.01')))
        changes = AuditLog.objects.filter(action=AuditLog.Action.CREATE).latest('pk').changes
        self.assertEqual(changes['Phosphate (mg/L PO₄ as P)'], [None, '5.01'])
        self.assertEqual(changes['Unit the phosphate was entered in'], [None, 'as PO₄ (mg/L of phosphate)'])
        self.assertEqual(changes['Phosphate as entered, in its own unit'], [None, '15.35'])

    def test_left_as_p_a_sample_is_stored_as_it_always_was(self):
        for hours, unit in enumerate(('p', '', None), start=1):
            sample = WaterMeasurement.objects.get(pk=self.record(unit=unit, hours=hours, phosphate_p_mg_l='5.00').pk)
            self.assertEqual((sample.phosphate_p_mg_l, sample.phosphate_unit, sample.phosphate_as_measured),
                             (D('5.00'), '', None))
        plain = services.record(self.user, point=self.mid1, measured_at=self.ago(hours=5), source='manual',
                                values={'phosphate_p_mg_l': D('5.00')})
        self.assertEqual((plain.phosphate_unit, plain.phosphate_as_measured), ('', None))

    def test_the_range_is_the_phosphorus_whatever_the_unit(self):
        """0 to 100 mg/L as P: as PO₄ that is up to 306.61."""
        self.assertEqual(self.record(phosphate_p_mg_l='306.61').phosphate_p_mg_l, D('100.00'))
        self.assertEqual(list(self.refused_record(phosphate_p_mg_l='306.70', hours=2)), ['phosphate_p_mg_l'])
        self.assertEqual(list(self.refused_record(unit='p', phosphate_p_mg_l='100.01', hours=2)), ['phosphate_p_mg_l'])
        self.assertEqual(list(self.refused_record(phosphate_p_mg_l='15.355', hours=2)), ['phosphate_p_mg_l'])  # 2 decimals
        self.assertEqual(self.refused_record(unit='p2o5', phosphate_p_mg_l='5', hours=2),
                         {'phosphate_unit': ['Choose the phosphate’s unit.']})
        self.assertEqual(WaterMeasurement.objects.count(), 1)

    def test_a_unit_without_a_phosphate_is_not_stored(self):
        sample = self.record(ph='7.20')
        self.assertEqual((sample.phosphate_p_mg_l, sample.phosphate_unit, sample.phosphate_as_measured), (None, '', None))

    def test_the_database_holds_the_unit_and_what_was_entered_together(self):
        sample = self.record(phosphate_p_mg_l='15.35')
        rows = WaterMeasurement.all_objects.filter(pk=sample.pk)
        for wrong in ({'phosphate_as_measured': None}, {'phosphate_unit': ''}, {'phosphate_unit': 'p2o5'},
                      {'phosphate_p_mg_l': None, 'ph': D('7.00')}, {'phosphate_as_measured': D('-1')}):
            with self.subTest(wrong=wrong), self.assertRaises(IntegrityError), transaction.atomic():
                rows.update(**wrong)

    def test_the_round_takes_one_unit_for_its_phosphates(self):
        samples = services.record_round(
            self.user, measured_at=self.ago(hours=1), source='manual', phosphate_unit='po4',
            rows=[(self.mid1, {'phosphate_p_mg_l': D('15.35')}, ''), (self.mid2, {'phosphate_p_mg_l': D('3.07')}, ''),
                  (self.loop, {'ph': D('7.10')}, '')])
        self.assertEqual([(sample.phosphate_p_mg_l, sample.phosphate_unit, sample.phosphate_as_measured)
                          for sample in samples],
                         [(D('5.01'), 'po4', D('15.35')), (D('1.00'), 'po4', D('3.07')), (None, '', None)])
        with self.assertRaises(ValidationError) as caught:
            services.record_round(self.user, measured_at=self.ago(hours=2), source='manual', phosphate_unit='po4',
                                  rows=[(self.mid1, {'phosphate_p_mg_l': D('5')}, ''),
                                        (self.mid2, {'phosphate_p_mg_l': D('400')}, '')])
        self.assertEqual(list(caught.exception.message_dict), ['1-phosphate_p_mg_l'])
        self.assertEqual(WaterMeasurement.objects.count(), 3)


class ReadTests(WaterTestCase):
    def setUp(self):
        super().setUp()
        services.record(self.user, point=self.mid1, measured_at=self.ago(hours=1), source='manual',
                        values={'phosphate_p_mg_l': D('15.35'), 'ph': D('7.00')}, phosphate_unit='po4')

    def test_the_reading_is_p_and_says_what_was_entered(self):
        reading = read.unit_water([self.t1])[self.t1.pk].get('phosphate_p_mg_l')
        self.assertEqual(reading.value, D('5.01'))
        self.assertEqual(str(reading.measured), 'entered as 15.35 mg/L PO₄')
        self.assertEqual(reading.provenance, 'Entered as 15.35 mg/L as PO₄; stored as phosphorus (PO₄-P), divided by '
                                             '3.066 (the molar masses of PO₄ and P).')

    def test_the_pages_say_it_in_visible_text(self):
        for query in ({'unit': self.t1.pk}, {'unit': self.t1.pk, 'view': 'history'}):
            with self.subTest(query=query):
                page = self.client.get(reverse('farm:water'), query)
                self.assertContains(page, '<span class="wq-source wq-measured">entered as 15.35 mg/L PO₄</span>')
                self.assertContains(page, '5.01')

    def test_a_reading_entered_as_p_says_nothing(self):
        services.record(self.user, point=self.mid1, measured_at=self.ago(hours=0), source='manual',
                        values={'phosphate_p_mg_l': D('5.00')})
        reading = read.unit_water([self.t1])[self.t1.pk].get('phosphate_p_mg_l')
        self.assertEqual((reading.value, reading.measured, reading.provenance), (D('5.00'), '', ''))

    def test_in_three_languages(self):
        for language, words in (('nb', 'angitt som 15,35 mg/L PO₄'), ('tr', '15,35 mg/L PO₄ olarak girildi')):
            with self.subTest(language=language):
                Profile.objects.update_or_create(user=self.user, defaults={'language': language})
                self.assertContains(self.client.get(reverse('farm:water'), {'unit': self.t1.pk}), words)


class FormTests(WaterTestCase):
    def data(self, **values):
        local = timezone.localtime(self.ago(hours=1)).strftime('%Y-%m-%dT%H:%M')
        return {'token': str(uuid.uuid4()), 'point': str(self.mid1.pk), 'measured_at': local, 'source': 'manual',
                'notes': '', **{code: '' for code in parameters.COLUMNS}, **values}

    def test_the_record_form_offers_the_unit_after_the_phosphate_and_p_is_chosen(self):
        page = self.client.get(reverse('farm:water_record'))
        form = page.context['form']
        self.assertEqual(form.fields['phosphate_unit'].initial, 'p')
        self.assertEqual([code for code, _label in form.fields['phosphate_unit'].choices], ['p', 'po4'])
        names = [field.name for _label, fields in form.value_groups() for field in fields]
        self.assertEqual(names[names.index('phosphate_p_mg_l') + 1], 'phosphate_unit')
        self.assertContains(page, 'as P (PO₄-P)')
        self.assertContains(page, 'as PO₄')
        self.assertContains(page, '3.07 times')

    def test_a_sample_through_its_form(self):
        response = self.client.post(reverse('farm:water_record'),
                                    self.data(phosphate_p_mg_l='15.35', phosphate_unit='po4'), headers={'X-Modal': '1'})
        self.assertEqual(response.status_code, 204, getattr(response, 'context', None) and response.context['form'].errors)
        sample = WaterMeasurement.objects.get()
        self.assertEqual((sample.phosphate_p_mg_l, sample.phosphate_unit, sample.phosphate_as_measured),
                         (D('5.01'), 'po4', D('15.35')))

    def test_a_po4_reading_above_the_range_of_p_goes_in_and_is_judged_as_p(self):
        """150 mg/L as PO₄ is 48.92 as P: inside the range, though 150 is past the 100 of a value as P."""
        response = self.client.post(reverse('farm:water_record'),
                                    self.data(phosphate_p_mg_l='150', phosphate_unit='po4'), headers={'X-Modal': '1'})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(WaterMeasurement.objects.get().phosphate_p_mg_l, D('48.92'))
        for unit, value in (('p', '150'), ('po4', '310'), ('', '101')):
            with self.subTest(unit=unit, value=value):
                response = self.client.post(reverse('farm:water_record'),
                                            self.data(phosphate_p_mg_l=value, phosphate_unit=unit, token=str(uuid.uuid4())),
                                            headers={'X-Modal': '1'})
                self.assertEqual(response.status_code, 422)
                self.assertIn('phosphate_p_mg_l', response.context['form'].errors)
        self.assertEqual(WaterMeasurement.objects.count(), 1)

    def test_a_round_through_its_page(self):
        url = f'{reverse("farm:water_round")}?site={self.bergen.pk}&columns=phosphate_p_mg_l'
        page = self.client.get(url)
        self.assertContains(page, 'name="phosphate_unit"')
        self.assertNotContains(self.client.get(f'{reverse("farm:water_round")}?site={self.bergen.pk}&columns=ph'),
                               'name="phosphate_unit"')
        local = timezone.localtime(self.ago(hours=1)).strftime('%Y-%m-%dT%H:%M')
        data = {'token': str(uuid.uuid4()), 'measured_at': local, 'source': 'manual', 'phosphate_unit': 'po4'}
        for row in page.context['rows']:
            data[f'point-{row.point.pk}-phosphate_p_mg_l'] = ''
        data[f'point-{self.mid1.pk}-phosphate_p_mg_l'] = '15.35'
        response = self.client.post(url, data, headers={'X-Modal': '1'})
        self.assertIn(response.status_code, (204, 302))
        sample = WaterMeasurement.objects.get()
        self.assertEqual((sample.phosphate_p_mg_l, sample.phosphate_unit, sample.phosphate_as_measured),
                         (D('5.01'), 'po4', D('15.35')))


class CalculatorTests(WaterTestCase):
    def page(self, name='farm:water_calculator', **values):
        return self.client.get(reverse(name), {**WATER, **values})

    def test_the_reviews_table(self):
        """True P 5: as P 5, or as PO₄ 15.35 with the unit chosen, both give the right recipe 8.59 + 11.89 g/m³; 15.35
        left as P (the slip) gives 2.14 + 14.96, and the page says which phosphate that was worked out with."""
        right = recipe_of(self.page(phosphate_p_mg_l='5'))
        self.assertAlmostEqual(right[0], 8.59, delta=0.005)
        self.assertAlmostEqual(right[1], 11.89, delta=0.005)
        chosen = self.page(phosphate_p_mg_l='15.35', phosphate_unit='po4')
        self.assertEqual(chosen.context['form'].errors, {})
        self.assertAlmostEqual(chosen.context['analysis'].water.phosphate_p_mg_l, float(D('15.35') / FACTOR), delta=1e-12)
        found = recipe_of(chosen)
        self.assertAlmostEqual(found[0], 8.59, delta=0.02)
        self.assertAlmostEqual(found[1], 11.89, delta=0.02)
        self.assertContains(chosen, USED % ('5.01', '15.35'))
        slip = self.page(phosphate_p_mg_l='15.35')
        wrong = recipe_of(slip)
        self.assertAlmostEqual(wrong[0], 2.14, delta=0.005)
        self.assertAlmostEqual(wrong[1], 14.96, delta=0.005)
        self.assertContains(slip, USED % ('15.35', '47.07'))
        # The review's other rows, the unit chosen: the right recipe is the one of the true P.
        for typed, true in (('6.14', 2.0), ('3.07', 1.0), ('30.7', 10.0)):
            with self.subTest(typed=typed):
                as_po4, as_p = self.page(phosphate_p_mg_l=typed, phosphate_unit='po4'), self.page(phosphate_p_mg_l=str(true))
                one, two = recipe_of(as_po4), recipe_of(as_p)
                self.assertEqual(one is None, two is None)
                if one is not None:
                    self.assertAlmostEqual(one[0], two[0], delta=0.03)
                    self.assertAlmostEqual(one[1], two[1], delta=0.03)

    def test_left_as_p_or_empty_the_calculator_is_what_it_was(self):
        self.assertEqual(CalculatorForm.DEFAULTS['phosphate_unit'], 'p')
        plain, chosen = self.page(phosphate_p_mg_l='5'), self.page(phosphate_p_mg_l='5', phosphate_unit='p')
        self.assertEqual(plain.context['analysis'], chosen.context['analysis'])
        self.assertEqual(plain.context['analysis'].water.phosphate_p_mg_l, 5.0)
        none, unit_only = self.page(), self.page(phosphate_unit='po4')
        self.assertEqual(none.context['analysis'], unit_only.context['analysis'])
        self.assertIsNone(none.context['analysis'].water.phosphate_p_mg_l)

    def test_every_dose_says_the_phosphate_it_was_worked_out_with(self):
        said = USED % ('5.00', '15.33')
        for name in ('farm:water_calculator', 'farm:water_calculator_results', 'farm:water_calculator_report'):
            with self.subTest(page=name):
                page = self.page(name, phosphate_p_mg_l='5', dose_naoh='10')
                self.assertEqual(page.status_code, 200)
                self.assertEqual(str(page.context['result'].phosphate_note), said)
                body = page.content.decode()
                recipes = body[body.index('calc-recipes'):]
                self.assertIn(said, recipes)                                     # beside the recipes
                simulator = body[body.index('calc-simulator'):body.index('calc-recipes')]
                self.assertIn(said, simulator)                                   # beside the simulator's steps
                self.assertEqual(body.count(said), 2)
        # Without an amount there are no steps: the simulator says nothing, the recipes still do.
        self.assertEqual(self.page(phosphate_p_mg_l='5').content.decode().count(said), 1)

    def test_without_a_phosphate_nothing_is_said(self):
        page = self.page(dose_naoh='10')
        self.assertEqual(page.context['result'].phosphate_note, '')
        self.assertNotContains(page, 'a wrong phosphate changes this dose')
        self.assertNotContains(self.page(phosphate_p_mg_l='0', dose_naoh='10'), 'a wrong phosphate changes this dose')

    def test_the_range_is_the_phosphorus_whatever_the_unit(self):
        self.assertEqual(self.page(phosphate_p_mg_l='150', phosphate_unit='po4', alkalinity_mg_l='400',
                                   target_alkalinity_mg_l='420').context['form'].errors, {})
        for unit, value in (('p', '150'), ('po4', '310'), ('', '100.5')):
            with self.subTest(unit=unit, value=value):
                page = self.page(phosphate_p_mg_l=value, phosphate_unit=unit, alkalinity_mg_l='400',
                                 target_alkalinity_mg_l='420')
                self.assertIn('phosphate_p_mg_l', page.context['form'].errors)
                self.assertIsNone(page.context['result'])

    def test_a_units_phosphate_is_loaded_as_p_and_is_not_converted_again(self):
        services.record(self.user, point=self.mid1, measured_at=self.ago(hours=1), source='manual',
                        values={'phosphate_p_mg_l': D('15.35'), 'ph': D('7.00'), 'temperature_c': D('12'),
                                'alkalinity_mg_l': D('80'), 'salinity_ppt': D('0')}, phosphate_unit='po4')
        owner = f'tank:{self.t1.pk}'
        page = self.client.get(reverse('farm:water_calculator'), {**WATER, 'phosphate_p_mg_l': '9', 'phosphate_unit': 'po4',
                                                                  'point': owner}, follow=True)
        form = page.context['form']
        self.assertEqual((form.cleaned_data['phosphate_p_mg_l'], form.cleaned_data['phosphate_unit'],
                          form.cleaned_data['phosphate_loaded']), (D('5.01'), 'p', D('5.01')))
        self.assertEqual(page.context['analysis'].water.phosphate_p_mg_l, 5.01)
        self.assertContains(page, 'entered as 15.35 mg/L PO₄')
        sent = {**WATER, 'phosphate_p_mg_l': '5.01', 'phosphate_unit': 'po4', 'point': owner, 'loaded': owner}
        for label, query in (('with the loaded value', {**sent, 'phosphate_loaded': '5.01'}), ('without it', sent)):
            with self.subTest(query=label):
                again = self.client.get(reverse('farm:water_calculator'), query)
                self.assertEqual(again.status_code, 200)
                self.assertIn('is the value loaded from T-01: it is as P already',
                              again.context['form'].errors['phosphate_unit'][0])
                self.assertIsNone(again.context['result'])
        typed = self.client.get(reverse('farm:water_calculator'), {**sent, 'phosphate_p_mg_l': '15.35',
                                                                  'phosphate_loaded': '5.01'})
        self.assertEqual(typed.context['form'].errors, {})
        self.assertAlmostEqual(typed.context['analysis'].water.phosphate_p_mg_l, float(D('15.35') / FACTOR), delta=1e-12)

    def test_in_three_languages(self):
        for language, words in (('nb', 'feil fosfat endrer denne dosen'), ('tr', 'yanlış bir fosfat bu dozu değiştirir')):
            with self.subTest(language=language):
                Profile.objects.update_or_create(user=self.user, defaults={'language': language})
                self.assertContains(self.page(phosphate_p_mg_l='5'), words)
