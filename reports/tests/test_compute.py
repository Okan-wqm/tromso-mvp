"""Each report's figures against the records they are read from (reports/compute), and the periods and deadlines
they are owed for (reports/periods.py)."""
from datetime import date, datetime
from decimal import Decimal

from django.test import SimpleTestCase

from farm.feeding import services as feeding_services
from farm.models import Feed, FeedingRecord, HandlingPlanItem, HandlingRule
from farm.models.handling import HandlingKind
from farm.stock import services

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

    def test_what_keeps_it_from_being_ready(self):
        self.october()
        self.salmon.official_code = ''
        self.salmon.save()
        self.hatchery.organisation_number_override = '12345'
        self.hatchery.save()
        report = self.report(Report.Kind.SMOLT, OCTOBER, contact_phone='')
        problems = compute.compute(report).problems
        self.assertEqual(problems, [
            'Atlantic salmon (SAL) has no official code (Setup › Reference data › Species).',   # once, not per unit
            'Hatchery (HA) has no organisation number of 9 digits (Facility › Sites).',
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

    def test_fish_weighed_long_ago_without_a_blind_day_report_the_projection(self):
        self.october()
        result = compute.compute(self.report(Report.Kind.BIOMASS, OCTOBER, site=self.sea))
        row, = result.content['units'].values()
        first = next(item for item in row['stock'] if item['fish'] == 500)
        # No feeding since their stocking: the projection adds no growth, and it is the figure filed, with its basis.
        self.assertEqual((first['biomass_kg'], first['basis']), ('1.0', {
            'method': biomass.PROJECTED, 'measured_on': '2026-09-20', 'measured_avg_g': '2.00'}))

    def test_losses_harvest_and_the_fallow_day(self):
        batch = self.stock(self.m1, 1000, '500', day(10, 1))
        services.record_mortality(self.user, unit=self.m1, batch=batch, day=day(10, 3), count=10, cause='disease',
                                  measured_weight_kg=Decimal(4))
        services.record_cull(self.user, unit=self.m1, batch=batch, day=day(10, 4), count=5, reason='deformed')
        services.record_harvest(self.user, unit=self.m1, batch=batch, day=day(10, 20), count=980,
                                measured_weight_kg=Decimal(490), facility=self.facility, everything=True)
        result = compute.compute(self.report(Report.Kind.BIOMASS, OCTOBER, site=self.sea))
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
        self.assertEqual(result.content['facility'], {'name': 'Fjord Slakteri', 'approval_number': 'M123'})
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
