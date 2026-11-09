"""An opening balance (farm/stock/services.py record_opening_balance) in the reports: fish the farm already had when it
started using the platform, never fish stocked or a site taken into use; each report of its period says so."""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model

from farm.stock import services
from farm.tests.helpers import make_species, role

from .. import compute
from ..models import Report
from .helpers import OCTOBER, ReportTestCase, day

WARNING = ('3000 fish of {batch} in unit 1 were taken over on 2026-10-10 (an opening balance, from Count sheet 10 Oct): '
           'they are counted as stock the farm already had, not as fish stocked.')


class OpeningBalanceReportTests(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.owner = get_user_model().objects.create_user('eier', 'eier@example.com', 'x')
        self.owner.groups.add(role('Platform owner', 'change_platformsettings'))

    def take_over(self, unit, count, weight, on, species=None):
        operation = services.record_opening_balance(
            self.owner, species=species or self.salmon, input_stage='smolt', origin='own_hatchery',
            stocked_on=date(2025, 4, 1), day=on, year_class=2025, document='Count sheet 10 Oct',
            lines=[(unit, count, Decimal(weight))])
        return operation.movements.get().batch

    def test_the_biomass_report_counts_it_as_stock_never_as_fish_stocked(self):
        batch = self.take_over(self.m1, 3000, '400', day(10, 10))
        result = compute.compute(self.report(Report.Kind.BIOMASS, OCTOBER, site=self.sea))
        row, = result.content['units'].values()
        self.assertEqual(row['stocked'], [])
        self.assertEqual([(stock['fish'], stock['year_class']) for stock in row['stock']], [(3000, 2025)])
        self.assertIn(WARNING.format(batch=batch.code), result.warnings)

    def test_the_cleaner_fish_report_counts_it_in_the_months_opening_figure(self):
        lump = make_species('LUM', 'Lumpfish', 'Cyclopterus lumpus', local_name='Rognkjeks', freshwater=False,
                            official_code='LUM', cleaner_fish_type='lumpfish')
        batch = self.take_over(self.m1, 3000, '50', day(10, 10), species=lump)
        result = compute.compute(self.report(Report.Kind.CLEANER_FISH, OCTOBER, site=self.sea, no_cleaner_feed=True))
        row, = result.content['units'].values()
        figures, = row['species']
        self.assertEqual((figures['opening'], figures['stocked'], figures['closing']), (3000, 0, 3000))
        self.assertEqual(result.problems, [])
        self.assertIn(WARNING.format(batch=batch.code), result.warnings)

    def test_a_site_taken_over_is_not_taken_into_use_on_that_day(self):
        self.take_over(self.m1, 3000, '400', day(10, 10))
        result = compute.compute(self.report(Report.Kind.SITE_IN_USE, site=self.sea, occurred_on=day(10, 10)))
        self.assertIn('No fish arrived at the site on that day.', result.problems)

    def test_a_stocking_in_the_same_month_is_still_fish_stocked(self):
        self.take_over(self.m1, 3000, '400', day(10, 10))
        self.stock(self.m1, 500, '300', day(10, 12))
        result = compute.compute(self.report(Report.Kind.BIOMASS, OCTOBER, site=self.sea))
        row, = result.content['units'].values()
        self.assertEqual([stocked['fish'] for stocked in row['stocked']], [500])
