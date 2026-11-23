"""The Production plans page reads every row's medicine withdrawal, earliest suitable harvest date and last feeding for
all its rows at once (farm/resources/harvest_plan.py): `check.holding_of`, `check.earliest_of`,
`feeding.read.handled_of` and `feeding.read.last_fed_in`. The one-at-a-time reads (`in_force`, `earliest`, `handled`)
are now their case of one, so they cannot be the oracle: a mistake in the set read would be in both. These tests
compare the set reads with MAIN'S READS AS THEY WERE before them (56b7ea0, copied verbatim below; they stand on the
reads the set reads did not change) and with fixed values, at five frozen moments: sites on UTC, Tokyo and Oslo clocks,
two of them on different dates, Oslo's midnight on both sides. The farm has fish moved beside held fish (S-02), cleaner
fish held apart (F-05) and moved beside the stock, a species' rule beside the default rule, feedings exactly 30 and 31
days old, a unit emptied on the day and one filled on it, and purges in degree-days; and the page's queries must not
grow with its rows (verification of wip/plans-perf, finding 1)."""
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.testing import FrozenClock

from .. import withdrawal_gate
from ..feeding import read as feeding_read
from ..feeding.services import record_feeding
from ..handling import check, fasting
from ..handling.fasting import DAY, LOOKBACK_DAYS
from ..health import services as health_services
from ..models import (
    HandlingRule, Medicine, MedicineWithdrawal, ProductionDepartment, ProductionPlan, Site, System, Tank,
    WaterMeasurement,
)
from ..models.site import zone_of
from ..stock import read as stock_read, services as stock_services
from ..stock.dates import local_today
from ..water.degree_days import BatchWater
from .helpers import going_on, point_of, role
from .test_feeding import FeedingTestCase
from .test_harvest import HARVEST_KEEPER
from .test_stock import make_unit
from .test_withdrawal_cleaner_fish import CleanerWithdrawalTestCase

UTC = dt_timezone.utc


# ---- main's reads at 56b7ea0, copied verbatim (renamed main_*, their module's names written with the module): the
# ---- oracle. farm/feeding/read.py `handled`, `last_fed_at` and the last feeding `figures` gave the page;
# ---- farm/handling/check.py `_in_force`, `in_force` and `earliest`.
def main_handled(unit, day):
    book = feeding_read.book_on(unit, day).production
    return set(book.start) | set(book.end)


def main_last_fed_at(unit, day, since=None):
    return feeding_read.last_fed_of([(unit, day, main_handled(unit, day), since)])[unit.pk]


def main_last_fed(stock):
    """{unit id: LastFed or None}: what main's `figures(stock)` gave each unit as its last feeding (the page showed its
    date): `last_fed_of` on the lines of the walk of the units' feedings."""
    if not stock:
        return {}
    unit_ids = list(stock)
    today = {unit_id: local_today(item.unit) for unit_id, item in stock.items()}
    since = min(item.since for item in stock.values())
    walked = feeding_read._walk(unit_ids, feeding_read.feedings(unit_ids, since), [])
    return feeding_read.last_fed_of(((item.unit, today[unit_id], [share.batch.pk for share in item.counted], None)
                                     for unit_id, item in stock.items()), lines=walked.lines)


def main__in_force(unit, day, named=None):
    found = check.in_force_of([unit], day)
    if found is None:
        return None
    holding, beside = [], []
    for block in found[unit.pk]:
        (beside if check.held_apart(block.batch, named) else holding).append(block)
    return holding, beside


def main_in_force(unit, day):
    found = main__in_force(unit, day)
    return None if found is None else found[0]


