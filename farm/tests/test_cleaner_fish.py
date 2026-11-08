"""Cleaner fish beside the production fish of a sea cage (docs/regulatory-reports.md, section 3 and D-1, D-2): the
species rule, what a unit's figures count, a feeding's target and the feed it splits among that target's batches, the
cull's reasons, no harvest, the sea-lice count's fish, the pages, each checked against the stored rows."""
import uuid
from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase
from django.urls import reverse

from core.audit import message
from core.models import AuditLog

from ..feeding import read, services
from ..feeding.fold import Feeding, walk
from ..health import services as health_services
from ..models import (
    Batch, FeedingRecord, FeedSuitability, HandlingPlanItem, ProductionDepartment, Site, StockMovement, StockOperation,
)
from ..models.feeding import FeedTarget
from ..models.stock import CLEANER_CULL_REASONS, PRODUCTION_CULL_REASONS, CullReason
from ..stock import integrity, read as stock_read, services as stock_services
from ..stock.fold import Line, Op
from .helpers import make_facility, make_species, role
from .test_feeding import FeedingTestCase, make_unit
from .test_harvest import HARVEST_KEEPER
from farm import withdrawal_gate


def setUpModule():
    call_command('compile_catalogs', verbosity=0)


def oct_(day):
    return date(2026, 10, day)


def cleaner_line(line_id, seq, day, kind, delta, batch, weight=None, cleaner=True, unit='T1'):
    operation = Op(f'op{seq}', 'input' if kind == 'input' else kind, day, seq)
    return Line(line_id, operation, unit, batch, kind, delta, None if weight is None else Decimal(weight), None, None,
                '', cleaner)


class WalkOfTwoKindsTests(SimpleTestCase):
    """The feeding walk splits a feeding among the batches of its target (farm/feeding/fold.py)."""

    def lines(self):
        return [cleaner_line(1, 1, oct_(1), 'input', 1000, 'A', '600', cleaner=False),     # 600 kg of salmon
                cleaner_line(2, 2, oct_(1), 'input', 2000, 'L', '100')]                    # 200 kg of lumpfish

    def test_a_feeding_is_split_among_the_batches_of_its_target_only(self):
        production = Feeding('p', 'T1', oct_(3), Decimal(10))
        cleaner = Feeding('c', 'T1', oct_(3), Decimal(4), target=FeedTarget.CLEANER_FISH)
        walked = walk(self.lines(), [production, cleaner], [('T1', oct_(3))])
        self.assertEqual((walked.split['p'], walked.split['c']), ({'A': 10}, {'L': 4}))
        self.assertEqual((walked.stays[('T1', 'A')][-1].feed, walked.stays[('T1', 'L')][-1].feed),
                         ({oct_(3): 10}, {oct_(3): 4}))
        day = walked.days[('T1', oct_(3))]
        self.assertEqual((day.biomass_kg, day.production.biomass_kg, day.of(FeedTarget.CLEANER_FISH).biomass_kg),
                         (800, 600, 200))
        self.assertEqual((day.production.start, day.of(FeedTarget.CLEANER_FISH).end), ({'A': 600000}, {'L': 200000}))
        self.assertEqual(walked.orphans, [])

    def test_a_feeding_on_the_stocking_day_is_split_by_the_end_of_the_day_among_its_target(self):
        walked = walk(self.lines(), [Feeding('c', 'T1', oct_(1), Decimal(3), target=FeedTarget.CLEANER_FISH),
                                     Feeding('p', 'T1', oct_(1), Decimal(5))])
        self.assertEqual((walked.split['c'], walked.split['p']), ({'L': 3}, {'A': 5}))

    def test_a_feeding_needs_fish_of_its_own_target(self):
        lines = self.lines() + [cleaner_line(3, 3, oct_(2), 'mortality', -2000, 'L')]
        feedings = [Feeding('c1', 'T1', oct_(2), Decimal(1), target=FeedTarget.CLEANER_FISH),     # the last day of the fish
                    Feeding('c2', 'T1', oct_(3), Decimal(1), target=FeedTarget.CLEANER_FISH),
                    Feeding('p', 'T1', oct_(3), Decimal(1))]
        walked = walk(lines, feedings)
        self.assertEqual([feeding.id for feeding in walked.orphans], ['c2'])
        self.assertEqual(set(walked.split), {'c1', 'p'})

    def test_the_species_rule_is_one_production_species_beside_any_cleaner_fish_on_a_sea_site(self):
        self.assertFalse(stock_read.mixed({1, 2}, {2}, True))
        self.assertFalse(stock_read.mixed({1, 2, 3}, {2, 3}, True))     # two cleaner species beside the salmon
        self.assertTrue(stock_read.mixed({1, 2, 3}, {3}, True))         # two production species
        self.assertTrue(stock_read.mixed({1, 2}, {2}, False))           # not on land
        self.assertTrue(stock_read.mixed({1, 2}, set(), True))
        self.assertFalse(stock_read.mixed({1}, set(), False))


