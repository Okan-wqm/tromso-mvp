"""Each report's figures against the records they are read from (reports/compute), and the periods and deadlines
they are owed for (reports/periods.py)."""
from datetime import date, datetime
from decimal import Decimal

from django.test import SimpleTestCase

from farm.feeding import services as feeding_services
from farm.models import (
    Batch, Feed, FeedingProtocol, FeedingRecord, HandlingPlanItem, HandlingRule, ProtocolAssignment, ProtocolBand,
    Supplier,
)
from farm.models.handling import HandlingKind
from farm.stock import services
from farm.tests.helpers import make_species

from .. import compute, periods
from ..compute import biomass
from ..models import Report, UnitAnswer
from ..periods import MONTH, WEEK, YEAR, Period
from .helpers import OCTOBER, WEEK_47, ReportTestCase, day


class PeriodTests(SimpleTestCase):
    def test_weeks_months_and_years_with_their_ends_keys_and_deadlines(self):
        week = Period.of(WEEK, date(2026, 11, 3))
        self.assertEqual((week.start, week.end, week.key, week.iso), (date(2026, 11, 2), date(2026, 11, 8), '2026-W45',
                                                                      (2026, 45)))
        self.assertEqual(periods.tuesday_after(week), date(2026, 11, 10))           # lakselusforskriften § 10
        self.assertEqual(periods.thursday_before(week), date(2026, 10, 29))         # restkontrollforskriften § 9a
        month = Period.of(MONTH, date(2026, 2, 14))
        self.assertEqual((month.start, month.end, month.key), (date(2026, 2, 1), date(2026, 2, 28), '2026-02'))
        self.assertEqual(periods.seventh_after(month), date(2026, 3, 7))            # § 44, § 58
        year = Period.of(YEAR, date(2026, 6, 1))
        self.assertEqual((year.end, periods.seventh_after(year)), (date(2026, 12, 31), date(2027, 1, 7)))  # § 44a
        for key in ('2026-W45', '2026-02', '2026'):
            self.assertEqual(Period.from_key(key).key, key)

    def test_the_iso_week_numbering_year_at_the_edge(self):
        # 28 December 2026 to 3 January 2027 is 2026-W53 (2026 has 53 ISO weeks); 1 January 2027 falls in it.
        week = Period.of(WEEK, date(2027, 1, 1))
        self.assertEqual((week.start, week.key, week.next.key), (date(2026, 12, 28), '2026-W53', '2027-W01'))
        self.assertEqual(Period.from_key('2026-W53').end, date(2027, 1, 3))
        self.assertEqual([period.key for period in periods.periods_between(WEEK, date(2026, 12, 20), date(2027, 1, 5))],
                         ['2026-W51', '2026-W52', '2026-W53', '2027-W01'])

    def test_a_period_must_start_where_its_grain_starts(self):
        for grain, start in ((WEEK, date(2026, 11, 3)), (MONTH, date(2026, 11, 2)), (YEAR, date(2026, 2, 1))):
            with self.assertRaises(ValueError):
                Period(grain, start)

    def test_today_is_the_day_in_oslo(self):
        self.assertEqual(periods.oslo_today(datetime(2026, 11, 3, 23, 30, tzinfo=periods.OSLO)), date(2026, 11, 3))
        utc_evening = datetime.fromisoformat('2026-11-03T23:30:00+00:00')         # 00:30 on the 4th in Oslo
        self.assertEqual(periods.oslo_today(utc_evening), date(2026, 11, 4))


