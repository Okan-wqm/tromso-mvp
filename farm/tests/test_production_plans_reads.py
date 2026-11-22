"""The Production plans page reads every row's medicine withdrawal, earliest suitable harvest date and last feeding for
all its rows at once (farm/resources/harvest_plan.py): `check.holding_of`, `check.earliest_of`,
`feeding.read.handled_of` and `feeding.read.last_fed_in`. They must say for every unit and batch exactly what the one-at-a-time reads say (the
dialogs, the harvest plan), on sites of different clocks, with fish moved beside held fish (S-02), cleaner fish held
apart (F-05) and a purge in degree-days; and the page's queries must not grow with its rows."""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .. import withdrawal_gate
from ..feeding import read as feeding_read
from ..handling import check
from ..health import services as health_services
from ..models import (
    HandlingRule, Medicine, MedicineWithdrawal, ProductionDepartment, ProductionPlan, Site, Tank, WaterMeasurement,
)
from ..models.site import zone_of
from ..stock import read as stock_read
from ..stock.dates import local_today
from .helpers import point_of, role
from .test_feeding import FeedingTestCase
from .test_harvest import HARVEST_KEEPER
from .test_stock import make_unit
from .test_withdrawal_cleaner_fish import CleanerWithdrawalTestCase


class Fixtures:
    def medicine(self, name, degree_days=None, days=None):
        medicine = Medicine.objects.create(name=name, kind='lice', administration='bath', active_substance='x',
                                           lice_report_code='AZAMETHIPHOS')
        with withdrawal_gate.opened('test fixture: a withdrawal row straight in the database'):
            MedicineWithdrawal.objects.create(medicine=medicine, species=None, degree_days=degree_days, days=days,
                                              safety_margin_pct=0, note='')
        return medicine

    def treat(self, medicine, units, days_ago):
        return health_services.record_treatment(self.user, units=units, method='bath', reason='sea_lice',
                                                start_date=self.day(days_ago), end_date=self.day(days_ago),
                                                medicine=medicine)

    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def warm(self, unit, *days_ago, value='10'):
        site = unit.production_department.site
        for each in days_ago:
            moment = datetime.combine(local_today(unit) - timedelta(days=each), time(12), tzinfo=zone_of(site))
            WaterMeasurement.objects.create(point=point_of(unit), measured_at=moment, source='manual',
                                            temperature_c=Decimal(value), created_by=self.user)

    def purge(self, hours, degrees):
        HandlingRule.objects.filter(kind='harvest', species=None).delete()
        HandlingRule.objects.create(kind='harvest', species=None, min_fasting_hours=hours,
                                    min_fasting_degree_days=degrees)