class CleanerFishTestCase(FeedingTestCase):
    """A sea cage with 2,000 salmon of 125 g (250 kg) and 10,000 lumpfish of 50 g (500 kg) since 10 days, and the
    land tank T-01 of the feeding tests with its salmon."""

    def setUp(self):
        super().setUp()
        self.fjord = Site.objects.create(name='Fjord', code='FJ', type='sea_cage', latitude=Decimal('60.1'),
                                         longitude=Decimal('5.1'))
        cages = ProductionDepartment.objects.create(site=self.fjord, name='Cages', code='CG')
        self.cage, self.cage2 = make_unit('C-01', cages), make_unit('C-02', cages)
        self.lump = make_species('LUM', 'Lumpfish', 'Cyclopterus lumpus', local_name='Rognkjeks', freshwater=False,
                                 cleaner_fish_type='lumpfish')
        self.block = self.feed.__class__.objects.create(name='Lumpfish block', code='LB', feed_type='grower')
        self.salmon_batch = self.stock(self.cage, count=2000, weight='125', days_ago=10)
        self.lump_batch = self.stock(self.cage, count=10000, weight='50', days_ago=10, species=self.lump)

    def cage_stock(self, unit=None):
        unit = unit or self.cage
        return stock_read.stock_of([unit])[unit.pk]


class SpeciesRuleTests(CleanerFishTestCase):
    def test_cleaner_fish_join_the_production_fish_on_a_sea_site_and_are_not_in_the_units_figures(self):
        stock = self.cage_stock()
        self.assertEqual([(share.batch, share.cleaner) for share in stock.shares],
                         [(self.salmon_batch, False), (self.lump_batch, True)])
        self.assertEqual((stock.count, stock.biomass_kg, stock.avg_weight_g, stock.batches),
                         (2000, 250, 125, [self.salmon_batch]))
        cleaner = stock.cleaner_stock
        self.assertEqual((cleaner.count, cleaner.biomass_kg, cleaner.batches), (10000, 500, [self.lump_batch]))
        self.assertEqual([(share.unit_count, share.siblings) for share in stock.shares], [(2000, 1), (10000, 1)])
        self.assertEqual(stock_read.unit_counts([self.cage.pk]), {self.cage.pk: 12000})   # the ledger's own count
        self.assertStockAddsUp()

    def test_a_second_production_species_is_refused_beside_them(self):
        errors = self.refused(self.stock, self.cage, days_ago=10, species=self.trout)
        self.assertIn('a unit holds one species of production fish at a time, beside its cleaner fish',
                      errors['species'][0])
        self.assertIn(str(self.trout), errors['species'][0])
        self.assertEqual(Batch.all_objects.count(), 3)

    def test_on_a_land_site_cleaner_fish_do_not_join_the_production_fish_nor_the_other_way(self):
        errors = self.refused(self.stock, self.t1, days_ago=10, species=self.lump)       # T-01 holds salmon
        self.assertIn('cleaner fish join the production fish only on a sea site', errors['species'][0])
        self.stock(self.t2, species=self.lump, days_ago=10)                              # alone: a cleaner-fish hatchery
        errors = self.refused(self.stock, self.t2, days_ago=10)
        self.assertIn('only on a sea site', errors['species'][0])
        self.assertStockAddsUp()

    def test_cleaner_fish_alone_in_a_cage_and_the_production_fish_arriving_later_and_two_cleaner_species(self):
        wrasse = make_species('USB', 'Ballan wrasse', 'Labrus bergylta', local_name='Berggylt', freshwater=False,
                              cleaner_fish_type='wrasse')
        self.stock(self.cage2, count=500, weight='30', days_ago=10, species=self.lump)
        self.stock(self.cage2, count=300, weight='60', days_ago=9, species=wrasse)
        self.stock(self.cage2, count=100, weight='100', days_ago=8)
        stock = self.cage_stock(self.cage2)
        self.assertEqual((stock.count, [batch.species for batch in stock.batches]), (100, [self.salmon]))
        self.assertEqual(stock.cleaner_stock.count, 800)
        self.assertStockAddsUp()

    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def test_check_stock_finds_cleaner_fish_in_a_land_unit_and_two_production_species_in_a_cage(self):
        for code, unit, species in (('B-2026-901', self.t1, self.lump), ('B-2026-902', self.cage, self.trout)):
            batch = Batch.objects.create(code=code, species=species, input_stage='fry', origin='own_hatchery',
                                         provenance='farmed', input_date=self.day(5))
            operation = StockOperation.objects.create(kind='input', date=self.day(5))
            StockMovement.objects.create(operation=operation, batch=batch, unit=unit, kind='input', count_delta=10,
                                         avg_weight_g=Decimal(5))
        found = integrity.problems()
        self.assertEqual(sorted(problem for problem in found if 'species' in problem),
                         ['Unit C-01 holds 3 species.', 'Unit T-01 holds 2 species.'])

    def test_the_capacity_is_the_production_fishs(self):
        self.stock(self.cage, count=200000, weight='100', species=self.lump, days_ago=5)    # 20,000 kg of lumpfish
        stock = self.cage_stock()
        self.assertEqual((stock.biomass_kg, stock.over_capacity), (250, False))
        self.assertEqual(stock.cleaner_stock.biomass_kg, 20500)
        errors = self.refused(self.stock, self.cage, count=50000, weight='110', days_ago=5)   # 5,500 kg of salmon
        self.assertIn('over_capacity_ack', errors)
        self.assertIn('would hold 5,750 kg', errors['over_capacity_ack'][0])          # the salmon's, not 26,250