class ArchitectureTests(SimpleTestCase):
    """The reports read the farm through the farm's own reads, and the farm never reads the reports."""

    def sources(self, root, skip=('tests', 'migrations', '__pycache__')):
        return {path.relative_to(root).as_posix(): path.read_text(encoding='utf-8') for path in root.rglob('*.py')
                if not set(skip) & set(path.relative_to(root).parts)}

    def test_the_reports_read_no_water_sample_but_through_the_water_modules_read(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        self.assertEqual([name for name, text in self.sources(root).items() if 'WaterMeasurement' in text], [])

    def test_the_farm_does_not_import_the_reports(self):
        from pathlib import Path
        farm = Path(__file__).resolve().parents[2] / 'farm'
        self.assertEqual([name for name, text in self.sources(farm).items()
                          if 'from reports' in text or 'import reports' in text], [])


class SmoltTests(ReportTestCase):
    def test_the_month_per_unit_from_the_ledger(self):
        self.october()
        result = compute.compute(self.report(Report.Kind.SMOLT, OCTOBER))
        units = {row['number']: {key: value for key, value in row.items() if key != 'lines'}
                 for row in result.content['units'].values()}
        self.assertEqual(units, {
            # 5,000 − 100 dead − 50 culled − 1,000 moved within the site; weighed at 5 g.
            'K-01': {'number': 'K-01', 'species': 'SAL', 'fish_at_end': 3850, 'avg_weight_g': '5.00', 'culled': 50,
                     'died': 100, 'moved_out_of_site': 0},
            # 1,000 in at 2 g from K-01 (an internal move, not reported), 500 out to the sea site.
            'K-02': {'number': 'K-02', 'species': 'SAL', 'fish_at_end': 500, 'avg_weight_g': '2.00', 'culled': 0,
                     'died': 0, 'moved_out_of_site': 500},
            # Emptied on 25 October: the fish and the average just before (D-8).
            'K-03': {'number': 'K-03', 'species': 'SAL', 'fish_at_end': 800, 'avg_weight_g': '3.00', 'culled': 0,
                     'died': 0, 'moved_out_of_site': 800},
        })
        self.assertEqual(result.problems, [])
        self.assertEqual(len([text for text in result.warnings if 'K-03 was emptied' in text]), 1)
        self.assertEqual(result.content['identity'], {'organisation_number': '987654321', 'lokalitetsnummer': 12345,
                                                      'site': 'Hatchery', 'site_code': 'HA'})

    def test_a_unit_emptied_by_moving_its_fish_within_the_site_does_not_count_them_twice(self):
        batch = self.stock(self.k1, 3850, '5', day(10, 2))
        services.record_transfer(self.user, source=self.k1, batch=batch, day=day(10, 30), legs=[(self.k3, 3850)],
                                 reason='density')
        result = compute.compute(self.report(Report.Kind.SMOLT, OCTOBER))
        rows = {row['number']: row for row in result.content['units'].values()}
        self.assertEqual((rows['K-01']['fish_at_end'], rows['K-01']['avg_weight_g'], rows['K-03']['fish_at_end']),
                         (0, '5.00', 3850))                       # the average just before, the fish in K-03 only
        self.assertEqual(sum(row['fish_at_end'] for row in rows.values()), 3850)
        self.assertEqual(result.problems, [])
        self.assertIn('3850 of the fish of K-01 were moved on 2026-10-30 to other units of the site: they are in '
                      'those units’ counts, not in this one’s (its average weight is the one just before).',
                      result.warnings)

    def test_only_the_fish_the_emptying_operation_moved_within_the_site_are_left_out(self):
        batch = self.stock(self.k1, 3850, '5', day(10, 2))
        services.record_transfer(self.user, source=self.k1, batch=batch, day=day(10, 30), legs=[(self.k3, 1000)],
                                 reason='density')
        services.record_cull(self.user, unit=self.k1, batch=batch, day=day(10, 30), count=2850, reason='small_size')
        rows = {row['number']: row for row in compute.compute(self.report(Report.Kind.SMOLT, OCTOBER)).content[
            'units'].values()}
        # The cull emptied K-01 (2,850 fish just before); the 1,000 moved earlier that day are in K-03's count.
        self.assertEqual((rows['K-01']['fish_at_end'], rows['K-01']['culled'], rows['K-03']['fish_at_end']),
                         (2850, 2850, 1000))

    def test_a_unit_that_held_two_species_one_after_the_other_is_listed_once_for_each(self):
        trout = make_species('TRR', 'Rainbow trout', 'Oncorhynchus mykiss', local_name='Regnbueørret',
                             official_code='TRR')
        operation = services.record_input(self.user, species=trout, input_stage='smolt', origin='own_hatchery',
                                          day=day(10, 1), lines=[(self.k1, 1000, Decimal(40))])
        services.record_delivery(self.user, unit=self.k1, batch=operation.movements.get().batch, day=day(10, 10),
                                 count=1000, destination='Buyer AS')
        self.stock(self.k1, 500, '2', day(10, 12))
        result = compute.compute(self.report(Report.Kind.SMOLT, OCTOBER))
        rows = {key.split('/')[1]: row for key, row in result.content['units'].items()}
        self.assertEqual({code: (row['fish_at_end'], row['avg_weight_g'], row['moved_out_of_site'])
                          for code, row in rows.items()},
                         {'TRR': (1000, '40.00', 1000), 'SAL': (500, '2.00', 0)})   # each species' own fish
        self.assertEqual(result.problems, [])
        self.assertIn('K-01 held more than one species in the month and is listed once for each: confirm that '
                      'Mattilsynet takes one tank number twice.', result.warnings)

    def test_what_keeps_it_from_being_ready(self):
        self.october()
        self.salmon.official_code = ''
        self.salmon.save()
        self.hatchery.organisation_number = ''
        self.hatchery.save()
        report = self.report(Report.Kind.SMOLT, OCTOBER, contact_phone='')
        problems = compute.compute(report).problems
        self.assertEqual(problems, [
            'Atlantic salmon (SAL) has no official code (Setup › Reference data › Species).',   # once, not per unit
            'Hatchery (HA) has no organisation number (Facility › Sites, its Reports tab).',
            'Give the contact person’s name, e-mail and telephone (the Contact person tab).'])

    def test_a_month_without_fish_has_nothing_to_file(self):
        result = compute.compute(self.report(Report.Kind.SMOLT, OCTOBER))
        self.assertEqual((result.content['units'], result.ready), ({}, False))


class BiomassTests(ReportTestCase):
    def test_the_sea_site_month_per_unit(self):
        self.october()
        feed = Feed.objects.create(name='Grower 2', code='GR-2', feed_type='grower')
        feeding_services.record_feeding(self.user, unit=self.m1, day=day(10, 28), feed=feed, amount_kg=Decimal('0.3'))
        report = self.report(Report.Kind.BIOMASS, OCTOBER, site=self.sea)
        UnitAnswer.objects.create(report=report, unit=self.m1, reduced_capacity=True)
        result = compute.compute(report)
        row, = result.content['units'].values()
        self.assertEqual((row['number'], row['reduced_capacity']), ('1', True))
        self.assertEqual(row['stocked'], [
            {'species': 'SAL', 'year_class': None, 'fish': 500, 'from_lokalitetsnummer': 12345},
            {'species': 'SAL', 'year_class': None, 'fish': 800, 'from_lokalitetsnummer': 12345}])
        stock = {item['fish']: item for item in row['stock']}
        # 500 of the first batch at 2 g, last measured at their stocking on 20 September: older than 30 days, and the
        # projection has a feeding day without a feeding table (no protocol): the book, marked stale (D-7).
        self.assertEqual((stock[500]['biomass_kg'], stock[500]['basis']['method'], stock[500]['basis']['measured_on']),
                         ('1.0', biomass.STALE, '2026-09-20'))
        self.assertIn('A batch’s biomass is its last measured average from 2026-09-20: no weighing in the 30 days '
                      'before the month’s end, and the projection has feeding days without a feeding table.',
                      result.warnings)
        # 800 stocked on 20 October: weighed within 30 days, the book.
        self.assertEqual((stock[800]['biomass_kg'], stock[800]['basis']), ('2.4', {'method': biomass.BOOK,
                                                                               'measured_on': '2026-10-20'}))
        self.assertEqual(row['feed'], [{'feed': 'Grower 2', 'feed_type': 'grower', 'kg': '0.3'}])
        self.assertEqual((row['harvested'], row['moved_out'], row['losses']), ([], [], []))
        # Year class is entered per batch (D-14); until it is, the report is not ready.
        self.assertEqual([text for text in result.problems if 'year class' in text],
                         [f'Batch {self.first.code} has no year class (Operations › Production units).',
                          f'Batch {self.second.code} has no year class (Operations › Production units).'])

    def test_a_projection_is_the_basis_only_when_feed_was_credited_since_the_last_measured_point(self):
        batch = self.stock(self.m1, 2000, '100', day(9, 1))                  # 200 kg, not weighed since
        report = self.report(Report.Kind.BIOMASS, OCTOBER, site=self.sea)

        def figure():
            result = compute.compute(report)
            row, = result.content['units'].values()
            return next(item for item in row['stock'] if item['fish'] == 2000), result.warnings
        # Nothing fed since the stocking: the figure is a 60-day-old measurement and says so, never a projection.
        item, warnings = figure()
        self.assertEqual((item['biomass_kg'], item['basis']), ('200.0', {'method': biomass.STALE,
                                                                       'measured_on': '2026-09-01'}))
        self.assertIn('A batch’s biomass is its last measured average from 2026-09-01: no weighing in the 30 days '
                      'before the month’s end, and no feeding with a feeding table was recorded since to project it '
                      'from.', warnings)
        # Fed to a feeding table with an expected FCR of 1: 75 kg of feed is 75 kg of growth.
        feed = Feed.objects.create(name='Grower', code='GR-1', feed_type='grower')
        protocol = FeedingProtocol.objects.create(name='P', species=self.salmon, expected_fcr=Decimal('1.00'),
                                                  status='active')
        ProtocolBand.objects.create(protocol=protocol, min_weight_g=Decimal(0), max_weight_g=None, feed=feed,
                                    meals_per_day=4, expected_fcr=Decimal('1.00'))
        ProtocolAssignment.objects.create(protocol=protocol, batch=batch, valid_from=day(9, 1))
        for number in range(21, 26):
            feeding_services.record_feeding(self.user, unit=self.m1, day=day(10, number), feed=feed,
                                            amount_kg=Decimal(15))
        item, warnings = figure()
        self.assertEqual((item['biomass_kg'], item['basis']), ('275.0', {
            'method': biomass.PROJECTED, 'measured_on': '2026-09-01', 'measured_avg_g': '100.00'}))
        self.assertFalse([text for text in warnings if 'last measured average' in text])

    def test_losses_harvest_and_the_fallow_day(self):
        batch = self.stock(self.m1, 1000, '500', day(10, 1))
        services.record_mortality(self.user, unit=self.m1, batch=batch, day=day(10, 3), count=10, cause='disease',
                                  measured_weight_kg=Decimal(4))
        services.record_cull(self.user, unit=self.m1, batch=batch, day=day(10, 4), count=5, reason='deformed')
        services.record_harvest(self.user, unit=self.m1, batch=batch, day=day(10, 20), count=980,
                                measured_weight_kg=Decimal(490), facility=self.facility, everything=True)
        Batch.all_objects.update(year_class=2026)
        report = self.report(Report.Kind.BIOMASS, OCTOBER, site=self.sea)
        # The farm holds the round kilos weighed at harvest and nothing else: the condition is theirs, never asked
        # (F-086: a person's "gutted" put round kilos under a gutted label in a filing).
        result = compute.compute(report)
        self.assertEqual(result.problems, [])
        row, = result.content['units'].values()
        self.assertEqual(row['losses'], [
            {'species': 'SAL', 'cause': 'dead', 'fish': 10, 'kg': '4.0'},
            {'species': 'SAL', 'cause': 'dead', 'fish': 5, 'kg': '2.5'},
            # The harvest that emptied the unit wrote the fish the book still held as an unaccounted loss.
            {'species': 'SAL', 'cause': 'other', 'fish': 5, 'kg': '2.5'}])
        self.assertEqual(row['harvested'], [{'species': 'SAL', 'fish': 980, 'slaughter_weight_kg': '490.0',
                                             'condition': 'round'}])
        self.assertEqual((row['stock'], result.content['fallow_since']), ([], '2026-10-20'))


class PlannedSlaughterTests(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.facility.operator = Supplier.objects.create(name='Fjord Slakteri AS', code='FSL', supplies=['slaughter'],
                                                         organisation_number='912345678')
        self.facility.save()

    def plan(self, on, kilos, unit=None, **fields):
        unit = unit or self.m1
        batch = getattr(self, 'planned_batch', None) or self.stock(unit, 1000, '4000', day(10, 1))
        self.planned_batch = batch
        return HandlingPlanItem.objects.create(kind=HandlingPlanItem.Kind.HARVEST, date=on, unit=unit, batch=batch,
                                               planned_kg=None if kilos is None else Decimal(kilos),
                                               facility=self.facility, created_by=self.user, **fields)

    def test_the_kilos_per_weekday_locality_and_species(self):
        self.plan(day(11, 16), '1200.4')
        self.plan(day(11, 16), '800')
        self.plan(day(11, 18), '1500.5')
        self.plan(day(11, 25), '9999')                                     # the next week
        self.plan(day(11, 17), '700', cancelled_reason='Weather')          # cancelled
        report = self.report(Report.Kind.SLAUGHTER_PLANNED, WEEK_47)
        result = compute.compute(report)
        locality, = result.content['localities'].values()
        self.assertEqual((locality['lokalitetsnummer'], locality['organisation_number']), (23456, '987654321'))
        self.assertEqual(locality['species'], {'SAL': {'monday': 2000, 'tuesday': None, 'wednesday': 1501,
                                                       'thursday': None, 'friday': None, 'saturday': None,
                                                       'sunday': None}})
        self.assertEqual(result.content['facility'], {'name': 'Fjord Slakteri', 'approval_number': 'M123',
                                                      'organisation_number': '912345678'})
        self.assertEqual(result.problems, [])

    def test_a_plan_without_kilos_keeps_it_from_being_ready(self):
        self.plan(day(11, 17), None, planned_count=100)
        problems = compute.compute(self.report(Report.Kind.SLAUGHTER_PLANNED, WEEK_47)).problems
        self.assertEqual(problems, ['The planned harvest of M-01 on 2026-11-17 has no planned kilos (Operations › '
                                    'Harvest › Harvest plan).'])

    def test_the_deadline_is_thursday_before_or_when_the_fish_start_fasting(self):
        self.plan(day(11, 16), '1000')
        report = self.report(Report.Kind.SLAUGHTER_PLANNED, WEEK_47)
        # The harvest rule of every species (72 h, Reference data › Handling rules) starts the fast on Friday 13:
        # Thursday 12 is earlier.
        self.assertEqual(compute.deadline(report), date(2026, 11, 12))
        HandlingRule.objects.create(kind=HandlingKind.HARVEST, species=self.salmon, min_fasting_hours=120)
        self.assertEqual(compute.deadline(report), date(2026, 11, 11))      # a fast from Wednesday 11 (§ 9a)


class FingerprintTests(ReportTestCase):
    def test_a_void_or_a_backdated_record_changes_it_and_nothing_else_does(self):
        self.october()
        report = self.report(Report.Kind.SMOLT, OCTOBER)
        before = compute.fingerprint(compute.compute(report).scope)
        self.assertEqual(compute.fingerprint(compute.compute(report).scope), before)
        services.void(self.user, self.out, 'Entered by mistake')
        voided = compute.fingerprint(compute.compute(report).scope)
        self.assertNotEqual(voided, before)
        services.record_mortality(self.user, unit=self.k1, batch=self.first, day=day(10, 30), count=1,
                                  cause='unknown')
        self.assertNotEqual(compute.fingerprint(compute.compute(report).scope), voided)

    def test_feedings_of_the_month_are_in_the_biomass_scope(self):
        self.october()
        report = self.report(Report.Kind.BIOMASS, OCTOBER, site=self.sea)
        before = compute.fingerprint(compute.compute(report).scope)
        feed = Feed.objects.create(name='Grower 2', code='GR-2', feed_type='grower')
        FeedingRecord.objects.create(unit=self.m1, date=day(10, 30), feed=feed, amount_kg=Decimal(1),
                                     created_by=self.user)
        self.assertNotEqual(compute.fingerprint(compute.compute(report).scope), before)