class SetReadsTests(Fixtures, CleanerWithdrawalTestCase):
    """C-01: untreated salmon and lumpfish, with bathed salmon and bathed lumpfish moved in beside them (held by S-02;
    the lumpfish held apart). C-02: what is left of the bathed fish. T-01: salmon in a degree-day withdrawal. K-01 on
    Tokyo's clock: salmon in a degree-day withdrawal too. T-02: salmon never treated. A harvest asks for 72 h and 30
    degree-days, so the purge reads the last feeding and the water of every unit."""

    def setUp(self):
        super().setUp()
        self.join(self.bathed_salmon, 100)
        self.join(self.bathed_lump, 100)
        tokyo = Site.objects.create(name='Tokyo', code='TK', timezone='Asia/Tokyo')
        self.k1 = make_unit('K-01', ProductionDepartment.objects.create(site=tokyo, name='Hall T', code='HT'))
        self.tokyo_batch = self.stock(self.k1, count=800, weight='200', days_ago=12)
        self.t2_batch = self.stock(self.t2, count=600, weight='90', days_ago=15)
        slow = self.medicine('Slow vet.', degree_days=150)
        self.treat(slow, [self.t1], 6)
        self.treat(slow, [self.k1], 4)
        self.purge(72, Decimal(30))
        for unit, days_ago in ((self.t1, 1), (self.t2, 5), (self.cage, 2), (self.cage2, 7), (self.k1, 3)):
            self.record(kilos='0.2', unit=unit, days_ago=days_ago, time=time(18))
        self.warm(self.t1, 1, 2, 3, 5, 8)
        self.warm(self.cage, 1, 2, value='6')
        self.warm(self.k1, 2, 3, 4, value='12')
        self.units = list(Tank.objects.select_related('production_department__site').order_by('code'))
        self.stock_now = stock_read.stock_of(self.units)
        self.pairs = [(item.unit, share.batch) for item in self.stock_now.values() for share in item.counted]

    def test_the_scenario_has_every_case(self):
        found = check.earliest_of(self.pairs)
        self.assertEqual({each.decides for each in found.values()}, {'withdrawal', 'purging'})
        holding = check.holding_of(self.units)
        self.assertIn(self.bathed_salmon, [block.batch for block in holding[self.cage.pk]])       # S-02
        self.assertNotIn(self.bathed_lump, [block.batch for block in holding[self.cage.pk]])      # F-05: held apart
        self.assertIn(self.bathed_lump, [block.batch for block in check.in_force_of([self.cage])[self.cage.pk]])
        self.assertEqual(holding[self.t2.pk], [])

    def test_the_withdrawals_of_all_the_units_are_each_units_own(self):
        self.assertEqual(check.holding_of(self.units), {unit.pk: check.in_force(unit, local_today(unit))
                                                        for unit in self.units})
        day = self.day(-3)
        self.assertEqual(check.holding_of(self.units, day), {unit.pk: check.in_force(unit, day) for unit in self.units})

    def test_the_earliest_dates_of_all_the_rows_are_each_rows_own(self):
        for kind in ('harvest', 'transport'):
            for today in (None, self.day(-2)):
                with self.subTest(kind=kind, today=today):
                    self.assertEqual(check.earliest_of(self.pairs, today, kind),
                                     {(unit.pk, batch.pk): check.earliest(unit, batch, today, kind)
                                      for unit, batch in self.pairs})
        holding = check.holding_of(self.units)
        self.assertEqual(check.earliest_of(self.pairs, holding=holding), check.earliest_of(self.pairs))

    def test_the_batches_handled_and_the_last_feedings_of_all_the_units_are_each_units_own(self):
        asked = [(unit, local_today(unit)) for unit in self.units] + [(self.cage, self.day(2))]
        self.assertEqual(feeding_read.handled_of(asked),
                         {(unit.pk, day): feeding_read.handled(unit, day) for unit, day in asked})
        figures = feeding_read.figures(self.stock_now)
        self.assertEqual({unit_id: fed.record.date if fed else None
                          for unit_id, fed in feeding_read.last_fed_in(self.stock_now).items()},
                         {unit_id: each.last_fed for unit_id, each in figures.items()})

    def test_the_page_shows_each_rows_own(self):
        rows = [row for row in self.client.get(reverse('farm:productionplan_list')).context['objects'] if row['share']]
        self.assertEqual(len(rows), len(self.pairs))
        for row in rows:
            unit, batch = row['unit'], row['share'].batch
            with self.subTest(unit=unit.code, batch=batch.code):
                self.assertEqual(row['withdrawal'], check.in_force(unit, local_today(unit)))
                self.assertEqual(row['earliest'], check.earliest(unit, batch))
                fed = feeding_read.figures(stock_read.stock_of([unit]))[unit.pk].last_fed
                self.assertEqual(row['last_fed'], fed)


class BudgetTests(Fixtures, FeedingTestCase):
    """The page's queries do not grow with its rows: every unit stocked, fed, measured, held by a degree-day withdrawal
    and with a target, so each row reads every part (the withdrawal, the purge in degree-days, the last feeding, the
    forecast)."""

    CEILING = 90          # held since 2026-11-22 (equal at 3 and 9 units, asserted); never raised without a review

    def setUp(self):
        super().setUp()
        self.user.groups.add(role('Harvest keeper', *HARVEST_KEEPER))
        self.purge(72, Decimal(30))
        self.slow = self.medicine('Slow vet.', degree_days=150)

    def farm_of(self, count):
        units = [make_unit(f'B-{len(self.made) + n:02d}', self.hall) for n in range(count)]
        self.made += units
        for unit in units:
            batch = self.stock(unit, count=500, weight='100', days_ago=12)
            ProductionPlan.objects.create(batch=batch, target_weight_g=Decimal(4000))
            self.record(kilos='0.2', unit=unit, days_ago=2, time=time(18))
            self.warm(unit, 1, 2, 3)
        self.treat(self.slow, units, 5)

    def count(self):
        with CaptureQueriesContext(connection) as log:
            response = self.client.get(reverse('farm:productionplan_list'))
        self.assertEqual(response.status_code, 200)
        return len(log), len(response.context['objects'])

    def test_the_queries_are_the_same_at_three_and_at_nine_units(self):
        self.made = []
        self.farm_of(3)
        self.count()                                    # warm what the first request loads once
        small, rows = self.count()
        self.farm_of(6)
        large, more = self.count()
        self.assertEqual(more - rows, 6)
        self.assertEqual(small, large)
        self.assertLessEqual(large, self.CEILING, f'the page costs {large} queries')
        # Every row of the units made is held (its earliest date read the withdrawal, its last feeding and the water).
        made = {unit.pk for unit in self.made}
        decides = {row['earliest'].decides for row in self.client.get(reverse('farm:productionplan_list'))
                   .context['objects'] if row['share'] and row['unit'].pk in made}
        self.assertEqual(decides, {'withdrawal'})