def main_earliest(unit, batch, today=None, kind=check.WITHDRAWAL_KIND):
    today = local_today(unit) if today is None else today
    blocks = main_in_force(unit, today) or []
    dated = [block for block in blocks if block.until is not None]
    unknown = len(dated) < len(blocks)
    latest = max(dated, key=lambda block: block.until, default=None)
    requirement = fasting.requirement_of(kind, batch.species)
    purge_day, degrees_unknown, water = None, False, None
    if requirement is not None and requirement.asks:
        fed = main_last_fed_at(unit, today, since=today - timedelta(days=LOOKBACK_DAYS))      # the unit's, not the batch's
        if fed is not None:
            if requirement.degree_days:
                water = BatchWater({batch.pk}, today, fed.record.date + DAY)
            day = today
            for _n in range(fasting.MAX_FAST_DAYS + 1):
                done = fasting.fasted(unit, day, fed, requirement, water, [batch.pk])
                if done.ok:
                    purge_day = day if day > today else None
                    break
                day += DAY
            else:
                degrees_unknown = True              # never complete within the days looked at: said as unknown
    if unknown:
        return check.Earliest(batch, None, check.WITHDRAWAL, latest.until if latest else None, unknown=True,
                              degrees_unknown=degrees_unknown, kind=kind)
    if latest is not None and (purge_day is None or latest.until >= purge_day):
        return check.Earliest(batch, latest.until, check.WITHDRAWAL, latest.until, latest.approximate,
                              degrees_unknown=degrees_unknown, kind=kind)
    if purge_day is not None:
        start = fasting.start_of_fast(unit, purge_day, requirement, water, batch.pk)
        stop_by = start.starts_at.date() - DAY if start.starts_at is not None else None
        return check.Earliest(batch, purge_day, check.PURGING, latest.until if latest else None,
                              latest.approximate if latest else False, stop_by=stop_by, degrees_unknown=degrees_unknown,
                              kind=kind)
    if degrees_unknown:                         # the purge cannot be worked out: not known, and said
        return check.Earliest(batch, None, check.PURGING, degrees_unknown=True, kind=kind)
    return check.Earliest(batch, today, '', kind=kind)


# ---- the farms -------------------------------------------------------------------------------------------------------
class Fixtures:
    def medicine(self, name, degree_days=None, days=None):
        medicine = Medicine.objects.create(name=name, kind='lice', administration='bath', active_substance='x',
                                           lice_report_code='AZAMETHIPHOS')
        with withdrawal_gate.opened('test fixture: a withdrawal row straight in the database'):
            MedicineWithdrawal.objects.create(medicine=medicine, species=None, degree_days=degree_days, days=days,
                                              safety_margin_pct=0, note='')
        return medicine

    def treat(self, medicine, units, days_ago):
        return going_on(health_services.record_treatment, self.user, units=units, method='bath', reason='sea_lice',
                        start_date=self.day(days_ago), end_date=self.day(days_ago), medicine=medicine)

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

    def fed_on(self, unit, days_ago, at=time(18)):
        """A feeding of the production fish `days_ago` days before the unit's own today (at `at` on its clock)."""
        return self.record(kilos='0.2', unit=unit, days_ago=(self.today - local_today(unit)).days + days_ago, time=at)

    def move(self, source, batch, days_ago, target, count):
        return going_on(stock_services.record_transfer, self.user, source=source, batch=batch, day=self.day(days_ago),
                        legs=[(target, count)], reason='density', ack=True, size_mix_ack=True)


