"""The production plan end to end, through the real pages and services (the owner's requirement of 2026-11-26,
F:/dev/balik-notes/plan/production-plan/SPEC.md decisions 1–12): a protocol with an uneaten share made through its
form in both looks, assigned through the dialog, fish stocked and weighed, feedings recorded, the estimate between
weighings, a target set through its page, then the Production plans page, the growth plan and its file; and every way
the plan stops. Every number is worked out by hand in the comments, never read back from the code.

The fish: 10,000 salmon of 50 g in T-01, stocked 20 days ago (HarvestTestCase). The protocol: one band from 0 g, feed
GR-4, 4 meals, SFR 1 % of the body weight a day at 10 and at 12 °C, FCR 1.00 on the feed eaten, 20 % of the feed given
left uneaten. So every kilo given grows the fish by 0.8 kg, and a day's ration grows them by 0.8 %."""
import csv
import io
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import formats

from core.island_props import props_of
from core.models import AuditLog, PlatformSettings

from ..feeding import read as feeding_read
from ..harvest import forecast
from ..models import (
    FeedingProtocol, HandlingPlanItem, ProtocolAssignment, ProtocolBand, Site, StockMovement,
    WeightSource,
)
from ..stock import read as stock_read, services as stock_services
from .helpers import role, site_data
from .test_harvest import HarvestTestCase
from .test_protocols import PROTOCOL_KEEPER, ProtocolTestCase, table_data

D = Decimal
SETUP = ('view_site', 'change_site', 'view_platformsettings', 'change_platformsettings', 'view_weightsource',
         'add_weightsource', 'change_weightsource', 'delete_weightsource')


def shown(day):
    return formats.date_format(day, 'DATE_FORMAT')


class PlanTestCase(HarvestTestCase):
    """The protocol made and assigned through its pages, the fish weighed at 60 g ten days ago (a sample of 50 fish
    weighing 3 kg), 5 kg fed two days ago and 5 kg yesterday, the water at 10 °C."""

    look = ''          # '?ui=next' posts the same forms in the new look

    def setUp(self):
        super().setUp()
        self.user.groups.add(role('Protocol keeper', *PROTOCOL_KEEPER), role('Setup keeper', *SETUP))
        self.user = type(self.user).objects.get(pk=self.user.pk)       # its rights read again
        self.protocol = self.protocol_through_its_pages()
        self.assign_through_the_dialog(self.protocol)
        stock_services.record_weighing(self.user, unit=self.t1, batch=self.batch, day=self.day(10), sample_count=50,
                                       sample_weight_kg=D(3))                       # 3 kg ÷ 50 fish = 60 g
        ProtocolTestCase.water(self, '10')
        self.record(kilos='5', days_ago=2)
        self.record(kilos='5', days_ago=1)

    def band(self, **fields):
        return {'min_weight_g': '0', 'max_weight_g': '', 'feed': str(self.feed.pk), 'meals_per_day': '4',
                'expected_fcr': '', 'uneaten_pct': '', 'mortality_pct_month': '', 'sfr_100': '1', 'sfr_120': '1',
                **fields}

    def general(self, **fields):
        return {'name': 'Salmon plan', 'species': str(self.salmon.pk), 'status': 'draft', 'expected_fcr': '1.00',
                'uneaten_pct': '20', 'mortality_pct_month': '', 'notes': '', **fields}

    def protocol_through_its_pages(self, rows=None, **fields):
        """Created (a draft), its table saved, set active: the three steps a person takes, each through its address."""
        created = self.client.post(reverse('farm:feedingprotocol_create') + self.look, self.general(**fields),
                                   headers={'X-Modal': '1'})
        self.assertEqual(created.status_code, 204)
        protocol = FeedingProtocol.objects.get(name=fields.get('name', 'Salmon plan'))
        saved = self.client.post(reverse('farm:feedingprotocol_table', args=[protocol.pk]) + self.look,
                                 table_data(1, '10 12', rows or [self.band()]), headers={'X-Modal': '1'})
        self.assertEqual(saved.status_code, 204)
        active = self.client.post(reverse('farm:feedingprotocol_edit', args=[protocol.pk]) + self.look,
                                  {**self.general(**fields), 'status': 'active', 'version': '2'})
        self.assertEqual(active.status_code, 302)
        protocol.refresh_from_db()
        self.assertEqual(protocol.status, 'active')
        return protocol

    def assign_through_the_dialog(self, protocol, unit=None):
        response = self.client.post(reverse('farm:protocolassignment_create'), {
            'protocol': str(protocol.pk), 'units': [str((unit or self.t1).pk)], 'batch': '',
            'valid_from': self.day(15).isoformat(), 'valid_until': '', 'notes': ''}, headers={'X-Modal': '1'})
        self.assertEqual(response.status_code, 204)

    def set_target(self, grams, batch=None):
        response = self.client.post(reverse('farm:productionplan_create'), {
            'batch': str((batch or self.batch).pk), 'target_weight_g': grams, 'notes': ''})
        self.assertEqual(response.status_code, 302)

    def row(self, batch=None):
        rows = self.client.get(reverse('farm:productionplan_list'), {'ui': 'classic'}).context['objects']
        return next(row for row in rows if row['share'] is not None and row['share'].batch == (batch or self.batch))

    def growth_url(self, unit=None, batch=None):
        return reverse('farm:production_plan', args=[(unit or self.t1).pk, (batch or self.batch).pk])

    def file(self, **query):
        response = self.client.get(self.growth_url(), {**query, 'format': 'csv'})
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        return list(csv.reader(io.StringIO(response.content.decode())))