class CullAndHarvestTests(CleanerFishTestCase):
    def cull(self, batch, reason, **fields):
        return stock_services.record_cull(self.user, unit=self.cage, batch=batch, day=self.day(5), count=10,
                                          reason=reason, notes='noted', **fields)

    def test_a_cleaner_fish_is_culled_for_the_six_causes_and_a_production_fish_for_the_others(self):
        for reason in CLEANER_CULL_REASONS:
            self.cull(self.lump_batch, reason)
        for reason in PRODUCTION_CULL_REASONS:
            self.cull(self.salmon_batch, reason)
        self.assertEqual(set(StockMovement.objects.filter(kind='cull', batch=self.lump_batch)
                             .values_list('reason', flat=True)), {reason.value for reason in CLEANER_CULL_REASONS})
        self.assertEqual(set(StockMovement.objects.filter(kind='cull', batch=self.salmon_batch)
                             .values_list('reason', flat=True)), {reason.value for reason in PRODUCTION_CULL_REASONS})
        self.assertEqual(self.cage_stock().cleaner_stock.count, 10000 - 10 * len(CLEANER_CULL_REASONS))
        self.assertStockAddsUp()

    def test_the_other_batchs_reasons_are_refused_with_the_batch_named(self):
        errors = self.refused(self.cull, self.lump_batch, CullReason.SMALL_SIZE)
        self.assertEqual(errors['reason'], [f'Small size is not a reason to cull {self.lump_batch.code}.'])
        errors = self.refused(self.cull, self.salmon_batch, CullReason.INJURED)
        self.assertEqual(errors['reason'], [f'Injured is not a reason to cull {self.salmon_batch.code}.'])
        self.assertFalse(StockMovement.objects.filter(kind='cull').exists())

    def test_the_cull_dialog_offers_each_batch_its_own_reasons_and_the_service_holds_them(self):
        url = reverse('farm:stock_cull', args=[self.cage.pk])
        field = self.client.get(url).context['form'].fields['reason']
        groups = {str(group): [value for value, _label in options] for group, options in field.choices[1:]}
        self.assertEqual(groups, {'Production fish': [reason.value for reason in PRODUCTION_CULL_REASONS],
                                  'Cleaner fish': [reason.value for reason in CLEANER_CULL_REASONS]})
        alone = self.stock(self.cage2, species=self.lump, days_ago=5)
        field = self.client.get(reverse('farm:stock_cull', args=[self.cage2.pk])).context['form'].fields['reason']
        self.assertEqual([value for value, _label in field.choices], [reason.value for reason in CLEANER_CULL_REASONS])
        data = {'token': str(uuid.uuid4()), 'batch': str(alone.pk), 'date': self.day(2).isoformat(), 'count': '10',
                'reason': 'emaciated', 'notes': ''}
        self.assertEqual(self.client.post(reverse('farm:stock_cull', args=[self.cage2.pk]), data,
                                          headers={'X-Modal': '1'}).status_code, 204)
        self.assertEqual(StockMovement.objects.get(kind='cull').reason, 'emaciated')
        wrong = self.client.post(url, {**data, 'token': str(uuid.uuid4()), 'batch': str(self.salmon_batch.pk)})
        self.assertEqual(wrong.status_code, 422)
        self.assertEqual(wrong.context['form'].errors['reason'],
                         [f'Emaciated is not a reason to cull {self.salmon_batch.code}.'])

    def test_cleaner_fish_are_culled_at_the_end_of_their_use_not_harvested(self):
        errors = self.refused(stock_services.record_harvest, self.user, unit=self.cage, batch=self.lump_batch,
                              day=self.day(1), count=10, measured_weight_kg=Decimal(1), facility=make_facility())
        self.assertEqual(errors['batch'], ['Cleaner fish are not harvested: record their cull, with the reason '
                                           '“Healthy, no longer to be used” at the end of their use.'])
        form = self.client.get(reverse('farm:stock_harvest', args=[self.cage.pk])).context['form']
        self.assertEqual([share.batch for share in form.present.values()], [self.salmon_batch])
        self.stock(self.cage2, species=self.lump, days_ago=5)
        self.assertContains(self.client.get(reverse('farm:stock_harvest', args=[self.cage2.pk])),
                            'No fish are in C-02.')

    def test_cleaner_fish_are_not_in_the_harvest_plan_nor_its_targets(self):
        self.user.groups.add(role('Harvest keeper', *HARVEST_KEEPER))
        form = self.client.get(reverse('farm:handlingplanitem_create'), {'kind': 'harvest'}).context['form']
        self.assertEqual(set(form.fields['batch'].queryset), {self.salmon_batch, self.batch})
        target_form = self.client.get(reverse('farm:productionplan_create')).context['form']
        self.assertEqual(set(target_form.fields['batch'].queryset), {self.salmon_batch, self.batch})
        listed = self.client.get(reverse('farm:productionplan_list'))
        self.assertEqual({row['share'].batch for row in listed.context['objects'] if row['share']},
                         {self.salmon_batch, self.batch})
        self.assertFalse(HandlingPlanItem.objects.exists())


