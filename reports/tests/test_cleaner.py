"""The monthly cleaner-fish report: per unit, species and origin the fish at the end of the month before, those stocked
and moved in, those taken out by cause, the month's adjustments netted, the feed dry and wet, and the JSON as
Mattilsynet's API takes it (validated against its OpenAPI)."""
import json
from decimal import Decimal

from django.urls import reverse

from farm.feeding import services as feeding
from farm.models import Batch, Feed, StockMovement, StockOperation, Supplier
from farm.stock import services
from farm.tests.helpers import make_species
from farm.tests.test_stock import make_unit

from .. import compute, exports
from ..models import Report
from .helpers import OCTOBER, ReportTestCase, day, previewed
from .schema import errors


class CleanerFishTestCase(ReportTestCase):
    """The sea cage M-01 with 2,000 salmon and 10,000 farmed lumpfish since September, 2,000 wild lumpfish from 5
    October, and M-02, where 500 of the farmed lumpfish are moved on 15 October."""

    def setUp(self):
        super().setUp()
        self.m2 = make_unit('M-02', self.bay, regulatory_unit_id='2')
        self.lump = make_species('LUM', 'Lumpfish', 'Cyclopterus lumpus', local_name='Rognkjeks', freshwater=False,
                                 official_code='LUM', cleaner_fish_type='lumpfish')
        self.stock(self.m1, 2000, '125', day(9, 20))              # the production fish: no part of this report
        self.farmed = self.cleaner(self.m1, 10000, '50', day(9, 20))
        self.wild = self.cleaner(self.m1, 2000, '80', day(10, 5), origin='wild')
        services.record_mortality(self.user, unit=self.m1, batch=self.farmed, day=day(10, 8), count=100,
                                  cause='unknown')
        for number, count, reason in ((10, 50, 'sick'), (11, 30, 'not_used'), (12, 20, 'emaciated')):
            services.record_cull(self.user, unit=self.m1, batch=self.farmed, day=day(10, number), count=count,
                                 reason=reason)
        services.record_transfer(self.user, source=self.m1, batch=self.farmed, day=day(10, 15),
                                 legs=[(self.m2, 500)], reason='density')
        self.adjust(self.m1, self.farmed, day(10, 20), -40, 'escape')
        self.dry = Feed.objects.create(name='Lumpfish pellets', code='LP', feed_type='grower', feed_form='dry')
        self.wet = Feed.objects.create(name='Fish paste', code='FP', feed_type='grower', feed_form='wet')
        self.salmon_feed = Feed.objects.create(name='Salmon pellets', code='SP', feed_type='grower')

    def cleaner(self, unit, count, weight, on, **fields):
        operation = services.record_input(self.user, species=self.lump, input_stage='fry',
                                          **{'origin': 'own_hatchery', **fields}, day=on,
                                          lines=[(unit, count, Decimal(weight))])
        return operation.movements.first().batch

    def adjust(self, unit, batch, on, count, reason):
        """A count adjustment, which has no dialog: its operation and line as the stock service would write them."""
        operation = StockOperation.objects.create(kind='adjustment', date=on, created_by=self.user)
        return StockMovement.objects.create(operation=operation, batch=batch, unit=unit, kind='adjustment',
                                            count_delta=count, reason=reason)

    def feed_cleaner(self, feed, kilos, on, target='cleaner_fish'):
        return feeding.record_feeding(self.user, unit=self.m1, day=on, feed=feed, amount_kg=Decimal(kilos),
                                      target=target)

    def result(self, site=None):
        site = site or self.sea
        report = Report.objects.filter(site=site).first() or self.report(Report.Kind.CLEANER_FISH, OCTOBER, site=site)
        return compute.compute(report)