class Scenario(Fixtures):
    """C-01: untreated salmon and lumpfish, with bathed salmon and bathed lumpfish moved in beside them 2 days ago (held
    by S-02; the lumpfish held apart). C-02: what is left of the bathed fish. C-03 / C-04: lumpfish moved from C-03 into
    C-04 yesterday, C-03 fed yesterday, C-04's salmon 5 days ago (the cleaner fish's path is not the salmon's last
    meal). T-01: salmon in a degree-day withdrawal. T-02: salmon never treated, fed today. T-03 / T-04: bathed salmon
    moved out of T-03 into the empty T-04 today (one unit emptied on the day, one filled). T-05 and R-01: salmon and
    trout fed at the same moment; the trout's own rule asks 24 h, the default 72 h and 30 degree-days. T-30 / T-31: fed
    exactly 30 and 31 days ago (31: the last day looked back to). K-01 (salmon in a degree-day withdrawal), K-02
    (trout) and K-03 (untreated salmon whose degree-days decide) on Tokyo's clock, O-01 (trout) on Oslo's. Water at
    T-01, C-01, T-05, K-01 and K-03 (none on K-03's yesterday or today)."""

    DAYS = None         # {'UTC': date, 'Tokyo': date, 'Oslo': date}: each site's today at the class's frozen moment

    def setUp(self):
        super().setUp()
        tokyo = Site.objects.create(name='Tokyo', code='TK', timezone='Asia/Tokyo')
        oslo = Site.objects.create(name='Oslo', code='OS', timezone='Europe/Oslo')
        tokyo_hall = ProductionDepartment.objects.create(site=tokyo, name='Hall T', code='HT')
        oslo_hall = ProductionDepartment.objects.create(site=oslo, name='Hall O', code='HO')
        cages = self.cage.production_department
        self.k1, self.k2, self.k3 = (make_unit(code, tokyo_hall) for code in ('K-01', 'K-02', 'K-03'))
        self.o1 = make_unit('O-01', oslo_hall)
        self.t3, self.t4, self.t5 = (make_unit(code, self.hall) for code in ('T-03', 'T-04', 'T-05'))
        self.t30, self.t31, self.r1 = (make_unit(code, self.hall) for code in ('T-30', 'T-31', 'R-01'))
        self.c3, self.c4 = make_unit('C-03', cages), make_unit('C-04', cages)
        # The fish.
        self.tokyo_batch = self.stock(self.k1, count=800, weight='200', days_ago=12)
        self.k3_batch = self.stock(self.k3, count=700, weight='180', days_ago=12)
        self.t2_batch = self.stock(self.t2, count=600, weight='90', days_ago=15)
        self.moved = self.stock(self.t3, count=400, weight='150', days_ago=12)
        self.t5_batch = self.stock(self.t5, count=500, weight='120', days_ago=12)
        self.fed30 = self.stock(self.t30, count=300, weight='300', days_ago=31)
        self.fed31 = self.stock(self.t31, count=300, weight='300', days_ago=31)
        self.trouts = {unit.pk: self.stock(unit, count=500, weight='80', days_ago=12, species=self.trout)
                       for unit in (self.r1, self.k2, self.o1)}
        self.c3_salmon = self.stock(self.c3, count=1000, weight='150', days_ago=10)
        self.c3_lump = self.stock(self.c3, count=2000, weight='40', days_ago=10, species=self.lump)
        self.c4_salmon = self.stock(self.c4, count=1000, weight='150', days_ago=10)
        # The moves and the treatments, before any feeding (a handling of fed fish asks about their fast).
        self.join(self.bathed_salmon, 100)
        self.join(self.bathed_lump, 100)
        self.move(self.t3, self.moved, 0, self.t4, 400)
        self.move(self.c3, self.c3_lump, 1, self.c4, 2000)
        slow = self.medicine('Slow vet.', degree_days=150)
        self.treat(slow, [self.t1], 6)
        self.treat(slow, [self.k1], 4)
        self.treat(self.medicine('Short vet.', days=5), [self.t3], 2)
        # The feedings: of the production fish, on each unit's own clock.
        for unit, days_ago in ((self.t1, 1), (self.t2, 5), (self.cage, 2), (self.cage2, 7), (self.t3, 3), (self.t5, 2),
                               (self.r1, 2), (self.k1, 3), (self.k2, 2), (self.k3, 2), (self.o1, 2), (self.c3, 1),
                               (self.c4, 5)):
            self.fed_on(unit, days_ago)
        self.fed_on(self.t2, 0, at=None)          # today, no time: the day's last meal
        self.fed_on(self.t30, 30, at=None)
        self.fed_on(self.t31, 31, at=None)
        # The rules and the water.
        self.purge(72, Decimal(30))
        HandlingRule.objects.create(kind='harvest', species=self.trout, min_fasting_hours=24,
                                    min_fasting_degree_days=None)
        self.warm(self.t1, 1, 2, 3, 5, 8)
        self.warm(self.cage, 1, 2, value='6')
        self.warm(self.k1, 3, 4, 5, value='12')
        self.warm(self.k3, 3, 4, 5, value='12')
        self.warm(self.t5, 1, 3, value='9')
        self.units = list(Tank.objects.select_related('production_department__site').order_by('code'))
        self.stock_now = stock_read.stock_of(self.units)
        self.pairs = [(item.unit, share.batch) for item in self.stock_now.values() for share in item.counted]
        # And pairs no row has: the fish of the unit emptied today (its dialog may still ask), cleaner fish.
        self.asked = self.pairs + [(self.t3, self.moved), (self.cage, self.lump_batch), (self.c4, self.c3_lump)]