class SpeciesFlagTests(CleanerFishTestCase):
    def errors(self, species):
        try:
            species.full_clean()
        except ValidationError as error:
            return error.message_dict
        return {}

    def test_whether_a_species_is_a_cleaner_fish_is_fixed_once_fish_of_it_have_been_stocked(self):
        fixed = ['Fixed: fish of this species have been stocked, so whether it is a cleaner fish cannot change.']
        self.lump.cleaner_fish_type = ''
        self.assertEqual(self.errors(self.lump)['cleaner_fish_type'], fixed)
        self.lump.cleaner_fish_type = 'wrasse'                   # one cleaner fish for another: the same reads
        self.assertNotIn('cleaner_fish_type', self.errors(self.lump))
        self.salmon.cleaner_fish_type = 'lumpfish'
        self.assertEqual(self.errors(self.salmon)['cleaner_fish_type'], fixed)
        unused = make_species('COD', 'Cod', 'Gadus morhua', local_name='Torsk')
        unused.cleaner_fish_type = 'wrasse'
        self.assertNotIn('cleaner_fish_type', self.errors(unused))     # nothing stocked: it may change


class FeedingTargetTests(CleanerFishTestCase):
    def test_the_days_view_gives_the_production_fish_their_feed_and_the_cleaner_fish_a_line_of_their_own(self):
        self.feed_cage('10', days_ago=1)
        self.feed_cage('4', FeedTarget.CLEANER_FISH, self.block, days_ago=1)
        self.feed_cage('3', FeedTarget.CLEANER_FISH, self.block, days_ago=2)      # a day with the cleaner fish only
        page = self.client.get(reverse('farm:feeding_records'), {'view': 'days'})
        rows = {row['day']: row for row in page.context['day_rows'] if row['unit'] == self.cage}
        self.assertEqual({day: (row['given_kg'], row['cleaner_kg']) for day, row in rows.items()
                          if row['given_kg'] or row['cleaner_kg']}, {self.day(1): (10, 4), self.day(2): (0, 3)})
        self.assertEqual((page.context['given_kg'], page.context['cleaner_kg']), (10, 7))
        self.assertContains(page, 'to the cleaner fish')

    def test_the_lice_count_is_of_the_cages_with_production_fish(self):
        self.stock(self.cage2, species=self.lump, days_ago=5)               # a cage of cleaner fish alone
        self.user.groups.add(role('Lice counter', 'view_licecount', 'add_licecount'))
        form = self.client.get(reverse('farm:lice_record')).context['form']
        self.assertIn(self.cage, form.fields['unit'].queryset)
        self.assertNotIn(self.cage2, form.fields['unit'].queryset)

    def feed_cage(self, kilos, target=FeedTarget.PRODUCTION, feed=None, days_ago=1, **fields):
        return self.record(kilos=kilos, days_ago=days_ago, unit=self.cage, feed=feed or self.feed, target=target,
                           **fields)

    def test_each_feeding_is_split_among_the_batches_of_its_target_and_read_per_batch_and_feed(self):
        production = self.feed_cage('10', days_ago=3)
        cleaner = self.feed_cage('4', FeedTarget.CLEANER_FISH, self.block, days_ago=3)
        self.assertEqual(read.split_of([production, cleaner]), {production.pk: {self.salmon_batch.pk: 10},
                                                                cleaner.pk: {self.lump_batch.pk: 4}})
        self.assertEqual(read.fed([self.cage], self.day(5), self.today), {
            (self.cage.pk, self.salmon_batch.pk, self.feed.pk): 10, (self.cage.pk, self.lump_batch.pk, self.block.pk): 4})
        self.assertEqual((production.target, cleaner.target), ('production', 'cleaner_fish'))

    def test_a_feeding_for_cleaner_fish_needs_cleaner_fish_in_the_unit_and_says_which_is_missing(self):
        errors = self.refused(self.record, kilos='1', unit=self.t1, target=FeedTarget.CLEANER_FISH)
        self.assertEqual(errors, {'target': ['T-01 holds no cleaner fish on '
                                             f'{stock_services.shown_date(self.day(1))}.']})
        self.stock(self.cage2, species=self.lump, days_ago=5)
        errors = self.refused(self.record, kilos='1', unit=self.cage2, target=FeedTarget.PRODUCTION)
        self.assertEqual(errors, {'target': ['C-02 holds no fish on '
                                             f'{stock_services.shown_date(self.day(1))}.']})
        self.assertEqual(FeedingRecord.objects.count(), 0)

    def test_the_feed_rate_is_against_the_fish_fed(self):
        # 30 kg is 12 % of the salmon's 250 kg (the limit is 10 %) and 4 % of the cage's 750 kg.
        errors = self.refused(self.feed_cage, '30')
        self.assertIn('is 12.0 % of the 250.0 kg C-01 holds', errors['high_rate_ack'][0])
        self.assertTrue(self.feed_cage('30', ack=True).high_rate_ack)
        self.assertFalse(self.feed_cage('30', FeedTarget.CLEANER_FISH, self.block).high_rate_ack)   # 6 % of 500 kg

    def test_a_stock_operation_cannot_leave_a_feeding_without_its_fish(self):
        self.feed_cage('2', FeedTarget.CLEANER_FISH, self.block, days_ago=2)
        errors = self.refused(stock_services.record_cull, self.user, unit=self.cage, batch=self.lump_batch,
                              day=self.day(3), count=10000, reason='not_used')
        self.assertEqual(errors['__all__'], [f'The feeding of {stock_services.shown_date(self.day(2))} in C-01 would '
                                             'have no fish: void it first.'])
        stock_services.record_cull(self.user, unit=self.cage, batch=self.lump_batch, day=self.day(1), count=10000,
                                   reason='not_used')          # after the feeding: fine
        self.assertStockAddsUp()
        # The salmon's own feedings do not need the lumpfish.
        self.feed_cage('5', days_ago=1)
        self.assertEqual(FeedingRecord.objects.count(), 2)

    def test_the_units_week_and_conversion_are_the_production_fishs(self):
        self.feed_cage('10', days_ago=2)
        self.feed_cage('4', FeedTarget.CLEANER_FISH, self.block, days_ago=2)
        stock = stock_read.stock_of([self.cage])
        figures = read.figures(stock, details=[self.cage])[self.cage.pk]
        self.assertEqual([(share.batch, share.cleaner, share.fed_kg) for share in figures.shares],
                         [(self.salmon_batch, False, 10), (self.lump_batch, True, 4)])
        self.assertEqual(figures.unweighed, [self.salmon_batch])
        self.assertEqual(figures.week.kg, 10)                      # the production fish's feed against their biomass
        self.assertEqual(figures.week.feed, self.feed)
        self.assertEqual(figures.last_fed, self.day(2))
        unit_day = figures.ration
        self.assertEqual((unit_day.fed_kg, [share.batch_id for share in unit_day.production], unit_day.meals_done),
                         (0, [self.salmon_batch.pk], 0))        # today: nothing fed yet

    def test_the_meal_board_days_total_the_production_fish_only(self):
        self.feed_cage('10', days_ago=0)
        self.feed_cage('4', FeedTarget.CLEANER_FISH, self.block, days_ago=0, meals=2)
        unit_day = read.project([self.cage.pk], [(self.cage.pk, self.today)]).days[(self.cage.pk, self.today)]
        self.assertEqual((unit_day.fed_kg, unit_day.meals_done, len(unit_day.feedings)), (10, 1, 2))
        self.assertEqual({share.batch_id for share in unit_day.shares}, {self.salmon_batch.pk, self.lump_batch.pk})
        self.assertEqual([share.batch_id for share in unit_day.production], [self.salmon_batch.pk])

    def test_the_last_feeding_of_the_fish_handled_is_the_production_fishs(self):
        self.feed_cage('10', days_ago=3)
        self.feed_cage('4', FeedTarget.CLEANER_FISH, self.block, days_ago=1)
        last = read.last_fed_at(self.cage, self.today)
        self.assertEqual(last.record.date, self.day(3))

    def test_the_split_preview_names_the_batches_of_the_target(self):
        from ..feeding.views import _split
        self.stock(self.cage, count=1000, weight='100', days_ago=9, species=self.lump)
        parts = _split(self.cage, self.day(1), FeedTarget.CLEANER_FISH)
        self.assertEqual(sorted(code for code, _share in parts['parts']),
                         sorted(batch.code for batch in Batch.objects.filter(species=self.lump)))
        self.assertIsNone(_split(self.cage, self.day(1)))           # one batch of salmon: no split to show