class GrowthPlanTests(PlanTestCase):
    def test_the_protocol_keeps_what_its_form_was_given_and_the_log_says_it(self):
        # Proves decision 1 (the uneaten share is entered on the protocol, 0–50 %) and "forms in both looks" (classic).
        protocol = self.protocol
        self.assertEqual((protocol.expected_fcr, protocol.uneaten_pct, protocol.mortality_pct_month,
                          protocol.interpolated_from), (D('1.00'), D('20.0'), None, None))
        band = ProtocolBand.objects.get(protocol=protocol)
        self.assertEqual((band.expected_fcr, band.uneaten_pct, band.mortality_pct_month), (None, None, None))
        created = AuditLog.objects.get(entity_type='feeding protocol', action='create')
        self.assertIn(created.changes['Uneaten feed (%)'][1], ('20', '20.0'))
        refused = self.client.post(reverse('farm:feedingprotocol_create'), self.general(name='Too much',
                                                                                        uneaten_pct='50.1'))
        self.assertIn('uneaten_pct', refused.context['form'].errors)
        refused = self.client.post(reverse('farm:feedingprotocol_create'), self.general(name='Too many',
                                                                                        mortality_pct_month='31'))
        self.assertIn('mortality_pct_month', refused.context['form'].errors)
        self.assertEqual(FeedingProtocol.objects.count(), 1)

    def test_the_estimate_between_weighings_grows_by_the_feed_eaten_only(self):
        # Proves decisions 1, 3 and 4: only recorded feedings grow the estimate, each by feed × (1 − uneaten) ÷ FCR.
        # 10,000 fish weighed at 60 g = 600 kg. Two days ago 5 kg given: 4 kg eaten ÷ FCR 1.00 = 4 kg → 604 kg, 60.4 g.
        # Yesterday 5 kg: 4 kg more → 608 kg, 60.8 g. The eight days without a recorded feeding add nothing.
        self.assertEqual(self.row()['forecast'].now_g, D('60.8'))
        self.assertContains(self.client.get(self.growth_url()), '10,000 fish at 60.8 g')

    def test_the_plans_page_says_the_day_the_feed_to_the_target_and_the_economic_fcr(self):
        # Proves decision 5 (the reach day, the feed needed, the economic FCR of the period) on Production plans.
        # From 60.8 g at 1 % a day, 20 % uneaten, FCR 1.00 (0.8 % growth a day), 10,000 fish:
        #   day 1: given 0.608 g a fish = 6.08 kg; eaten 4.864 kg; 61.2864 g
        #   day 2: given 0.612864 g = 6.12864 kg; eaten 4.902912 kg; 61.7766912 g
        #   day 3: given 0.617766912 g = 6.17766912 kg; eaten 4.942135296 kg; 62.2709047296 g ≥ 62 g: reached
        # Feed to the target 6.08 + 6.12864 + 6.17766912 = 18.38630912 kg; growth 14.709047296 kg; 18.386… ÷ 14.709… = 1.25
        self.set_target('62')
        found = self.row()['forecast']
        self.assertEqual((found.now_g, found.day, found.temperature_c), (D('60.8'), self.day(-3), D('10.0')))
        self.assertEqual((found.curve.feed_kg, found.curve.eaten_kg, found.curve.economic_fcr),
                         (D('18.38630912'), D('14.709047296'), D('1.25')))
        self.assertIn(f'date={self.day(-3).isoformat()}', self.row()['plan_harvest_url'])
        for look in ('classic', 'next'):
            page = self.client.get(reverse('farm:productionplan_list'), {'ui': look})
            said = page.content.decode() if look == 'classic' else str(props_of(page.content.decode(), 'list-page'))
            for text in (f'target on {shown(self.day(-3))}, at 10.0 °C held',
                         '18.39 kg of feed to the target · economic FCR 1.25', 'Growth plan'):
                self.assertIn(text, said, look)
            self.assertIn(self.growth_url(), said, look)

    def test_the_growth_plan_and_its_file_show_the_curve_a_day_at_a_time(self):
        # Proves decision 5 (the curve: date, weight, fish, biomass, feed that day and to date, eaten, uneaten, the FCR in
        # force; every day in the file) and decision 8 (computed on read: nothing of it is stored).
        self.set_target('62')
        today = self.today
        rows = self.file()
        self.assertEqual(rows[0], ['date', 'average_weight_g', 'fish', 'biomass_kg', 'feed_kg', 'feed_to_date_kg',
                                   'eaten_kg', 'uneaten_kg', 'fcr', 'economic_fcr', 'uneaten_pct', 'temperature_c',
                                   'fasting'])
        # the start, then the three days worked out above (biomass = weight × 10,000 ÷ 1000; uneaten = a fifth of the feed)
        self.assertEqual(rows[1:], [
            [today.isoformat(), '60.8000', '10000', '608.000', '', '0.000', '', '', '', '', '', '', ''],
            [(today + timedelta(days=1)).isoformat(), '61.2864', '10000', '612.864', '6.080', '6.080', '4.864', '1.216',
             '1.000', '1.250', '20.00', '10.0', ''],
            [(today + timedelta(days=2)).isoformat(), '61.7767', '10000', '617.767', '6.129', '12.209', '4.903', '1.226',
             '1.000', '1.250', '20.00', '10.0', ''],
            [(today + timedelta(days=3)).isoformat(), '62.2709', '10000', '622.709', '6.178', '18.386', '4.942', '1.236',
             '1.000', '1.250', '20.00', '10.0', ''],
        ])
        page = self.client.get(self.growth_url())
        for text in (f'Growth plan · T-01 · {self.batch.code}', f'Target 62.0 g: reached on {shown(self.day(-3))}.',
                     'Feed over these days: 18.39 kg given, 14.71 kg eaten, 3.68 kg uneaten; economic FCR of the period '
                     '1.25; 10,000 fish and 623 kg at the end.',
                     'Every day at 10.0 °C, the unit’s latest temperature at the start, held.',
                     'Today’s estimate', f'Stocked {shown(self.day(20))}', f'Weighed {shown(self.day(10))}',
                     'Manual sample', '50 fish weighed, 3.00 kg', 'Download every day (CSV)'):
            self.assertContains(page, text)
        # the page shows one day a week and the last day: here the last day only
        self.assertEqual([row['cells']['weight']['text'] for row in page.context['props']['table']['rows']], ['62.3 g'])

    def test_both_looks_draw_the_same_growth_plan(self):
        self.set_target('62')
        classic = self.client.get(self.growth_url(), {'ui': 'classic'})
        new = props_of(self.client.get(self.growth_url(), {'ui': 'next'}).content.decode(), 'list-page')
        self.assertEqual(new['lines'], classic.context['props']['lines'])
        self.assertEqual(new['table']['rows'], classic.context['props']['table']['rows'])
        self.assertEqual(new['sections'], classic.context['props']['sections'])
        for line in new['lines']:
            self.assertContains(classic, line)

    def test_without_a_target_the_plan_runs_its_horizon_and_the_page_shows_a_day_a_week(self):
        # Proves decision 8 (the horizon is the platform owner's reference data, not a constant) and the weekly rows.
        # Horizon 21 days through Platform settings: 21 daily rows in the file after the start; the page shows days 7, 14
        # and 21. Day 7: 60.8 × 1.008^7 = 64.2872… g (1.008^7 = 1.057359…).
        row = PlatformSettings.get()
        saved = self.client.post(reverse('core:platformsettings_edit', args=[row.pk]), {
            'correction_window_days': 31, 'clock_tolerance_seconds': 300, 'unknown_withdrawal_days': 180,
            'plan_horizon_days': 21, 'version': row.version})
        self.assertEqual(saved.status_code, 302)
        self.assertEqual(len(self.file()), 1 + 1 + 21)
        page = self.client.get(self.growth_url())
        self.assertContains(page, 'No target weight is set: the plan runs 21 days ahead.')
        rows = page.context['props']['table']['rows']
        self.assertEqual([row['cells']['date']['text'] for row in rows],
                         [shown(self.day(-7)), shown(self.day(-14)), shown(self.day(-21))])
        self.assertEqual(rows[0]['cells']['weight']['text'], '64.3 g')
        self.set_target('5000')                       # far away: not within 21 days, and the page says so
        self.assertEqual(self.row()['forecast'].why, 'Not reached within 21 days at this rate.')
        self.assertContains(self.client.get(self.growth_url()), 'Target 5,000 g: Not reached within 21 days at this rate.')
        refused = self.client.post(reverse('core:platformsettings_edit', args=[row.pk]), {
            'correction_window_days': 31, 'clock_tolerance_seconds': 300, 'unknown_withdrawal_days': 180,
            'plan_horizon_days': 6, 'version': PlatformSettings.get().version})
        self.assertIn('plan_horizon_days', refused.context['form'].errors)

    def test_a_fasting_day_ahead_gives_no_feed_and_no_growth(self):
        # A transport planned five days ahead asks for its fast (the rule's 24 h: the day before and the day). Without
        # it 62 g is reached on day 3 (above); set the target past day 3 to see the fast: 60.8 × 1.008^6 = 63.7770… g,
        # so 63.5 g takes six growing days: days 1, 2, 3, then the fast on days 4 and 5, then 6, 7, 8: reached on day 8.
        self.set_target('63.5')
        self.assertEqual(self.row()['forecast'].day, self.day(-6))
        HandlingPlanItem.objects.create(kind='transport', date=self.day(-5), unit=self.t1, batch=self.batch)
        self.assertEqual(self.row()['forecast'].day, self.day(-8))
        fasted = [row for row in self.file()[2:] if row[12] == 'yes']
        self.assertEqual([row[0] for row in fasted], [self.day(-4).isoformat(), self.day(-5).isoformat()])
        # nothing fed, nothing grown: the weight of day 3 (62.2709 g) stands, the feed to date too (18.386 kg)
        self.assertEqual([(row[1], row[4], row[5], row[8]) for row in fasted],
                         [('62.2709', '0.000', '18.386', ''), ('62.2709', '0.000', '18.386', '')])

    def test_the_plan_stops_where_the_ration_stops_and_says_why(self):
        self.set_target('62')
        # weight outside the bands: a second protocol whose only band ends at 61 g, assigned to the batch in T-01
        narrow = ProtocolTestCase.make_protocol(self, name='Narrow', bands=((0, 61, None),), columns=('10', '12'),
                                                sfr=(('1.00', '1.00'),))
        ProtocolAssignment.objects.create(protocol=narrow, unit=self.t1, batch=self.batch, valid_from=self.day(15))
        # the estimate now is read by Narrow (FCR 1.00, nothing uneaten): 60 g + 5 kg + 5 kg over 10,000 fish = 61 g,
        # which is the band's upper weight, not in it
        found = self.row()['forecast']
        self.assertEqual(found.now_g, D(61))
        self.assertEqual(found.why, '61.0 g is outside Narrow (0–61 g).')
        self.assertContains(self.client.get(self.growth_url()), 'Target 62.0 g: 61.0 g is outside Narrow (0–61 g).')
        ProtocolAssignment.objects.filter(protocol=narrow).delete()
        # no temperature: fish in T-02, fed by the same protocol, where no water was ever sampled
        other = self.stock(self.t2, count=1000, weight='55', days_ago=5)
        self.assign_through_the_dialog(self.protocol, unit=self.t2)
        self.set_target('70', batch=other)
        self.assertEqual(self.row(other)['forecast'].why, 'No temperature recorded here yet: record one.')
        self.assertContains(self.client.get(self.growth_url(self.t2, other)),
                            'Target 70.0 g: No temperature recorded here yet: record one.')
        # no protocol
        ProtocolAssignment.objects.all().delete()
        found = self.row()['forecast']
        self.assertEqual((found.now_g, found.why), (D(60), 'No protocol is assigned to these fish.'))
        self.assertEqual(self.file()[1:], [[self.today.isoformat(), '60.0000', '10000', '600.000', '', '0.000', '', '',
                                            '', '', '', '', '']])

    def test_an_assigned_protocol_is_fixed(self):
        # Proves decision 9: the new fields follow the rule of an assigned protocol.
        url = reverse('farm:feedingprotocol_edit', args=[self.protocol.pk])
        for field, value in (('uneaten_pct', '10'), ('mortality_pct_month', '2')):
            form = self.client.get(url).context['form']
            self.assertTrue(form.fields[field].disabled, field)
            self.protocol.refresh_from_db()
            self.client.post(url, {**self.general(status='active'), field: value, 'version': self.protocol.version})
            self.protocol.refresh_from_db()
            self.assertEqual((self.protocol.uneaten_pct, self.protocol.mortality_pct_month), (D('20.0'), None))
        self.protocol.uneaten_pct = D(10)
        with self.assertRaises(Exception) as caught:
            self.protocol.full_clean()
        self.assertEqual(caught.exception.message_dict['uneaten_pct'],
                         ['Fixed: the protocol is assigned. Duplicate it to change it.'])
        refused = self.client.post(reverse('farm:feedingprotocol_table', args=[self.protocol.pk]),
                                   table_data(self.protocol.version, '10 12', [self.band(uneaten_pct='5')]))
        self.assertEqual(refused.status_code, 422)
        self.assertIsNone(ProtocolBand.objects.get(protocol=self.protocol).uneaten_pct)
        page = self.client.get(url)
        for text in ('Uneaten feed', 'Economic FCR', 'Mortality a month', '1.25'):       # 1.00 ÷ 0.8
            self.assertContains(page, text)
        copy = self.client.post(reverse('farm:feedingprotocol_duplicate', args=[self.protocol.pk]))
        self.assertEqual(copy.status_code, 302)
        copied = FeedingProtocol.objects.get(name='Salmon plan (copy)')
        self.assertEqual((copied.uneaten_pct, copied.status, copied.interpolated_from), (D('20.0'), 'draft', None))


