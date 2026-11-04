"""Live fish delivered out of the company in the reports (D-10): the smolt report's fish moved out of the site, the monthly
biomass report's fish moved to another site (with the receiving site's number), the cleaner-fish report's fish moved
out."""
from decimal import Decimal

from farm.stock import services
from farm.tests.helpers import make_species
from farm.tests.test_stock import make_unit

from .. import compute
from ..models import Report
from .helpers import OCTOBER, ReportTestCase, day


class DeliveryInTheReportsTests(ReportTestCase):
    def test_the_smolt_report_counts_the_fish_delivered_as_moved_out_of_the_site(self):
        self.october()
        services.record_delivery(self.user, unit=self.k1, batch=self.first, day=day(10, 22), count=300,
                                 destination='Nordic Smolt AS', destination_site_number=31234)
        result = compute.compute(self.report(Report.Kind.SMOLT, OCTOBER))
        unit = next(row for row in result.content['units'].values() if row['number'] == 'K-01')
        self.assertEqual((unit['moved_out_of_site'], unit['fish_at_end']), (300, 3850 - 300))
        self.assertEqual(result.problems, [])

    def test_the_biomass_report_names_the_receiving_site(self):
        batch = self.stock(self.m1, 1000, '300', day(9, 20))
        services.record_delivery(self.user, unit=self.m1, batch=batch, day=day(10, 10), count=100,
                                 destination='Nordic Farms', destination_site_number=31234,
                                 measured_weight_kg=Decimal('30.5'))
        services.record_delivery(self.user, unit=self.m1, batch=batch, day=day(10, 11), count=50,
                                 destination='A customer')
        result = compute.compute(self.report(Report.Kind.BIOMASS, OCTOBER, site=self.sea))
        row, = result.content['units'].values()
        self.assertEqual(row['moved_out'], [
            {'species': 'SAL', 'fish': 100, 'kg': '30.5', 'to_lokalitetsnummer': 31234},
            {'species': 'SAL', 'fish': 50, 'kg': '15.0', 'to_lokalitetsnummer': None}])

    def test_the_cleaner_fish_report_counts_the_fish_delivered_as_moved_out(self):
        make_unit('M-02', self.bay, regulatory_unit_id='2')
        lump = make_species('LUM', 'Lumpfish', 'Cyclopterus lumpus', local_name='Rognkjeks', freshwater=False,
                            official_code='LUM', cleaner_fish_type='lumpfish')
        self.stock(self.m1, 500, '100', day(9, 20))
        operation = services.record_input(self.user, species=lump, input_stage='fry', origin='own_hatchery',
                                          day=day(9, 20), lines=[(self.m1, 4000, Decimal(50))])
        batch = operation.movements.get().batch
        services.record_delivery(self.user, unit=self.m1, batch=batch, day=day(10, 14), count=1000,
                                 destination='Nordic Farms')
        result = compute.compute(self.report(Report.Kind.CLEANER_FISH, OCTOBER, site=self.sea, no_cleaner_feed=True))
        row, = result.content['units'].values()
        figures, = row['species']
        self.assertEqual((figures['moved_out'], figures['closing'], result.problems), (1000, 3000, []))