class FeedingDialogTests(CleanerFishTestCase):
    def url(self, unit=None):
        return f'{reverse("farm:feeding_record", args=[(unit or self.cage).pk])}?unit={(unit or self.cage).pk}'

    def data(self, **fields):
        return super().data(**{'amount_kg': '3', 'meals': '', 'time': '', **fields})

    def suit(self, feed, species, low, high):
        FeedSuitability.objects.create(feed=feed, species=species, growth_stage='all', min_weight_g=low,
                                       max_weight_g=high)

    def test_the_target_is_asked_only_where_cleaner_fish_are_and_is_stored_and_listed(self):
        self.assertNotIn('target', self.client.get(self.url(self.t1)).context['form'].fields)
        form = self.client.get(self.url()).context['form']
        self.assertEqual([value for value, _label in form.fields['target'].choices], ['', 'production', 'cleaner_fish'])
        response = self.client.post(self.url(), self.data(feed=str(self.block.pk), target='cleaner_fish'),
                                    headers={'X-Modal': '1'})
        self.assertEqual(response.status_code, 204)
        record = FeedingRecord.objects.get()
        self.assertEqual((record.unit, record.feed, record.target, record.amount_kg),
                         (self.cage, self.block, 'cleaner_fish', Decimal('3.000')))
        self.assertEqual(AuditLog.objects.get(entity_type='feeding record').changes['Fed to'],
                         [None, message('Cleaner fish')])
        listed = self.client.get(reverse('farm:feeding_records'))
        self.assertContains(listed, self.lump_batch.code)
        self.assertContains(listed, 'Cleaner fish')
        self.assertEqual(read.split_of([record]), {record.pk: {self.lump_batch.pk: 3}})
        # Voided, it stops counting.
        services.void_feeding(self.user, record, 'Wrong cage')
        self.assertEqual(read.fed([self.cage], self.day(5), self.today), {})

    def test_left_to_the_feed_the_target_is_the_one_kind_of_fish_the_feed_suits_and_never_guessed_otherwise(self):
        self.suit(self.block, self.lump, 0, 1000)
        self.suit(self.feed, self.salmon, 0, 1000)
        both = self.feed.__class__.objects.create(name='All fish', code='AF', feed_type='grower')
        self.suit(both, self.lump, 0, 1000)
        self.suit(both, self.salmon, 0, 1000)
        for feed, target in ((self.block, 'cleaner_fish'), (self.feed, 'production')):
            self.client.post(self.url(), self.data(feed=str(feed.pk), target=''), headers={'X-Modal': '1'})
            self.assertEqual(FeedingRecord.objects.order_by('-created_at').first().target, target, feed.code)
        # A feed that suits both kinds of fish (or neither) does not say whom it is for: the person is asked.
        asked = 'Say whom the feed is for: the production fish or the cleaner fish.'
        neither = self.feed.__class__.objects.create(name='Other fish', code='OF', feed_type='grower')
        self.suit(neither, make_species('COD', 'Cod', 'Gadus morhua', local_name='Torsk'), 0, 1000)
        for feed in (both, neither):
            response = self.client.post(self.url(), self.data(feed=str(feed.pk), target=''))
            self.assertEqual((response.status_code, response.context['form'].errors['target']), (422, [asked]), feed.code)
        self.assertEqual(FeedingRecord.objects.count(), 2)
        response = self.client.post(self.url(), self.data(feed=str(both.pk), target='production'),
                                    headers={'X-Modal': '1'})
        self.assertEqual((response.status_code, FeedingRecord.objects.count()), (204, 3))
        # The choices list the feeds that suit either kind of fish first.
        groups = self.client.get(self.url()).context['form'].fields['feed'].choices
        self.assertEqual(str(groups[1][0]), 'Suitable for these fish')

    def test_a_feed_that_suits_any_cleaner_species_of_the_unit_is_the_cleaner_fishs(self):
        wrasse = make_species('WRA', 'Ballan wrasse', 'Labrus bergylta', local_name='Berggylt', freshwater=False,
                              official_code='WRA', cleaner_fish_type='wrasse')
        self.stock(self.cage, count=500, weight='60', days_ago=9, species=wrasse)      # lumpfish and wrasse share the cage
        only_wrasse = self.feed.__class__.objects.create(name='Wrasse feed', code='WF', feed_type='grower')
        self.suit(only_wrasse, wrasse, 0, 1000)
        self.suit(self.feed, self.salmon, 0, 1000)
        response = self.client.post(self.url(), self.data(feed=str(only_wrasse.pk), target=''),
                                    headers={'X-Modal': '1'})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(FeedingRecord.objects.get().target, 'cleaner_fish')

    def test_a_unit_without_cleaner_fish_has_no_target_and_a_unit_of_cleaner_fish_alone_feeds_them(self):
        response = self.client.post(self.url(self.t1), self.data(feed=str(self.block.pk)), headers={'X-Modal': '1'})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(FeedingRecord.objects.get().target, 'production')   # no cleaner fish in T-01: no target asked
        self.stock(self.cage2, species=self.lump, days_ago=5)
        wrong = self.client.post(self.url(self.cage2), self.data(target='production'))
        self.assertEqual(wrong.status_code, 422)
        self.assertEqual(wrong.context['form'].errors['target'],
                         [f'C-02 holds no fish on {stock_services.shown_date(self.day(1))}.'])
        right = self.client.post(self.url(self.cage2), self.data(target=''), headers={'X-Modal': '1'})
        self.assertEqual(right.status_code, 204)             # left to the feed: there is nothing else to feed
        self.assertEqual(FeedingRecord.objects.get(unit=self.cage2).target, 'cleaner_fish')

    def test_the_pages_show_the_cleaner_fish_beside_the_unit_and_not_in_its_figures(self):
        page = self.client.get(reverse('farm:production_units'), {'unit': self.cage.pk})
        self.assertContains(page, f'Cleaner fish: {self.lump_batch.code} · 10,000 fish')
        self.assertContains(page, 'Cleaner fish: 10,000 fish, 500 kg: not in the figures below')
        rows = {row['unit']: row for row in page.context['rows']}
        self.assertEqual((rows[self.cage]['stock'].count, rows[self.cage]['stock'].biomass_kg), (2000, 250))
        chooser = self.client.get(reverse('farm:feeding_new'))
        self.assertContains(chooser, f'cleaner fish {self.lump_batch.code}: 10,000 fish')
        self.assertStockAddsUp()

    def test_a_unit_of_cleaner_fish_alone_is_listed_with_them(self):
        self.stock(self.cage2, species=self.lump, count=300, weight='40', days_ago=5)
        page = self.client.get(reverse('farm:production_units'), {'unit': self.cage2.pk})
        self.assertContains(page, 'Cleaner fish: ')
        rows = {row['unit']: row for row in page.context['rows']}
        self.assertEqual((rows[self.cage2]['stock'].count, rows[self.cage2]['stock'].cleaner_stock.count), (0, 300))