class NextLookFormTests(PlanTestCase):
    look = '?ui=next'

    def test_the_new_looks_forms_store_the_same_protocol_and_show_its_fields(self):
        # "Forms in both looks": the protocol of every test here was made by posting the new look's forms.
        self.assertEqual((self.protocol.uneaten_pct, self.protocol.status), (D('20.0'), 'active'))
        self.assertEqual(self.row()['forecast'].now_g, D('60.8'))
        draft = FeedingProtocol.objects.create(name='Draft', species=self.salmon, expected_fcr=D('1.10'))
        page = self.client.get(reverse('farm:feedingprotocol_edit', args=[draft.pk]), {'ui': 'next'}).content.decode()
        for text in ('uneaten_pct', 'mortality_pct_month', 'Uneaten feed (%)', 'Expected mortality (%/month)'):
            self.assertIn(text, page)
        fixed = self.client.get(reverse('farm:feedingprotocol_edit', args=[self.protocol.pk]), {'ui': 'next'})
        for text in ('Economic FCR', 'Mortality a month', 'Each band’s FCR and uneaten share sit at the middle'):
            self.assertIn(text, fixed.content.decode().replace('\\u2019', '’'))


class InterpolationTests(PlanTestCase):
    """Two bands, 0–100 g at FCR 1.00 and 100–200 g at FCR 1.50, nothing uneaten: the values sit at 50 g and 150 g, so
    fish of 100 g, on the edge, are read at 1.25, half way. 1,000 trout-sized salmon of 100 g in T-02, 1 % a day."""

    def setUp(self):
        super().setUp()
        self.two = self.protocol_through_its_pages(name='Two bands', uneaten_pct='', rows=[
            self.band(max_weight_g='100', expected_fcr='1.00'),
            self.band(min_weight_g='100', max_weight_g='200', expected_fcr='1.50')])
        self.big = self.stock(self.t2, count=1000, weight='100', days_ago=5)
        self.assign_through_the_dialog(self.two, unit=self.t2)
        ProtocolTestCase.water(self, '10', unit=self.t2)

    def test_the_fcr_is_read_between_the_bands_by_the_estimate_and_by_the_plan(self):
        # Proves decisions 2 and 3: one interpolation, used by the estimate between weighings and by the plan ahead.
        # Yesterday 1 kg fed to 100 kg of fish (the day's ration is 1 kg): at 100 g the FCR is 1.25, so 1 kg ÷ 1.25 =
        # 0.8 kg of growth → 100.8 g. A step table would read the 100–200 g band's 1.50: 100.667 g.
        self.record(kilos='1', days_ago=1, unit=self.t2)
        self.set_target('101.5', batch=self.big)
        found = self.row(self.big)['forecast']
        self.assertEqual(found.now_g, D('100.8'))
        # Ahead from 100.8 g: FCR = 1.00 + 0.50 × (100.8 − 50) ÷ 100 = 1.254; given 1.008 g a fish; growth 1.008 ÷ 1.254
        # = 0.80382… g → 101.6038… g ≥ 101.5 g on the first day.
        self.assertEqual(found.day, self.day(-1))
        first = found.curve.points[0]
        self.assertEqual(first.fcr, D('1.254'))
        self.assertEqual(first.weight_g, D('100.8') + D('1.008') / D('1.254'))
        self.assertEqual(first.feed_kg, D('1.008'))                              # 1,000 fish × 1.008 g

    def test_a_protocol_that_fed_before_the_interpolation_keeps_its_bands_fcr_for_those_days(self):
        # Proves decision 9: a protocol that existed when the interpolation landed (the migration writes the day) keeps
        # its step FCR for the days before it, and is read between the bands from that day on.
        FeedingProtocol.objects.filter(pk=self.two.pk).update(interpolated_from=self.today)
        self.record(kilos='1', days_ago=1, unit=self.t2)
        self.set_target('101.5', batch=self.big)
        found = self.row(self.big)['forecast']
        # yesterday, before the day: the 100–200 g band's own 1.50: 1 kg ÷ 1.50 = 0.6667 kg → 100.6667 g
        self.assertAlmostEqual(found.now_g, D(100) + D(1000) / D('1.50') / 1000, places=20)
        # ahead, from the day on: between the bands, 1.00 + 0.50 × (100.6667 − 50) ÷ 100 = 1.25333…
        self.assertAlmostEqual(found.curve.points[0].fcr, D(1) + D('0.5') * (found.now_g - 50) / 100, places=20)
        self.assertNotEqual(found.curve.points[0].fcr, D('1.50'))
        for look in ('classic', 'next'):
            page = self.client.get(reverse('farm:feedingprotocol_edit', args=[self.two.pk]), {'ui': look})
            self.assertIn(f'Until {shown(self.today)} this protocol', page.content.decode(), look)


