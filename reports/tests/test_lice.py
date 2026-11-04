"""The weekly sea-lice report: the counts and the site's average, the cages that were due a count, the exceptions of
lakselusforskriften § 6, the treatments with their substances and the answers of the person, the temperature, and the
JSON as Mattilsynet's API takes it (validated against its OpenAPI)."""
from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock

from django.urls import reverse

from farm.health import services as health
from farm.models import Batch, HandlingPlanItem, Medicine, SamplingPoint, Site, Treatment
from farm.models.site import zone_of
from farm.stock import services as stock_services
from farm.tests.helpers import make_species, rows_data
from farm.tests.test_stock import make_unit
from farm.water import services as water_services

from .. import compute, exports
from ..compute import lice
from ..models import Report, ResistanceSuspicion, SensitivityTest, TreatmentAnswer
from ..periods import WEEK, Period
from .helpers import ReportTestCase, day
from .schema import errors

WEEK_44 = Period(WEEK, date(2026, 10, 26))         # Monday 26 October to Sunday 1 November
WARM, COLD = (Decimal('8.5'), []), (Decimal('3.0'), [])
AMOUNT_WARNING = ('The amount of a medicinal treatment is the amount used of the product; Mattilsynet asks for the '
                  'amount of the active substance: confirm which it wants.')


def temperature(value):
    return mock.patch.object(lice, 'sea_temperature', return_value=value)