class SetReads:
    """The tests of the Scenario, run at each moment of CLOCKS (the classes below)."""

    def test_the_days_and_the_answers_are_the_farms(self):
        self.assertEqual({'UTC': local_today(self.t1), 'Tokyo': local_today(self.k1), 'Oslo': local_today(self.o1)},
                         self.DAYS)
        utc, tokyo, oslo = self.DAYS['UTC'], self.DAYS['Tokyo'], self.DAYS['Oslo']
        found = check.earliest_of(self.asked)

        def of(unit, batch):
            return found[(unit.pk, batch.pk)]
        # The trout's own rule (24 h) is fasted, on each site's own today; the salmon fed at the same moment are not
        # (the default rule: 72 h and 30 degree-days).
        for unit, today in ((self.r1, utc), (self.k2, tokyo), (self.o1, oslo)):
            with self.subTest(unit=unit.code):
                self.assertEqual((of(unit, self.trouts[unit.pk]).day, of(unit, self.trouts[unit.pk]).decides),
                                 (today, ''))
        self.assertEqual(of(self.t5, self.t5_batch).decides, check.PURGING)
        # K-03's purge on Tokyo's own day: fed 2 days ago, its yesterday unmeasured counts 0 °C (a past day), today and
        # on at the projection, 12 °C: 0, 12, 24, 36 degree-days, so 3 days on. Read on another site's day (a day
        # behind), its yesterday would be projected too, and it would be 2.
        self.assertEqual((of(self.k3, self.k3_batch).day, of(self.k3, self.k3_batch).decides),
                         (tokyo + 3 * DAY, check.PURGING))
        # Fed 31 days ago, the last day looked back to, and 30: the purge counts from them, never "not fed".
        for unit, batch in ((self.t31, self.fed31), (self.t30, self.fed30)):
            with self.subTest(unit=unit.code):
                self.assertEqual((of(unit, batch).day, of(unit, batch).decides), (None, check.PURGING))
        # The bathed fish moved into the empty T-04 today bring their withdrawal (S-02).
        self.assertEqual(of(self.t4, self.moved).decides, check.WITHDRAWAL)
        # The last feedings: T-02 today; T-04 never fed, its fish last in T-03 3 days ago (their path, S-01); C-04's
        # salmon 5 days ago, not the lumpfish's meal in C-03 yesterday.
        last = feeding_read.last_fed_in(self.stock_now)
        self.assertEqual({unit.code: last[unit.pk].record.date for unit in (self.t2, self.t4, self.c4)},
                         {'T-02': utc, 'T-04': utc - 3 * DAY, 'C-04': utc - 5 * DAY})
        # The batches a handling takes: at the start of the day or at its end, never the cleaner fish.
        handled = feeding_read.handled_of([(self.t3, utc), (self.t4, utc), (self.t4, utc - DAY),
                                           (self.cage, utc - 2 * DAY), (self.cage, utc - 3 * DAY)])
        self.assertEqual(handled, {(self.t3.pk, utc): {self.moved.pk},                 # emptied on the day
                                   (self.t4.pk, utc): {self.moved.pk},                 # filled on the day
                                   (self.t4.pk, utc - DAY): set(),
                                   (self.cage.pk, utc - 2 * DAY): {self.salmon_batch.pk, self.bathed_salmon.pk},
                                   (self.cage.pk, utc - 3 * DAY): {self.salmon_batch.pk}})
        # C-02's bath holds it today and no longer 6 days on (the harvest is allowed from 5 days on).
        self.assertTrue(check.holding_of(self.units)[self.cage2.pk])
        self.assertEqual(check.holding_of(self.units, utc + 6 * DAY)[self.cage2.pk], [])

    def test_the_set_reads_say_what_mains_reads_said(self):
        for day in (None, self.day(3), self.day(-6)):
            with self.subTest(read='holding_of', day=day):
                self.assertEqual(check.holding_of(self.units, day),
                                 {unit.pk: main_in_force(unit, day or local_today(unit)) for unit in self.units})
        asked = [(unit, local_today(unit) - n * DAY) for unit in self.units for n in (0, 1, 2, 3)]
        self.assertEqual(feeding_read.handled_of(asked),
                         {(unit.pk, day): main_handled(unit, day) for unit, day in asked})
        self.assertEqual(feeding_read.last_fed_in(self.stock_now), main_last_fed(self.stock_now))
        for kind in (check.WITHDRAWAL_KIND, 'transport'):
            for today in (None, self.day(2), self.day(-2)):
                with self.subTest(read='earliest_of', kind=kind, today=today):
                    expected = {(unit.pk, batch.pk): main_earliest(unit, batch, today, kind)
                                for unit, batch in self.asked}
                    self.assertEqual(check.earliest_of(self.asked, today, kind), expected)
                    self.assertEqual({(unit.pk, batch.pk): check.earliest(unit, batch, today, kind)
                                      for unit, batch in self.asked}, expected)
        self.assertEqual(check.earliest_of(self.asked, holding=check.holding_of(self.units)),
                         {(unit.pk, batch.pk): main_earliest(unit, batch) for unit, batch in self.asked})

    def test_the_page_shows_what_main_showed(self):
        rows = [row for row in self.client.get(reverse('farm:productionplan_list')).context['objects'] if row['share']]
        self.assertEqual(len(rows), len(self.pairs))
        last = main_last_fed(self.stock_now)
        for row in rows:
            unit, batch = row['unit'], row['share'].batch
            with self.subTest(unit=unit.code, batch=batch.code):
                self.assertEqual(row['withdrawal'], main_in_force(unit, local_today(unit)))
                self.assertEqual(row['earliest'], main_earliest(unit, batch))
                self.assertEqual(row['last_fed'], last[unit.pk].record.date if last[unit.pk] else None)