class MortalityAndTemperatureTests(PlanTestCase):
    def test_expected_mortality_lowers_the_fish_and_the_feed_never_the_average_weight(self):
        # Proves decision 6. A second protocol like the first with 10 % mortality a month on its band, made through the
        # pages, assigned to the batch in T-01 (the more specific row wins). 30 days ahead: 10,000 × 0.9 = 9,000 fish;
        # the average is the same as without mortality: 60.8 × 1.008^30.
        dying = self.protocol_through_its_pages(name='With mortality', rows=[self.band(mortality_pct_month='10')])
        plain = self.file()
        ProtocolAssignment.objects.create(protocol=dying, unit=self.t1, batch=self.batch, valid_from=self.day(15))
        rows = self.file()
        self.assertEqual(rows[1][2], '10000')
        self.assertEqual(rows[1 + 30][2], '9000')
        self.assertEqual([row[1] for row in rows], [row[1] for row in plain])          # the same weights, every day
        self.assertEqual(rows[2][4], plain[2][4])                                     # the first day feeds every fish
        self.assertLess(D(rows[1 + 30][4]), D(plain[1 + 30][4]))                      # then fewer fish eat less
        self.assertAlmostEqual(D(rows[1 + 30][3]), D(rows[1 + 30][1]) * 9, delta=D('0.01'))     # 9,000 fish, in kg
        band = ProtocolBand.objects.get(protocol=dying)
        self.assertEqual(band.mortality_pct_month, D('10.00'))
        log = AuditLog.objects.filter(entity_type='feeding protocol', action='update')
        self.assertTrue(any('mortality 10 % a month' in str(row.changes.get('Feeding table')) for row in log))

    def test_the_sites_monthly_temperatures_are_read_when_all_twelve_are_set(self):
        # Proves decision 7: the default is today's temperature held, and said; a site's twelve monthly temperatures are
        # used when set, and the page says which. All twelve at 11 °C (between the 10 and 12 °C columns: SFR 1 %).
        self.set_target('62')
        site = self.t1.production_department.site
        url = reverse('farm:site_edit', args=[site.pk])
        data = site_data(name=site.name, code=site.code, timezone=site.timezone, country='', region='',
                         version=site.version)
        months = {f'plan_temperature_{month:02d}': '11' for month in range(1, 13)}
        half = self.client.post(url, {**data, **dict(list(months.items())[:6])})
        self.assertEqual(half.context['form'].errors['plan_temperature_07'],
                         ['Give the water temperature of all twelve months, or of none.'])
        hot = self.client.post(url, {**data, **months, 'plan_temperature_03': '41'})
        self.assertIn('plan_temperature_03', hot.context['form'].errors)
        self.assertContains(self.client.get(reverse('farm:productionplan_list')), 'at 10.0 °C held')
        self.assertEqual(self.client.post(url, {**data, **months}).status_code, 302)
        self.assertEqual(Site.objects.get(pk=site.pk).plan_temperatures(), (D('11.0'),) * 12)
        found = self.row()['forecast']
        self.assertEqual((found.day, found.monthly, found.temperature_c), (self.day(-3), True, None))
        self.assertContains(self.client.get(reverse('farm:productionplan_list')),
                            f'target on {shown(self.day(-3))}, at the site’s monthly temperatures')
        self.assertContains(self.client.get(self.growth_url()),
                            'Every day at the site’s water temperature of its month (Setup › Sites).')
        self.assertEqual(self.file()[2][11], '11.0')