class LiceTestCase(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.sea.lice_area = Site.LiceArea.SOUTH
        self.sea.timezone = 'Europe/Oslo'             # the authority's clock: no warning of another one
        self.sea.save()
        self.m2 = make_unit('M-02', self.bay, regulatory_unit_id='2')
        self.stock(self.m1, 5000, '200', day(10, 1))
        self.stock(self.m2, 3000, '200', day(10, 1))
        self.draft = self.report(Report.Kind.SEA_LICE, WEEK_44, site=self.sea)
        self.medicine = Medicine.objects.create(
            name='Salmosan', kind='lice', administration='bath', active_substance='azamethiphos',
            lice_report_code='AZAMETHIPHOS', strength_value=Decimal(500), strength_unit='MILLIGRAM_PER_GRAM')

    def count(self, unit, month, number, fish=20, females=4, mobile=10, attached=20):
        return health.record_lice_count(self.user, unit=unit, day=day(month, number), fish_counted=fish,
                                        adult_females=females, mobile=mobile, attached=attached)

    def treat(self, units, start, end, method='bath', **fields):
        medicinal = method in ('bath', 'dip', 'in_feed', 'injection')
        if medicinal:
            fields = {'amount_value': Decimal('12.5'), 'amount_unit': 'KILO', **fields}
        return health.record_treatment(
            self.user, units=units, method=method, reason='sea_lice', start_date=start, end_date=end,
            medicine=self.medicine if medicinal else None, **fields)

    def result(self, value=WARM, report=None):
        report = report or self.draft
        with temperature(value):
            return compute.compute(report)


class CountsTests(LiceTestCase):
    def test_the_sites_average_is_the_mean_of_the_cages_averages(self):
        self.count(self.m1, 10, 27)                                                 # 0.2, 0.5, 1.0 per fish
        self.count(self.m2, 10, 28, females=2, mobile=6, attached=10)               # 0.1, 0.3, 0.5
        health.record_lice_count(self.user, unit=self.m1, day=day(10, 29), fish_counted=40, adult_females=4,
                                 mobile=40, attached=40)       # the latest of the cage counts: 0.1, 1.0, 1.0
        result = self.result()
        self.assertEqual((result.problems, result.warnings), ([], []))
        counts = result.content['counts']
        self.assertEqual([(cage['number'], cage['date'], cage['fish']) for cage in counts['cages']],
                         [('1', '2026-10-29', 40), ('2', '2026-10-28', 20)])
        self.assertEqual((counts['adult_females'], counts['mobile'], counts['attached']), ('0.100', '0.650', '0.750'))
        self.assertEqual((result.content['temperature_c'], result.content['kind'], result.content['period']),
                         ('8.5', 'sea_lice', '2026-W44'))
        self.assertEqual(result.content['identity']['lokalitetsnummer'], 23456)

    def test_a_small_sample_and_a_site_over_its_limit_are_warned_not_blocked(self):
        self.count(self.m1, 10, 27, fish=20, females=20, mobile=1, attached=1)       # 1.0 adult female per fish
        self.count(self.m2, 10, 27, fish=5, females=5, mobile=1, attached=1)
        result = self.result()
        self.assertEqual(result.problems, [])
        self.assertEqual(result.warnings, [
            'M-02: 5 fish counted on 2026-10-27, where the regulation asks for 10 in this week.',
            'The site’s average of adult female lice, 1.000, is not below the limit of 0.5 (lakselusforskriften § 8).'])

    def test_a_site_without_a_limit_area_is_judged_by_the_stricter_one_and_says_so(self):
        self.sea.lice_area = ''
        self.sea.save()
        self.count(self.m1, 10, 27)
        self.count(self.m2, 10, 27)
        self.assertIn('Fjord (FJ) has no sea-lice limit area (Facility › Sites): the stricter limit and the larger '
                      'sample are applied.', self.result().warnings)

    def test_without_a_sea_temperature_at_3_m_it_is_not_ready(self):
        self.count(self.m1, 10, 27)
        self.count(self.m2, 10, 27)
        report = self.draft
        result = compute.compute(report)         # no depth on the water samples yet: nothing to read (OUR-13)
        self.assertEqual(result.problems, ['Fjord (FJ) has no sea temperature at 3 m depth for the week: record a '
                                           'water sample at a depth point of 3 m (Operations › Water chemistry).'])
        self.assertIsNone(result.content['temperature_c'])

    def test_the_temperature_is_the_mean_of_the_weeks_samples_at_3_m(self):
        self.count(self.m1, 10, 27)
        self.count(self.m2, 10, 27)
        three = SamplingPoint.objects.create(unit=self.m1, name='3 m', kind='depth', depth_m=Decimal('3.0'))
        three_too = SamplingPoint.objects.create(unit=self.m2, name='3 m', kind='depth', depth_m=Decimal('3.0'))
        five = SamplingPoint.objects.create(unit=self.m1, name='5 m', kind='depth', depth_m=Decimal('5.0'))
        middle = SamplingPoint.objects.create(unit=self.m1, name='Middle', kind='middle')

        def sample(point, month, number, value, hour=12):
            moment = datetime.combine(day(month, number), time(hour), tzinfo=zone_of(self.sea))
            return water_services.record(self.user, point=point, measured_at=moment, source='manual',
                                         values={'temperature_c': Decimal(value)})
        first = sample(three, 10, 27, '8.4')
        second = sample(three_too, 10, 29, '9.1')
        sample(five, 10, 28, '3.0')                          # another depth
        sample(middle, 10, 28, '2.0')                        # not a depth point
        sample(three, 10, 20, '1.0')                         # the week before
        sample(three, 11, 2, '1.0')                          # the week after
        voided = sample(three, 10, 30, '20.0')
        water_services.void(self.user, voided, 'Wrong point')
        result = compute.compute(self.draft)
        self.assertEqual((result.problems, result.content['temperature_c']), ([], '8.8'))     # (8.4 + 9.1) / 2, half up
        self.assertEqual(result.content['samples'], sorted([str(first.pk), str(second.pk)]))
        # What it read is in its sources: a void of one of them changes the fingerprint.
        before = compute.fingerprint(result.scope)
        water_services.void(self.user, second, 'Wrong unit')
        self.assertNotEqual(compute.fingerprint(compute.compute(self.draft).scope), before)

    def test_a_site_on_another_clock_than_oslos_is_told_that_the_authoritys_week_is_oslos(self):
        self.count(self.m1, 10, 27)
        self.count(self.m2, 10, 27)
        self.assertFalse(any('another clock' in warning for warning in self.result().warnings))
        self.sea.timezone = 'Asia/Tokyo'
        self.sea.save()
        self.assertIn('Fjord (FJ) keeps another clock than Oslo’s: the week and its samples are the site’s, the '
                      'authority’s week is Oslo’s.', self.result().warnings)

    def test_a_week_without_salmonids_has_nothing_to_file(self):
        report = self.report(Report.Kind.SEA_LICE, Period(WEEK, date(2026, 9, 7)), site=self.sea)
        self.assertEqual(self.result(report=report).problems[0],
                         'No unit of the site held salmonids in the week: the report has nothing to file.')
        # Another species is not a salmonid for this report (D-11).
        self.salmon.official_code = 'COD'
        self.salmon.save()
        self.assertIn('No unit of the site held salmonids', ' '.join(self.result().problems))


class CoverageTests(LiceTestCase):
    def test_a_cage_due_a_count_without_one_keeps_it_from_being_ready(self):
        self.count(self.m1, 10, 27)
        result = self.result()
        self.assertEqual(result.problems, [
            'M-02 held salmonids and was due a count by 2026-10-08: count it, or the site’s average is not of every '
            'cage.'])
        self.count(self.m2, 10, 22)               # counted the week before: due again 7 days on, inside this week
        self.assertEqual(self.result().problems, [
            'M-02 held salmonids and was due a count by 2026-10-29: count it, or the site’s average is not of every '
            'cage.'])
        self.count(self.m2, 10, 30)
        self.assertEqual(self.result().problems, [])

    def test_below_4_degrees_a_count_is_due_every_14_days_and_a_week_may_have_none(self):
        self.count(self.m1, 10, 22)
        self.count(self.m2, 10, 22)
        self.assertEqual(len(self.result(WARM).problems), 2)         # 22 October + 7 days is inside the week
        report = self.draft
        result = self.result(COLD, report)        # 22 October + 14 days is after the week: nothing fell due
        self.assertEqual((result.problems, result.content['counts']), ([], None))
        self.assertEqual(result.warnings, ['No count fell due in the week: it is filed with the temperature and '
                                           'without counts.'])
        self.assertIsNone(exports.api_json(report, result.content)['lusetelling'])

    def test_a_count_after_a_longer_gap_than_the_regulation_allows_is_warned(self):
        self.count(self.m1, 10, 15)
        self.count(self.m1, 10, 27)                   # 12 days later: the count was late
        self.count(self.m2, 10, 20)
        self.count(self.m2, 10, 27)                   # 7 days later: in time
        warnings = self.result().warnings
        self.assertIn('M-01 was counted on 2026-10-27 and before that on 2026-10-15: the regulation asks for a count '
                      'at least every 7 days (§ 6).', warnings)
        self.assertFalse(any('M-02 was counted' in warning for warning in warnings))

    def test_broodstock_below_4_degrees_is_not_counted(self):
        self.sea.production_form = Site.ProductionForm.STAMFISK
        self.sea.save()
        self.assertNotEqual(self.result(WARM).problems, [])
        self.assertEqual(self.result(COLD).problems, [])

    def test_a_site_planned_for_slaughter_within_14_days_needs_no_count(self):
        self.count(self.m1, 10, 22)             # due again on 29 October
        self.count(self.m2, 10, 22)
        self.assertNotEqual(self.result().problems, [])
        for unit, fish in ((self.m1, 5000), (self.m2, 3000)):
            batch = Batch.objects.get(movements__unit=unit)
            HandlingPlanItem.objects.create(kind='harvest', date=day(11, 5), unit=unit, batch=batch, planned_count=fish,
                                            facility=self.facility, created_by=self.user)
        result = self.result()
        self.assertEqual(result.problems, [])
        self.assertEqual(result.warnings, ['Every fish of the site is planned for slaughter within 14 days of the day '
                                           'the count fell due: no count is needed (lakselusforskriften § 6).'])


    def harvest(self, unit, on, count, kilos):
        batch = Batch.objects.get(movements__unit=unit, species=self.salmon)
        return stock_services.record_harvest(self.user, unit=unit, batch=batch, day=on, count=count,
                                             measured_weight_kg=Decimal(kilos), facility=self.facility)

    def test_harvests_already_recorded_keep_the_exception_and_one_voided_does_not(self):
        self.count(self.m1, 10, 22)             # due again on 29 October
        self.count(self.m2, 10, 22)
        items = []
        for unit, fish in ((self.m1, 5000), (self.m2, 3000)):
            batch = Batch.objects.get(movements__unit=unit)
            items.append(HandlingPlanItem.objects.create(kind='harvest', date=day(10, 31), unit=unit, batch=batch,
                                                         planned_count=fish, facility=self.facility,
                                                         created_by=self.user))
        self.assertEqual(self.result().problems, [])                                  # planned
        operations = []
        for item in items:                                                            # recorded on 31 October
            operation = self.harvest(item.unit, day(10, 31), item.planned_count, 800)
            HandlingPlanItem.objects.filter(pk=item.pk).update(operation=operation)
            operations.append(operation)
        self.assertEqual(self.result().problems, [])                                  # the exception does not lapse
        stock_services.void(self.user, operations[0], 'Wrong cage')
        HandlingPlanItem.objects.filter(pk=items[0].pk).update(operation=None)
        self.assertEqual(self.result().problems, [])                                  # planned again
        HandlingPlanItem.objects.filter(pk=items[0].pk).update(cancelled_reason='Weather')
        self.assertEqual(len(self.result().problems), 2)           # not every fish is planned: both cages are due

    def test_a_harvest_recorded_before_the_due_day_is_no_cover_for_the_fish_that_remain(self):
        self.count(self.m1, 10, 22)             # due again on 29 October
        self.count(self.m2, 10, 22)
        batches = {unit: Batch.objects.filter(movements__unit=unit).distinct().get() for unit in (self.m1, self.m2)}

        def plan(unit, on, fish):
            return HandlingPlanItem.objects.create(kind='harvest', date=on, unit=unit, batch=batches[unit],
                                                   planned_count=fish, facility=self.facility, created_by=self.user)
        first = plan(self.m1, day(10, 10), 2500)
        HandlingPlanItem.objects.filter(pk=first.pk).update(operation=self.harvest(self.m1, day(10, 10), 2500, 500))
        plan(self.m2, day(11, 5), 3000)
        # M-01's other 2,500 fish have no plan: the harvest of 10 October took the fish it names out already.
        self.assertEqual(len(self.result().problems), 2)
        plan(self.m1, day(11, 5), 2500)
        self.assertEqual(self.result().problems, [])

    def test_a_cage_emptied_before_its_count_fell_due_needs_none(self):
        self.count(self.m1, 10, 27)
        self.count(self.m2, 10, 22)             # M-02 is due on 29 October
        self.assertEqual(len(self.result().problems), 1)
        self.harvest(self.m2, day(10, 27), 3000, 600)
        self.assertEqual(self.result().problems, [])

    def test_cleaner_fish_in_a_cage_are_not_harvested_and_do_not_keep_the_exemption_away(self):
        lump = make_species('LUM', 'Lumpfish', 'Cyclopterus lumpus', local_name='Rognkjeks', freshwater=False,
                            official_code='LUM', cleaner_fish_type='lumpfish')
        stock_services.record_input(self.user, species=lump, input_stage='fry', origin='own_hatchery', day=day(10, 1),
                                    lines=[(self.m1, 2000, Decimal(50))])
        self.count(self.m1, 10, 22)
        self.count(self.m2, 10, 22)
        for unit, fish in ((self.m1, 5000), (self.m2, 3000)):           # every salmon of the site, no lumpfish
            batch = Batch.objects.get(movements__unit=unit, species=self.salmon)
            HandlingPlanItem.objects.create(kind='harvest', date=day(11, 5), unit=unit, batch=batch, planned_count=fish,
                                            facility=self.facility, created_by=self.user)
        result = self.result()
        self.assertEqual(result.problems, [])
        self.assertIn('Every fish of the site is planned for slaughter within 14 days of the day the count fell due: '
                      'no count is needed (lakselusforskriften § 6).', result.warnings)


class TreatmentTests(LiceTestCase):
    def setUp(self):
        super().setUp()
        self.count(self.m1, 10, 27)
        self.count(self.m2, 10, 28)

    def treatments(self, **kwargs):
        return self.result(**kwargs).content['treatments']

    def test_a_medicinal_bath_with_its_substance_strength_and_amount_before_the_counts(self):
        self.treat([self.m1, self.m2], day(10, 26), day(10, 26))
        row, = self.treatments()
        self.assertEqual({key: row[key] for key in ('medicinal', 'type', 'whole_site', 'cages', 'before_count',
                                                    'combination', 'start', 'end', 'description')},
                         {'medicinal': True, 'type': 'BADEBEHANDLING', 'whole_site': True, 'cages': None,
                          'before_count': True, 'combination': None, 'start': '2026-10-26', 'end': '2026-10-26',
                          'description': None})
        self.assertEqual(row['substance'], {
            'type': 'AZAMETHIPHOS', 'other': None, 'strength': {'value': '500.000', 'unit': 'MILLIGRAM_PER_GRAM'},
            'amount': {'value': '12.500', 'unit': 'KILO'}})
        self.assertEqual(self.result().problems, [])

    def test_a_treatment_of_some_cages_names_how_many_and_one_after_the_counts_is_not_before(self):
        self.treat([self.m1], day(10, 30), day(10, 30), method='thermal')
        row, = self.treatments()
        self.assertEqual((row['medicinal'], row['type'], row['substance'], row['whole_site'], row['cages'],
                          row['before_count']), (False, 'TERMISK_BEHANDLING', None, False, 1, False))

    def test_a_treatment_that_ended_on_the_day_of_a_count_is_asked_about_and_the_answer_is_kept(self):
        treatment = self.treat([self.m1, self.m2], day(10, 27), day(10, 27), method='mechanical')
        report = self.draft
        problems = self.result(report=report).problems
        self.assertEqual(problems, ['Say whether the treatment of 2026-10-27 was given before the count (the '
                                    'Treatments tab): the count was taken on the day it ended.'])
        TreatmentAnswer.objects.create(report=report, treatment=treatment, done_before_count=True)
        result = self.result(report=report)
        self.assertEqual((result.problems, result.content['treatments'][0]['before_count']), ([], True))

    def test_a_medicine_without_a_substance_or_a_strength_and_a_treatment_without_an_amount_are_problems(self):
        other = Medicine.objects.create(name='Other', kind='antiparasitic', administration='bath',
                                        active_substance='x')
        self.medicine = other
        self.treat([self.m1, self.m2], day(10, 26), day(10, 26), amount_value=None, amount_unit='')
        self.assertEqual(self.result().problems, [
            'Other has no substance in the lice report (Reference data › Medicines): the treatment of 2026-10-26 '
            'cannot be reported.',
            'Other has no strength (Reference data › Medicines).',
            'The treatment of 2026-10-26 has no amount used (Operations › Health): the report asks for it.'])

    def test_a_treatment_without_a_medicine_is_one_of_the_other_methods_and_other_is_described(self):
        self.treat([self.m1, self.m2], day(10, 26), day(10, 26), method='freshwater')
        self.treat([self.m1, self.m2], day(10, 26), day(10, 26), method='other', notes='Brushing')
        rows = {row['type']: row for row in self.treatments()}
        self.assertEqual((rows['FERSKVANNSBEHANDLING']['description'], rows['ANNEN_BEHANDLING']['description']),
                         (None, 'Brushing'))

    def test_the_amount_of_a_medicinal_treatment_is_flagged_as_the_products_and_a_plain_one_is_not(self):
        self.treat([self.m1], day(10, 30), day(10, 30), method='thermal')
        self.assertNotIn(AMOUNT_WARNING, self.result().warnings)
        self.treat([self.m1, self.m2], day(10, 26), day(10, 26))
        self.assertEqual(self.result().warnings.count(AMOUNT_WARNING), 1)

    def test_other_is_described_and_a_treatment_of_no_cage_with_salmonids_is_a_problem(self):
        # The treatment dialog refuses an undescribed "other"; a record written another way is told here.
        other = self.treat([self.m1, self.m2], day(10, 26), day(10, 26), method='other', notes='Brushing')
        Treatment.objects.filter(pk=other.pk).update(notes='')
        self.assertIn('Describe the treatment of 2026-10-26 (Operations › Health): “other” is described in the report.',
                      self.result().problems)
        cod = make_species('COD', 'Cod', 'Gadus morhua', local_name='Torsk', official_code='COD')
        cages = make_unit('M-03', self.bay, regulatory_unit_id='3')
        stock_services.record_input(self.user, species=cod, input_stage='smolt', origin='own_hatchery', day=day(10, 1),
                                    lines=[(cages, 100, Decimal(50))])
        self.treat([cages], day(10, 27), day(10, 27), method='thermal')
        self.assertIn('The treatment of 2026-10-27 was of no unit that held salmonids: the report cannot say how many '
                      'cages were treated.', self.result().problems)

    def test_injections_baths_and_feed_are_the_reports_types(self):
        for method, kind in (('in_feed', 'FORBEHANDLING'), ('dip', 'BADEBEHANDLING'), ('injection', 'ANNEN_BEHANDLING')):
            Report.objects.all().delete()
            self.medicine.administration = method
            self.medicine.save()
            treatment = self.treat([self.m1, self.m2], day(10, 26), day(10, 26), method=method)
            row = next(item for item in self.treatments() if item['treatment'] == str(treatment.pk))
            self.assertEqual((row['type'], row['description']),
                             (kind, 'Injeksjon' if method == 'injection' else None), method)

    def test_a_treatment_across_two_weeks_is_in_both_and_a_lice_free_reason_is_in_neither(self):
        self.treat([self.m1, self.m2], day(10, 24), day(10, 28))
        previous = self.report(Report.Kind.SEA_LICE, Period(WEEK, date(2026, 10, 19)), site=self.sea)
        self.assertEqual(len(self.result(report=previous).content['treatments']), 1)
        self.assertEqual(len(self.treatments()), 1)
        health.record_treatment(self.user, units=[self.m1], method='thermal', reason='parasites',
                                start_date=day(10, 26), end_date=day(10, 26))
        self.assertEqual(len(self.treatments()), 1)

    def test_treatments_given_together_are_a_combination_of_at_least_two(self):
        first = self.treat([self.m1, self.m2], day(10, 26), day(10, 26))
        second = self.treat([self.m1, self.m2], day(10, 26), day(10, 26), method='thermal')
        report = self.draft
        TreatmentAnswer.objects.create(report=report, treatment=first, done_before_count=True, combination=1)
        self.assertEqual(self.result(report=report).problems,
                         ['Combination 1 is of one treatment: a combination is of at least two.'])
        TreatmentAnswer.objects.create(report=report, treatment=second, done_before_count=True, combination=1)
        result = self.result(report=report)
        self.assertEqual(result.problems, [])
        self.assertEqual([row['combination'] for row in result.content['treatments']], [1, 1])


class AnswersAndExportTests(LiceTestCase):
    def setUp(self):
        super().setUp()
        self.count(self.m1, 10, 27)
        self.count(self.m2, 10, 28)
        self.report_ = self.draft

    def test_the_week_as_mattilsynets_api_takes_it_validated_against_its_openapi(self):
        first = self.treat([self.m1, self.m2], day(10, 26), day(10, 26))
        self.treat([self.m1], day(10, 30), day(10, 30), method='thermal')
        third = self.treat([self.m1, self.m2], day(10, 26), day(10, 26), method='mechanical')
        TreatmentAnswer.objects.create(report=self.report_, treatment=first, done_before_count=True, combination=1)
        TreatmentAnswer.objects.create(report=self.report_, treatment=third, done_before_count=True, combination=1)
        ResistanceSuspicion.objects.create(report=self.report_, substance='ANNEN_RESISTENS',
                                           other_substance='Ivermectin', cause='BIOESSAY')
        SensitivityTest.objects.create(report=self.report_, tested_on=day(10, 20), laboratory='FiskLab AS',
                                       substance='DELTAMETHRIN', result='FØLSOM')
        result = self.result(report=self.report_)
        self.assertEqual(result.problems, [])
        body = exports.api_json(self.report_, result.content)
        self.assertEqual(errors(body, 'LakselusrapporteringDto'), [])
        self.assertEqual((body['rapporteringsår'], body['rapporteringsuke'], body['sjøtemperatur'],
                          body['organisasjonsnummer'], body['lokalitetsnummer']), (2026, 44, 8.5, '987654321', 23456))
        self.assertEqual(body['lusetelling'], {'voksneHunnlus': 0.2, 'bevegeligeLus': 0.5, 'fastsittendeLus': 1})
        self.assertEqual(body['ikkeMedikamentelleBehandlinger'], [{
            'type': 'TERMISK_BEHANDLING', 'beskrivelse': None, 'gjennomførtFørTelling': False, 'heleLokaliteten': False,
            'antallMerder': 1}])
        self.assertEqual(body['medikamentelleBehandlinger'], [])
        combination, = body['kombinasjonsbehandlinger']
        self.assertEqual([item['type'] for item in combination['medikamentelleBehandlinger']], ['BADEBEHANDLING'])
        self.assertEqual(combination['medikamentelleBehandlinger'][0]['virkestoff'], {
            'type': 'AZAMETHIPHOS', 'annetVirkestoff': None, 'styrke': {'verdi': 500, 'enhet': 'MILLIGRAM_PER_GRAM'},
            'mengde': {'verdi': 12.5, 'enhet': 'KILO'}})
        self.assertEqual([item['type'] for item in combination['ikkeMedikamentelleBehandlinger']],
                         ['MEKANISK_BEHANDLING'])
        self.assertEqual(body['resistensMistanker'], [{'resistens': 'ANNEN_RESISTENS', 'annenResistens': 'Ivermectin',
                                                      'årsak': 'BIOESSAY', 'annenÅrsak': None}])
        self.assertEqual(body['følsomhetsundersøkelser'][0]['utførtDato'], '2026-10-20T00:00:00Z')

    def test_the_row_lists_are_stored_read_edited_and_removed_through_the_pages(self):
        treatment = self.treat([self.m1, self.m2], day(10, 26), day(10, 26))
        url = reverse('reports:report_treatments', args=[self.report_.pk])
        self.client.post(url, {**rows_data('treatments', [
            {'treatment': str(treatment.pk), 'done_before_count': True, 'combination': ''}]),
                               'version': str(self.report_.version)})
        answer = TreatmentAnswer.objects.get()
        self.assertEqual((answer.treatment, answer.done_before_count, answer.combination, answer.created_by),
                         (treatment, True, None, self.user))
        form = self.client.get(reverse('reports:report_edit', args=[self.report_.pk]))
        self.assertContains(form, 'data-panel="treatments"')
        self.assertContains(form, 'treatment-answer-row')
        self.assertContains(form, 'data-panel="resistance"')
        version = str(Report.objects.get(pk=self.report_.pk).version)
        self.client.post(url, {**rows_data('treatments', [{
            'id': str(answer.pk), 'treatment': str(treatment.pk), 'done_before_count': False, 'combination': ''}],
                                           initial=1), 'version': version})
        self.assertEqual(list(TreatmentAnswer.objects.values_list('done_before_count', 'combination')),
                         [(False, None)])
        # A combination of one treatment is refused where it is entered.
        response = self.client.post(url, {**rows_data('treatments', [{
            'id': str(answer.pk), 'treatment': str(treatment.pk), 'done_before_count': False, 'combination': '3'}],
                                                       initial=1),
                                          'version': str(Report.objects.get(pk=self.report_.pk).version)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(TreatmentAnswer.objects.get().combination, None)
        version = str(Report.objects.get(pk=self.report_.pk).version)
        self.client.post(url, {**rows_data('treatments', [{'id': str(answer.pk), 'DELETE': True}], initial=1),
                               'version': version})
        self.assertFalse(TreatmentAnswer.objects.exists())

    def test_a_resistance_suspicion_is_stored_read_edited_and_removed_through_its_page(self):
        url = reverse('reports:report_resistance', args=[self.report_.pk])

        def version():
            return str(Report.objects.get(pk=self.report_.pk).version)
        row = {'substance': 'AZAMETHIPHOS', 'other_substance': '', 'cause': 'BIOESSAY', 'other_cause': ''}
        self.client.post(url, {**rows_data('resistance', [row]), 'version': version()})
        suspicion = ResistanceSuspicion.objects.get()
        self.assertEqual((suspicion.report, suspicion.substance, suspicion.cause, suspicion.other_substance,
                          suspicion.created_by), (self.report_, 'AZAMETHIPHOS', 'BIOESSAY', '', self.user))
        form = self.client.get(reverse('reports:report_edit', args=[self.report_.pk]))
        self.assertContains(form, 'data-panel="resistance"')
        self.assertContains(form, 'value="AZAMETHIPHOS" selected')
        # Another substance or reason is named where it is entered, and only then.
        other = {'id': str(suspicion.pk), **row, 'substance': 'ANNEN_RESISTENS'}
        response = self.client.post(url, {**rows_data('resistance', [other], initial=1), 'version': version()})
        self.assertEqual((response.status_code, ResistanceSuspicion.objects.get().substance), (200, 'AZAMETHIPHOS'))
        other.update(other_substance='Ivermectin', cause='ANNEN_ÅRSAK', other_cause='Seen in the area')
        self.client.post(url, {**rows_data('resistance', [other], initial=1), 'version': version()})
        suspicion = ResistanceSuspicion.objects.get()           # a list is saved as a whole: its rows are new rows
        self.assertEqual((suspicion.substance, suspicion.other_substance, suspicion.cause, suspicion.other_cause),
                         ('ANNEN_RESISTENS', 'Ivermectin', 'ANNEN_ÅRSAK', 'Seen in the area'))
        self.client.post(url, {**rows_data('resistance', [{'id': str(suspicion.pk), 'DELETE': True}], initial=1),
                               'version': version()})
        self.assertFalse(ResistanceSuspicion.objects.exists())

    def test_a_sensitivity_test_is_read_edited_and_removed_through_its_page(self):
        url = reverse('reports:report_sensitivity', args=[self.report_.pk])

        def version():
            return str(Report.objects.get(pk=self.report_.pk).version)
        row = {'tested_on': '2026-10-20', 'laboratory': 'FiskLab', 'substance': 'DELTAMETHRIN', 'other_substance': '',
               'result': 'FØLSOM'}
        self.client.post(url, {**rows_data('sensitivity', [row]), 'version': version()})
        test = SensitivityTest.objects.get()
        self.assertEqual((test.tested_on, test.laboratory, test.substance, test.result, test.created_by),
                         (day(10, 20), 'FiskLab', 'DELTAMETHRIN', 'FØLSOM', self.user))
        self.assertContains(self.client.get(reverse('reports:report_edit', args=[self.report_.pk])),
                            'data-panel="sensitivity"')
        row.update(id=str(test.pk), result='RESISTENS', laboratory='Another lab')
        self.client.post(url, {**rows_data('sensitivity', [row], initial=1), 'version': version()})
        test = SensitivityTest.objects.get()                     # a list is saved as a whole: its rows are new rows
        self.assertEqual((test.result, test.laboratory), ('RESISTENS', 'Another lab'))
        # A test cannot be of a day to come.
        row.update(id=str(test.pk), tested_on='2099-01-01')
        response = self.client.post(url, {**rows_data('sensitivity', [row], initial=1), 'version': version()})
        self.assertEqual((response.status_code, SensitivityTest.objects.get().tested_on), (200, day(10, 20)))
        self.client.post(url, {**rows_data('sensitivity', [{'id': str(test.pk), 'DELETE': True}], initial=1),
                               'version': version()})
        self.assertFalse(SensitivityTest.objects.exists())

    def test_a_treatment_of_another_week_is_not_offered(self):
        other = self.treat([self.m1, self.m2], day(10, 12), day(10, 12))
        url = reverse('reports:report_treatments', args=[self.report_.pk])
        response = self.client.post(url, {**rows_data('treatments', [{'treatment': str(other.pk)}]),
                                          'version': str(self.report_.version)})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(TreatmentAnswer.objects.exists())

    def test_the_sensitivity_test_of_another_substance_says_which(self):
        url = reverse('reports:report_sensitivity', args=[self.report_.pk])
        rows = [{'tested_on': '2026-10-20', 'laboratory': 'FiskLab', 'substance': 'ANNEN_RESISTENS',
                 'other_substance': '', 'result': 'FØLSOM'}]
        response = self.client.post(url, {**rows_data('sensitivity', rows), 'version': str(self.report_.version)})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SensitivityTest.objects.exists())
        rows[0]['other_substance'] = 'Ivermectin'
        self.client.post(url, {**rows_data('sensitivity', rows), 'version': str(self.report_.version)})
        self.assertEqual(SensitivityTest.objects.get().other_substance, 'Ivermectin')

    def test_the_csv_of_the_week_is_in_the_apis_field_names(self):
        self.treat([self.m1, self.m2], day(10, 26), day(10, 26))
        with temperature(WARM):
            response = self.client.get(reverse('reports:report_export', args=[self.report_.pk, 'csv']))
        self.assertContains(response, 'rapporteringsuke,,44')
        self.assertContains(response, 'lusetelling,voksneHunnlus,0.2')
        self.assertContains(response, 'medikamentelleBehandlinger,[0].virkestoff.type,AZAMETHIPHOS')