class FiguresTests(CleanerFishTestCase):
    def test_the_month_per_unit_species_and_origin_from_the_ledger(self):
        self.feed_cleaner(self.dry, '1', day(10, 3))
        result = self.result()
        self.assertEqual((result.problems, result.warnings), ([], []))
        units = {unit['number']: unit for unit in result.content['units'].values()}
        self.assertEqual(sorted(units), ['1', '2'])
        farmed, wild = units['1']['species']
        self.assertEqual((farmed['species'], farmed['origin'], farmed['opening'], farmed['stocked'], farmed['moved_in'],
                          farmed['died'], farmed['moved_out'], farmed['unaccounted'], farmed['closing']),
                         ('LUM', 'farmed', 10000, 0, 0, 100, 500, 40, 9260))
        self.assertEqual(farmed['culled'], {'sick': 50, 'injured': 0, 'emaciated': 20, 'salmon_handling': 0,
                                            'poor_environment': 0, 'not_used': 30})
        self.assertEqual((wild['origin'], wild['opening'], wild['stocked'], wild['closing']),
                         ('wild_caught', 0, 2000, 2000))
        moved, = units['2']['species']
        self.assertEqual((moved['origin'], moved['opening'], moved['moved_in'], moved['closing']),
                         ('farmed', 0, 500, 500))
        self.assertEqual(result.content['identity']['organisation_number'], '987654321')

    def test_the_production_fish_are_not_in_it_and_a_unit_without_cleaner_fish_is_not_listed(self):
        units = self.result().content['units']
        self.assertEqual({species['species'] for unit in units.values() for species in unit['species']}, {'LUM'})
        self.assertEqual(self.result(self.hatchery).problems,
                         ['No unit of the site held cleaner fish in the month: the report has nothing to file.'])

    def test_no_feed_recorded_for_the_cleaner_fish_is_said(self):
        warning = ('No feeding of the cleaner fish is recorded in the month, so their feed is filed as 0 kg '
                   '(Operations › Feeding: choose the cleaner fish as the target).')
        self.assertIn(warning, self.result().warnings)
        self.feed_cleaner(self.dry, '6.6', day(10, 3))
        self.assertNotIn(warning, self.result().warnings)

    def test_the_feed_is_the_cleaner_fishs_in_whole_kilos_dry_and_wet(self):
        self.feed_cleaner(self.dry, '6.6', day(10, 3))
        self.feed_cleaner(self.dry, '1', day(10, 4))
        self.feed_cleaner(self.wet, '2.4', day(10, 4))
        self.feed_cleaner(self.salmon_feed, '20', day(10, 4), target='production')
        self.feed_cleaner(self.dry, '40', day(9, 30))                              # the month before
        feed = self.result().content['feed']
        self.assertEqual((feed['dry_kg'], feed['wet_kg']), (8, 2))                  # 7.6 and 2.4, half up
        self.assertEqual(feed['feeds'], [{'feed': 'Fish paste', 'form': 'wet', 'kg': '2.4'},
                                         {'feed': 'Lumpfish pellets', 'form': 'dry', 'kg': '7.6'}])

    def test_a_recount_up_is_a_warning_a_cull_of_another_reason_and_a_harvest_are_problems(self):
        self.feed_cleaner(self.dry, '1', day(10, 3))
        self.adjust(self.m1, self.farmed, day(10, 21), 10, 'count_correction')      # nets to a loss of 30
        result = self.result()
        farmed = next(unit for unit in result.content['units'].values() if unit['number'] == '1')['species'][0]
        self.assertEqual((farmed['unaccounted'], farmed['adjusted_up'], farmed['closing']), (30, 0, 9270))
        self.adjust(self.m1, self.wild, day(10, 22), 15, 'count_correction')
        result = self.result()
        self.assertEqual(result.problems, [])
        self.assertEqual(result.warnings, [
            'Unit 1: count adjustments of both signs in the month net to -30 fish of LUM, though 40 fish left by an '
            'escape or a recount down: check that the figure filed is the one meant.',
            'Unit 1: 15 more fish of LUM are in the count than the month’s lines explain (a recount up). The report '
            'has no field for it: file it as Mattilsynet accepts, or correct the count.'])
        operation = StockOperation.objects.create(kind='cull', date=day(10, 23), created_by=self.user)
        StockMovement.objects.create(operation=operation, batch=self.farmed, unit=self.m1, kind='cull',
                                     count_delta=-5, reason='grading')
        problems = self.result().problems
        self.assertIn(f'A cull of {self.farmed.code} on 2026-10-23 has the reason “grading”, which is none of '
                      'Mattilsynet’s six causes for cleaner fish.', problems)
        self.assertIn('Unit 1: the fish of LUM at the start and the month’s lines do not add up to the fish at its '
                      'end: look at its operations.', problems)

    def test_a_batch_without_its_origin_cannot_be_reported(self):
        supplier = Supplier.objects.create(name='Fisherman', code='FM', supplies=['live_fish'])
        bought = self.cleaner(self.m2, 300, '60', day(10, 6), origin='purchased', supplier=supplier,
                              provenance='wild_caught')
        Batch.all_objects.filter(pk=bought.pk).update(provenance='')
        self.assertEqual(self.result().problems, [
            f'Batch {bought.code} has no origin, farmed or wild-caught (Operations › Production units): the report asks '
            'it of every cleaner fish.'])

    def test_a_species_without_its_code_keeps_it_from_being_ready(self):
        self.lump.official_code = ''
        self.lump.save()
        self.assertEqual(self.result().problems, ['Lumpfish (LUM) has no official code (Setup › Reference data › '
                                                  'Species).'])