class HealthRecordsOfTheFishTests(CleanerFishTestCase):
    def count(self, unit, **fields):
        return health_services.record_lice_count(self.user, unit=unit, day=self.day(1), fish_counted=20,
                                                 adult_females=2, mobile=3, attached=4, **fields)

    def test_a_sea_lice_count_needs_production_fish_in_the_unit(self):
        self.stock(self.cage2, species=self.lump, days_ago=5)
        errors = self.refused(self.count, self.cage2)
        self.assertEqual(errors, {'date': [f'C-02 holds no fish on {stock_services.shown_date(self.day(1))}.']})
        self.assertEqual(self.count(self.cage).fish_counted, 20)          # salmon beside the cleaner fish: counted

    def test_a_stock_operation_cannot_leave_a_count_without_its_salmon(self):
        self.count(self.cage)
        errors = self.refused(stock_services.record_mortality, self.user, unit=self.cage, batch=self.salmon_batch,
                              day=self.day(2), count=2000, cause='disease')
        self.assertEqual(errors['__all__'], [f'The sea-lice count of {stock_services.shown_date(self.day(1))} in C-01 '
                                             'would have no fish: void it first.'])

    def test_the_medicine_withdrawal_and_the_water_still_see_every_fish(self):
        presence = stock_read.Presence.of_units([self.cage.pk])
        self.assertEqual(presence.batches_in(self.cage.pk, self.day(1)), {self.salmon_batch.pk, self.lump_batch.pk})