# The moments the Scenario is read at, and each site's today then (Tokyo UTC+9, Oslo UTC+1 in November).
D22, D23 = date(2026, 11, 22), date(2026, 11, 23)
CLOCKS = {
    'Morning': (datetime(2026, 11, 22, 10, 30, tzinfo=UTC), {'UTC': D22, 'Tokyo': D22, 'Oslo': D22}),
    'Evening': (datetime(2026, 11, 22, 18, 30, tzinfo=UTC), {'UTC': D22, 'Tokyo': D23, 'Oslo': D22}),
    'BeforeOsloMidnight': (datetime(2026, 11, 22, 22, 59, 30, tzinfo=UTC), {'UTC': D22, 'Tokyo': D23, 'Oslo': D22}),
    'AfterOsloMidnight': (datetime(2026, 11, 22, 23, 0, 30, tzinfo=UTC), {'UTC': D22, 'Tokyo': D23, 'Oslo': D23}),
    'AfterUtcMidnight': (datetime(2026, 11, 23, 0, 0, 30, tzinfo=UTC), {'UTC': D23, 'Tokyo': D23, 'Oslo': D23}),
}
for _name, (_now, _days) in CLOCKS.items():
    globals()[f'SetReadsAt{_name}'] = type(f'SetReadsAt{_name}', (FrozenClock, SetReads, Scenario,
                                                                   CleanerWithdrawalTestCase),
                                           {'NOW': _now, 'DAYS': _days, '__module__': __name__})
del _name, _now, _days