class PlannedAgainstActualTests(PlanTestCase):
    """Decisions 10–12. Beside the base case: 5 kg fed seven days ago and a second weighing five days ago at 62 g; the
    site's months all at 10 °C, so the plan from a past start reads a temperature whatever was sampled then."""

    def setUp(self):
        super().setUp()
        self.record(kilos='5', days_ago=7)
        stock_services.record_weighing(self.user, unit=self.t1, batch=self.batch, day=self.day(5), avg_weight_g=D(62))
        Site.objects.filter(pk=self.t1.production_department.site_id).update(
            **{f'plan_temperature_{month:02d}': D('10.0') for month in range(1, 13)})

    def plan(self, start=None):
        unit = type(self.t1).objects.select_related('production_department__site').get(pk=self.t1.pk)
        share = stock_read.stock_of([unit])[unit.pk].counted[0]
        return forecast.plan(unit, share, D(70), start)

    def test_the_measured_points_are_read_one_way_with_their_source_and_sample(self):
        # Proves decision 11: one reader of the measured points, each weighing with its source (reference data) and
        # its sample where it has one; a stocking has no source.
        points = self.plan().measured
        self.assertEqual([(item.point.kind, item.point.day, item.point.fish, item.point.avg_weight_g)
                          for item in points],
                         [('start', self.day(20), 10000, D(50)), ('weighing', self.day(10), 10000, D(60)),
                          ('weighing', self.day(5), 10000, D(62))])
        manual = WeightSource.manual()
        self.assertEqual([(item.point.source, item.point.sample_count, item.point.sample_weight_kg) for item in points],
                         [(None, None, None), (manual, 50, D('3.0000')), (manual, None, None)])
        self.assertEqual(set(StockMovement.objects.filter(kind='weighing').values_list('weight_source__code', flat=True)),
                         {'manual'})
        self.assertFalse(StockMovement.objects.exclude(kind='weighing').filter(weight_source__isnull=False).exists())
        projection = feeding_read.project([self.t1.pk], [(self.t1.pk, self.today)])
        self.assertEqual([point.day for point in feeding_read.measured_points(projection, self.t1.pk, self.batch.pk)],
                         [item.point.day for item in points])

    def test_each_weighing_is_set_beside_the_estimate_it_replaced_and_the_realised_fcr(self):
        # Proves decision 10. The weighing five days ago: estimated 60 g + (5 kg × 0.8 ÷ 1.00) ÷ 10,000 fish = 60.4 g;
        # measured 62 g: +1.6 g, +2.649 % of 60.4. Realised bFCR since the weighing before it: 5 kg fed ÷ (620 − 600 kg
        # gained) = 0.25; expected on the feed given: 5 kg ÷ 4 kg = 1.25.
        correction = self.plan().measured[2].point.correction
        self.assertEqual((correction.estimated_g, correction.measured_g, correction.difference_g),
                         (D('60.4'), D(62), D('1.6')))
        self.assertEqual((correction.realised_fcr, correction.expected_fcr), (D('0.25'), D('1.25')))
        page = self.client.get(self.growth_url())
        for text in ('Measured against the plan', 'Estimated before it', 'Planned that day', 'FCR realised · expected',
                     '60.4 g', '+1.6 g · +2.6 %', '0.25 · 1.25'):
            self.assertContains(page, text)

    def test_the_plan_from_a_measured_point_says_where_it_would_have_been(self):
        # Proves decisions 10 and 12: the plan from the weighing ten days ago (60 g, 10,000 fish), every day's ration
        # given: 0.8 % a day. Five days on: 60 × 1.008^5 = 60 × 1.040645140512768 = 62.43870843076608 g; measured
        # that day 62 g: −0.43870843076608 g. The plan re-anchors at each measured point: today's estimate starts
        # from the 62 g measured, 62 g + 0.8 g (two feedings of 5 kg since: 8 kg eaten ÷ 10,000) = 62.8 g.
        found = self.plan(self.day(10))
        self.assertEqual((found.chosen.day, found.forecast.start, found.forecast.now_g, found.forecast.fish),
                         (self.day(10), self.day(10), D(60), 10000))
        against = found.measured[2]
        self.assertEqual(against.planned_g, D('62.43870843076608'))
        self.assertEqual(against.difference_g, D('-0.43870843076608'))
        self.assertEqual([item.planned_g for item in found.measured[:2]], [None, None])      # on or before the start
        self.assertEqual(self.plan().forecast.now_g, D('62.8'))
        page = self.client.get(self.growth_url(), {'from': self.day(10).isoformat()})
        for text in (f'10,000 fish at 60.0 g on {shown(self.day(10))} (Weighed {shown(self.day(10))}).',
                     '62.4 g', '−0.4 g · −0.7 %'):
            self.assertContains(page, text)
        self.assertEqual(self.file(**{'from': self.day(10).isoformat()})[1][:3],
                         [self.day(10).isoformat(), '60.0000', '10000'])
        # from the stocking: 50 × 1.008^10 = 54.147… g on the first weighing's day, where 60 g was measured
        stocked = self.plan(self.day(20))
        self.assertAlmostEqual(stocked.measured[1].planned_g, D(50) * D('1.008') ** 10, places=15)
        # a day that is no measured point, or outside the stay, is today's estimate
        for day in (self.day(8), self.day(300), self.today):
            self.assertIsNone(self.plan(day).chosen)
        self.assertEqual(self.client.get(self.growth_url(), {'from': 'nonsense'}).status_code, 200)

    def test_another_source_is_one_more_row_of_reference_data_and_no_second_path(self):
        # Proves decision 11: a camera is a new weight source made through the tab; a weighing naming it is read by the
        # same reader. Nothing else is needed (no camera code).
        created = self.client.post(reverse('farm:weightsource_create'), {
            'name': 'Biomass camera', 'code': 'camera', 'notes': 'Stereo camera in the unit.'})
        self.assertEqual(created.status_code, 302)
        camera = WeightSource.objects.get(code='camera')
        listed = self.client.get(reverse('farm:weightsource_list'))
        for text in ('Manual sample', 'Biomass camera', 'Weight sources'):
            self.assertContains(listed, text)
        form = self.client.get(reverse('farm:stock_weighing', args=[self.t1.pk]), headers={'X-Modal': '1'})
        self.assertContains(form, 'Weight source')                          # asked once there is more than one
        stock_services.record_weighing(self.user, unit=self.t1, batch=self.batch, day=self.day(3), avg_weight_g=D(63),
                                       source=camera)
        point = self.plan().measured[-1].point
        self.assertEqual((point.day, point.avg_weight_g, point.source), (self.day(3), D(63), camera))
        self.assertContains(self.client.get(self.growth_url()), 'Biomass camera')
        self.assertTrue(any('by Biomass camera' in str(row.changes) for row in AuditLog.objects.all()))
        # the seeded source and a source weighings name are kept
        for source in (WeightSource.manual(), camera):
            self.client.post(reverse('farm:weightsource_delete', args=[source.pk]))
            self.assertFalse(WeightSource.all_objects.get(pk=source.pk).is_deleted)
        spare = WeightSource.objects.create(name='Spare', code='spare')
        self.client.post(reverse('farm:weightsource_edit', args=[spare.pk]),
                         {'name': 'Spare scale', 'code': 'other', 'notes': '', 'version': '1'})
        spare.refresh_from_db()
        self.assertEqual((spare.name, spare.code), ('Spare scale', 'spare'))        # its code is chosen once
        self.client.post(reverse('farm:weightsource_delete', args=[spare.pk]))
        self.assertTrue(WeightSource.all_objects.get(pk=spare.pk).is_deleted)

    def test_the_page_needs_the_plans_right_and_a_batch_in_the_unit(self):
        self.assertEqual(self.client.get(self.growth_url(unit=self.t2)).status_code, 404)
        self.user.groups.clear()
        self.user.user_permissions.clear()
        self.assertEqual(self.client.get(self.growth_url()).status_code, 403)
        self.assertEqual(self.client.get(self.growth_url(), {'format': 'csv'}).status_code, 403)