class ExportAndPageTests(CleanerFishTestCase):
    def test_the_month_as_mattilsynets_api_takes_it_validated_against_its_openapi(self):
        self.feed_cleaner(self.dry, '6.6', day(10, 3))
        self.feed_cleaner(self.wet, '2.4', day(10, 4))
        report = self.report(Report.Kind.CLEANER_FISH, OCTOBER, site=self.sea)
        body = exports.api_json(report, compute.compute(report).content)
        self.assertEqual(errors(body, 'RensefiskrapporteringDto'), [])
        self.assertEqual((body['rapporteringsår'], body['rapporteringsmåned'], body['tørrforKg'], body['våtforKg'],
                          body['organisasjonsnummer'], body['lokalitetsnummer']), (2026, 10, 7, 2, '987654321', 23456))
        first = body['produksjonsenheter'][0]
        self.assertEqual(first['merdId'], '1')
        self.assertEqual(first['arter'][0], {
            'artskode': 'LUM', 'opprinnelse': 'OPPDRETTET', 'beholdningVedForrigeMånedsslutt': 10000,
            'utsett': {'antallNy': 0, 'antallFlyttetInn': 0},
            'uttak': {'antallAvlivetSykdom': 50, 'antallAvlivetSkader': 0, 'antallAvlivetAvmagret': 20,
                      'antallAvlivetForeståendeHåndteringAvLaksen': 0,
                      'antallAvlivetForeståendeUgunstigLevemiljø': 0, 'antallAvlivetSkalIkkeBrukes': 30,
                      'antallSelvdød': 100, 'antallFlyttetUt': 500, 'antallKanIkkeGjøresRedeFor': 40}})
        self.assertEqual(first['arter'][1]['opprinnelse'], 'VILLFANGET')

    def test_the_report_is_started_filed_and_exported_through_the_pages(self):
        response = self.client.post(reverse('reports:report_create'), {
            'kind': 'cleaner_fish', 'site': str(self.sea.pk), 'period_start': '2026-10-17',
            'contact_name': 'Kari Nord', 'contact_email': 'kari@example.com', 'contact_phone': '+47 98989898',
            'notes': ''})
        report = Report.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(str(report.period), '2026-10')
        detail = self.client.get(reverse('reports:report_detail', args=[report.pk]))
        self.assertEqual(detail.context['problems'], [])
        self.client.post(reverse('reports:report_submit', args=[report.pk]), {
            'submitted_at': '2026-11-03T09:30', 'channel': 'altinn', 'reference': 'AR1', 'version': str(report.version),
            'content_sha256': previewed(report)})
        report.refresh_from_db()
        self.assertEqual(report.status, 'submitted')
        self.assertEqual(report.snapshot.content['units'].popitem()[1]['species'][0]['species'], 'LUM')
        body = json.loads(self.client.get(reverse('reports:report_export', args=[report.pk, 'json'])).content)
        self.assertEqual(errors(body, 'RensefiskrapporteringDto'), [])
        csv = self.client.get(reverse('reports:report_export', args=[report.pk, 'csv'])).content.decode()
        self.assertIn('produksjonsenheter,[0].arter[0].uttak.antallAvlivetSykdom,50', csv)
        self.assertReportsAddUp()
        # A void of the records the filing read is told, not hidden.
        services.void(self.user, StockOperation.objects.get(movements__reason='sick'), 'Wrong batch')
        changed = self.client.get(reverse('reports:report_detail', args=[report.pk]))
        self.assertTrue(changed.context['differences']['figures'])