class BudgetTests(Fixtures, FeedingTestCase):
    """The page's queries do not grow with its rows: every unit stocked, fed, measured, held by a degree-day withdrawal
    and with a target, so each row reads every part (the withdrawal, the purge in degree-days, the last feeding, the
    forecast)."""

    CEILING = 60          # measured 55 at 3 and at 9 units (2026-11-22), a small margin; never raised without a review

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
        for queries in (small, large):
            self.assertLessEqual(queries, self.CEILING, f'the page costs {queries} queries')
        # Every row of the units made is held (its earliest date read the withdrawal, its last feeding and the water).
        made = {unit.pk for unit in self.made}
        decides = {row['earliest'].decides for row in self.client.get(reverse('farm:productionplan_list'))
                   .context['objects'] if row['share'] and row['unit'].pk in made}
        self.assertEqual(decides, {'withdrawal'})


class WaterOnAnotherClockTests(FrozenClock, FeedingTestCase):
    """A batch's water read beside batches of other clocks is the water it reads alone (main's `earliest`: one
    BatchWater per batch). U-A on UTC with a system whose site is Tokyo (the link written past Tank.clean, as raw
    writes or a restore could leave it); U-K on Kiritimati (UTC+14). At 05:00 UTC it is the 22nd on all three clocks.
    The loop's sample at 00:30 on Tokyo's first day of the water (today - 30) is before that day starts on U-A's clock
    but not on U-K's: a read of both batches' units together counts it, U-A's batch alone does not. Fed 31 days ago, a
    30 degree-day purge counts from that day (verification of wip/plans-perf, finding 2)."""
    NOW = datetime(2026, 11, 22, 5, 0, tzinfo=UTC)
    EARLY, LATE = '2', '10'         # the loop's samples on its first day, at 00:30 and 15:00 on Tokyo's clock
    MAIN_SAYS = ''                  # alone: 10 + 4 x 5 = 30 degree-days, fasted; with the early 2 counted, held

    @withdrawal_gate.opened('test fixture: samples straight in the database')
    def sample(self, point, moment, value):
        WaterMeasurement.objects.create(point=point, measured_at=moment, source='manual', temperature_c=Decimal(value),
                                        created_by=self.user)

    def setUp(self):
        super().setUp()
        self.user.groups.add(role('Harvest keeper', *HARVEST_KEEPER))
        tokyo = Site.objects.create(name='Tokyo', code='TK', timezone='Asia/Tokyo')
        kiritimati = Site.objects.create(name='Kiritimati', code='KI', timezone='Pacific/Kiritimati')
        self.ua = make_unit('U-A', self.hall)
        self.uk = make_unit('U-K', ProductionDepartment.objects.create(site=kiritimati, name='Hall K', code='HK'))
        self.system = System.objects.create(site=tokyo, name='Tokyo loop', code='TL',
                                            production_department=ProductionDepartment.objects.create(
                                                site=tokyo, name='Hall T', code='HT'))
        Tank.objects.filter(pk=self.ua.pk).update(system=self.system)          # past Tank.clean's own-site check
        self.ua.refresh_from_db()
        HandlingRule.objects.filter(kind='harvest', species=None).delete()
        HandlingRule.objects.create(kind='harvest', species=None, min_fasting_hours=0,
                                    min_fasting_degree_days=Decimal(30))
        self.bx = self.stock(self.ua, count=500, weight='100', days_ago=31)
        self.by = self.stock(self.uk, count=500, weight='100', days_ago=31)
        for unit in (self.ua, self.uk):
            record_feeding(self.user, unit=unit, day=local_today(unit) - 31 * DAY, feed=self.feed,
                           amount_kg=Decimal('0.2'))
        loop, zone = point_of(self.system), zone_of(tokyo)
        self.first = local_today(self.ua) - 30 * DAY
        self.sample(loop, datetime.combine(self.first, time(0, 30), tzinfo=zone), self.EARLY)
        self.sample(loop, datetime.combine(self.first, time(15), tzinfo=zone), self.LATE)
        for back in range(1, 5):
            self.sample(loop, datetime.combine(local_today(self.ua) - back * DAY, time(12), tzinfo=zone), '5')

    def test_a_batch_beside_a_batch_on_another_clock_reads_its_own_water(self):
        today = local_today(self.ua)
        self.assertEqual((today, local_today(self.uk)), (date(2026, 11, 22), date(2026, 11, 22)))
        # The edge is there: the two batches' units read together count the early sample on U-A's first day.
        alone = BatchWater({self.bx.pk}, today, self.first).temperatures.of(self.ua.pk, self.first)
        together = BatchWater({self.bx.pk, self.by.pk}, today, self.first).temperatures.of(self.ua.pk, self.first)
        self.assertEqual((alone, together), (Decimal(self.LATE), (Decimal(self.EARLY) + Decimal(self.LATE)) / 2))
        main = main_earliest(self.ua, self.bx)
        self.assertEqual(main.decides, self.MAIN_SAYS)
        self.assertEqual(check.earliest_of([(self.ua, self.bx)])[(self.ua.pk, self.bx.pk)], main)
        both = check.earliest_of([(self.ua, self.bx), (self.uk, self.by)])
        self.assertEqual(both, {(self.ua.pk, self.bx.pk): main,
                                (self.uk.pk, self.by.pk): main_earliest(self.uk, self.by)})
        rows = {row['unit'].pk: row for row in self.client.get(reverse('farm:productionplan_list')).context['objects']
                if row['share']}
        self.assertEqual((rows[self.ua.pk]['earliest'], rows[self.uk.pk]['earliest']),
                         (main, main_earliest(self.uk, self.by)))