class DatabaseRuleTests(CleanerFishTestCase):
    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def test_the_database_holds_the_feeding_targets_the_provenance_the_year_class_and_the_cull_reasons(self):
        record = self.record(kilos='1')
        with self.assertRaises(IntegrityError), transaction.atomic():
            FeedingRecord.objects.filter(pk=record.pk).update(target='fish')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Batch.all_objects.filter(pk=self.lump_batch.pk).update(provenance='wild_caught')    # its origin says farmed
        with self.assertRaises(IntegrityError), transaction.atomic():
            Batch.all_objects.filter(pk=self.lump_batch.pk).update(year_class=1979)
        Batch.all_objects.filter(pk=self.lump_batch.pk).update(year_class=2026)
        operation = StockOperation.objects.filter(movements__batch=self.lump_batch).get()
        good = {'operation': operation, 'batch': self.lump_batch, 'unit': self.cage, 'kind': 'cull',
                'count_delta': -5}
        with self.assertRaises(IntegrityError), transaction.atomic():
            StockMovement.objects.create(**good, reason='not_a_reason')
        with self.assertRaises(IntegrityError), transaction.atomic():
            StockMovement.objects.create(**{**good, 'kind': 'mortality'}, reason='emaciated')   # a cull's cause only
        StockMovement.objects.create(**good, reason='emaciated')                                  # one of the six: fine