class WaterOnAnotherClockWarmEarlyTests(WaterOnAnotherClockTests):
    """The unsafe side: the early sample is the warm one, so a shared read adds degree-days main never counted and
    says "free" where main holds the fish (alone: 2 + 4 x 5 = 22 degree-days)."""
    EARLY, LATE = '20', '2'
    MAIN_SAYS = check.PURGING


class HoldingGivenTests(Fixtures, FeedingTestCase):
    """`earliest_of(holding=...)`, the withdrawals a caller has read already: a unit it leaves out is an error, never a
    unit without a withdrawal; None (no provider registered) holds nothing, as `earliest` alone (verification of
    wip/plans-perf, finding 3). T-01 is held by a withdrawal in days, T-02 is not."""

    def setUp(self):
        super().setUp()
        self.user.groups.add(role('Harvest keeper', *HARVEST_KEEPER))
        self.t2_batch = self.stock(self.t2, count=600, weight='90', days_ago=15)
        self.treat(self.medicine('Short vet.', days=5), [self.t1], 2)
        self.pairs = [(self.t1, self.batch), (self.t2, self.t2_batch)]

    def test_a_unit_left_out_of_the_holding_given_is_an_error_never_free(self):
        holding = check.holding_of([self.t1, self.t2])
        self.assertTrue(holding[self.t1.pk])
        self.assertEqual(check.earliest_of(self.pairs, holding=holding)[(self.t1.pk, self.batch.pk)].decides,
                         check.WITHDRAWAL)
        with self.assertRaises(KeyError):
            check.earliest_of(self.pairs, holding={self.t2.pk: holding[self.t2.pk]})

    def test_with_no_provider_nothing_holds_as_alone_and_the_page_says_not_checked(self):
        with mock.patch.object(check.withdrawal, 'blocks_of', return_value=None):
            self.assertIsNone(check.holding_of([self.t1, self.t2]))
            expected = {(unit.pk, batch.pk): main_earliest(unit, batch) for unit, batch in self.pairs}
            self.assertEqual(expected[(self.t1.pk, self.batch.pk)].decides, '')
            self.assertEqual(check.earliest_of(self.pairs, holding=None), expected)
            self.assertEqual(check.earliest_of(self.pairs), expected)
            rows = [row for row in self.client.get(reverse('farm:productionplan_list')).context['objects']
                    if row['share']]
        self.assertEqual({(row['unit'].pk, row['share'].batch.pk): (row['withdrawal'], row['earliest']) for row in rows},
                         {key: (None, earliest) for key, earliest in expected.items()})
