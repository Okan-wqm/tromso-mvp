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
from pathlib import Path

from django.test import override_settings
from django.urls import reverse
from django.utils import formats, timezone

from core.island_props import props_of
from core.models import AuditLog, PlatformSettings

from ..feeding import read as feeding_read
from ..harvest import forecast
from ..models import (
    FeedingProtocol, HandlingPlanItem, ProtocolAssignment, ProtocolBand, ProtocolRate, StockMovement,
    TemperatureProfile, TemperatureProfileAssignment, TemperatureProfilePoint, WeightSource,
)
from ..stock import read as stock_read, services as stock_services
from .helpers import recorded_at, role, rows_data
from .test_harvest import HarvestTestCase
from .test_protocols import PROTOCOL_KEEPER, ProtocolTestCase, table_data
from .test_stock import make_unit

D = Decimal
# the new look's pages are drawn with the islands' manifest the other page tests use (no browser build in a test run)
MANIFEST = str(Path(__file__).resolve().parents[2] / 'core' / 'testdata' / 'islands-prodrest-manifest.json')
SETUP = ('view_platformsettings', 'change_platformsettings', 'view_weightsource', 'add_weightsource',
         'change_weightsource', 'delete_weightsource', 'view_temperatureprofile', 'add_temperatureprofile',
         'change_temperatureprofile', 'delete_temperatureprofile', 'view_temperatureprofileassignment',
         'add_temperatureprofileassignment', 'change_temperatureprofileassignment',
         'delete_temperatureprofileassignment')


def shown(day):
    return formats.date_format(day, 'DATE_FORMAT')


@override_settings(ISLANDS_MANIFEST=MANIFEST)
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

    def profile_through_its_pages(self, name, points, between='smooth', look=None):
        """A temperature profile created (a draft), its points saved and set active, each through its address, in the
        classic look or (`look`='?ui=next') the new one. `points`: [(weight g, temperature °C)] as typed."""
        look = self.look if look is None else look
        general = {'name': name, 'species': str(self.salmon.pk), 'status': 'draft', 'temperature_between': between,
                   'notes': ''}
        created = self.client.post(reverse('farm:temperatureprofile_create') + look, general)
        self.assertEqual(created.status_code, 302)
        profile = TemperatureProfile.objects.get(name=name)
        saved = self.client.post(reverse('farm:temperatureprofile_points', args=[profile.pk]) + look, rows_data(
            'points', [{'weight_g': weight, 'temperature_c': temperature} for weight, temperature in points],
            record=profile))
        self.assertEqual(saved.status_code, 302)
        active = self.client.post(reverse('farm:temperatureprofile_edit', args=[profile.pk]) + look,
                                  {**general, 'status': 'active', 'version': str(TemperatureProfile.objects.get(
                                      pk=profile.pk).version)})
        self.assertEqual(active.status_code, 302)
        profile.refresh_from_db()
        self.assertEqual(profile.status, 'active')
        return profile

    def assign_profile(self, profile, unit=None, batch=None, days_ago=15):
        response = self.client.post(reverse('farm:temperatureprofileassignment_create'), {
            'profile': str(profile.pk), 'units': [str(unit.pk)] if unit else [], 'batch': str(batch.pk) if batch else '',
            'valid_from': self.day(days_ago).isoformat(), 'valid_until': '', 'notes': ''}, headers={'X-Modal': '1'})
        self.assertEqual(response.status_code, 204)

    def recorded_back(self, days_ago):
        """Every row as made `days_ago` (a farm's rows were made when they were, not on the test's day): their versions
        (core.versions). A plan from a past start reads only the rows recorded by then, as they were then (decision 12)."""
        recorded_at(timezone.now() - timedelta(days=days_ago))

    def set_target(self, grams, batch=None):
        response = self.client.post(reverse('farm:productionplan_create'), {
            'batch': str((batch or self.batch).pk), 'target_weight_g': grams, 'notes': ''})
        self.assertEqual(response.status_code, 302)

    def row(self, batch=None):
        rows = self.client.get(reverse('farm:productionplan_list'), {'ui': 'classic'}).context['objects']
        return next(row for row in rows if row['share'] is not None and row['share'].batch == (batch or self.batch))

    def growth_url(self, unit=None, batch=None):
        return reverse('farm:production_plan', args=[(unit or self.t1).pk, (batch or self.batch).pk])

    def file(self, unit=None, **query):
        response = self.client.get(self.growth_url(unit), {**query, 'format': 'csv'})
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        return list(csv.reader(io.StringIO(response.content.decode())))


class GrowthPlanTests(PlanTestCase):
    def test_the_protocol_keeps_what_its_form_was_given_and_the_log_says_it(self):
        # Proves decision 1 (the uneaten share is entered on the protocol, 0–50 %) and "forms in both looks" (classic).
        protocol = self.protocol
        self.assertEqual((protocol.expected_fcr, protocol.uneaten_pct, protocol.mortality_pct_month,
                          protocol.fcr_between), (D('1.00'), D('20.0'), None, 'smooth'))
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
        # no fish die: the economic FCR (feed ÷ biomass gained: 622.709 kg − 608 kg = 14.709 kg) is the FCR on feed given
        self.assertEqual((found.curve.feed_kg, found.curve.eaten_kg, found.curve.fcr_on_feed_given,
                          found.curve.economic_fcr), (D('18.38630912'), D('14.709047296'), D('1.25'), D('1.25')))
        self.assertIn(f'date={self.day(-3).isoformat()}', self.row()['plan_harvest_url'])
        for look in ('classic', 'next'):
            page = self.client.get(reverse('farm:productionplan_list'), {'ui': look})
            said = page.content.decode() if look == 'classic' else str(props_of(page.content.decode(), 'list-page'))
            for text in (f'target on {shown(self.day(-3))}, at 10.0 °C held',
                         '18.39 kg of feed to the target · FCR on feed given 1.25 · economic FCR 1.25', 'Growth plan'):
                self.assertIn(text, said, look)
            self.assertIn(self.growth_url(), said, look)

    def test_the_growth_plan_and_its_file_show_the_curve_a_day_at_a_time(self):
        # Proves decision 5 (the curve: date, weight, fish, biomass, feed that day and to date, eaten, uneaten, the FCR in
        # force; every day in the file) and decision 8 (computed on read: nothing of it is stored).
        self.set_target('62')
        today = self.today
        rows = self.file()
        self.assertEqual(rows[0], ['date', 'average_weight_g', 'fish', 'biomass_kg', 'feed_kg', 'feed_to_date_kg',
                                   'eaten_kg', 'uneaten_kg', 'fcr', 'fcr_on_feed_given', 'uneaten_pct', 'temperature_c',
                                   'temperature_source', 'fasting'])
        # the start, then the three days worked out above (biomass = weight × 10,000 ÷ 1000; uneaten = a fifth of the feed)
        self.assertEqual(rows[1:], [
            [today.isoformat(), '60.8000', '10000', '608.000', '', '0.000', '', '', '', '', '', '', '', ''],
            [(today + timedelta(days=1)).isoformat(), '61.2864', '10000', '612.864', '6.080', '6.080', '4.864', '1.216',
             '1.000', '1.250', '20.00', '10.0', 'measured, held', ''],
            [(today + timedelta(days=2)).isoformat(), '61.7767', '10000', '617.767', '6.129', '12.209', '4.903', '1.226',
             '1.000', '1.250', '20.00', '10.0', 'measured, held', ''],
            [(today + timedelta(days=3)).isoformat(), '62.2709', '10000', '622.709', '6.178', '18.386', '4.942', '1.236',
             '1.000', '1.250', '20.00', '10.0', 'measured, held', ''],
        ])
        page = self.client.get(self.growth_url())
        for text in (f'Growth plan · T-01 · {self.batch.code}', f'Target 62.0 g: reached on {shown(self.day(-3))}.',
                     'Feed over these days: 18.39 kg given, 14.71 kg eaten, 3.68 kg uneaten; FCR on feed given of the period '
                     '1.25, economic FCR 1.25; 10,000 fish and 623 kg at the end.',
                     'Economic FCR, as the industry says it: the feed given divided by the biomass gained',
                     'Every day without a temperature profile at 10.0 °C, the unit’s latest measured temperature at '
                     'the start, held.',
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
            'sensor_day_hours': 20, 'sensor_hold_seconds': 3600, 'assumption_cap_days': 7, 'probe_sample_tolerance_c': '1.0',
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
            'sensor_day_hours': 20, 'sensor_hold_seconds': 3600, 'assumption_cap_days': 7, 'probe_sample_tolerance_c': '1.0',
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
        fasted = [row for row in self.file()[2:] if row[13] == 'yes']
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
                                            '', '', '', '', '', '']])

    def test_an_assigned_protocol_is_fixed(self):
        # Proves decision 9: the new fields follow the rule of an assigned protocol.
        url = reverse('farm:feedingprotocol_edit', args=[self.protocol.pk])
        for field, value in (('uneaten_pct', '10'), ('mortality_pct_month', '2'), ('sfr_between', 'step')):
            form = self.client.get(url).context['form']
            self.assertTrue(form.fields[field].disabled, field)
            self.protocol.refresh_from_db()
            self.client.post(url, {**self.general(status='active'), field: value, 'version': self.protocol.version})
            self.protocol.refresh_from_db()
            self.assertEqual((self.protocol.uneaten_pct, self.protocol.mortality_pct_month,
                              self.protocol.sfr_between), (D('20.0'), None, 'smooth'))
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
        for text in ('Uneaten feed', 'FCR on feed given', 'Mortality a month', '1.25'):  # 1.00 ÷ 0.8
            self.assertContains(page, text)
        copy = self.client.post(reverse('farm:feedingprotocol_duplicate', args=[self.protocol.pk]))
        self.assertEqual(copy.status_code, 302)
        copied = FeedingProtocol.objects.get(name='Salmon plan (copy)')
        self.assertEqual((copied.uneaten_pct, copied.status, copied.sfr_between), (D('20.0'), 'draft', 'smooth'))


class NextLookFormTests(PlanTestCase):
    look = '?ui=next'

    def test_the_new_looks_forms_store_the_same_protocol_and_show_its_fields(self):
        # "Forms in both looks": the protocol of every test here was made by posting the new look's forms.
        self.assertEqual((self.protocol.uneaten_pct, self.protocol.status), (D('20.0'), 'active'))
        self.assertEqual(self.row()['forecast'].now_g, D('60.8'))
        draft = FeedingProtocol.objects.create(name='Draft', species=self.salmon, expected_fcr=D('1.10'))
        page = self.client.get(reverse('farm:feedingprotocol_edit', args=[draft.pk]), {'ui': 'next'}).content.decode()
        for text in ('uneaten_pct', 'mortality_pct_month', 'Uneaten feed (%)', 'Expected mortality (%/month)',
                     'sfr_between', 'Step at the band edge'):
            self.assertIn(text, page)
        fixed = self.client.get(reverse('farm:feedingprotocol_edit', args=[self.protocol.pk]), {'ui': 'next'})
        for text in ('FCR on feed given', 'Mortality a month', 'Each band’s FCR, uneaten share and SFR sit at the middle'):
            self.assertIn(text, fixed.content.decode().replace('\\u2019', '’'))


class BetweenBandsTests(PlanTestCase):
    """Two bands, 0–100 g (FCR 1.00, SFR 1 %) and 100–200 g (FCR 1.50, SFR 2 %), nothing uneaten: the values sit at 50 g
    and 150 g, so fish of 100 g, on the edge, are read half way under the smooth rule: FCR 1.25, SFR 1.5 %. 1,000 salmon
    of 100 g in T-02."""

    def two_bands(self, name='Two bands', **rules):
        made = self.protocol_through_its_pages(name=name, uneaten_pct='', rows=[
            self.band(max_weight_g='100', expected_fcr='1.00'),
            self.band(min_weight_g='100', max_weight_g='200', expected_fcr='1.50', sfr_100='2', sfr_120='2')], **rules)
        self.big = self.stock(self.t2, count=1000, weight='100', days_ago=5)
        self.assign_through_the_dialog(made, unit=self.t2)
        ProtocolTestCase.water(self, '10', unit=self.t2)
        self.record(kilos='1', days_ago=1, unit=self.t2)
        self.set_target('101.5', batch=self.big)
        return made

    def test_smooth_reads_the_fcr_and_the_sfr_between_the_bands_in_the_estimate_and_in_the_plan(self):
        # Proves decisions 2, 3 and 13: one interpolation, used by the estimate between weighings and by the plan ahead,
        # for the FCR and for the SFR. A protocol made through its form is smooth unless its maker says otherwise.
        made = self.two_bands()
        self.assertEqual((made.fcr_between, made.uneaten_between, made.sfr_between), ('smooth',) * 3)
        # Yesterday 1 kg fed to 100 kg of fish (under the day's ration of 1.5 kg): at 100 g the FCR is 1.25, so
        # 1 kg ÷ 1.25 = 0.8 kg of growth → 100.8 g.
        found = self.row(self.big)['forecast']
        self.assertEqual(found.now_g, D('100.8'))
        # Ahead from 100.8 g: FCR = 1.00 + 0.50 × (100.8 − 50) ÷ 100 = 1.254; SFR = 1 + 1 × 50.8 ÷ 100 = 1.508 %:
        # given 100.8 × 1.508 ÷ 100 = 1.5200640 g a fish (1.520064 kg for the 1,000); growth 1.520064 ÷ 1.254 = 1.2122 g
        # → 102.0122 g ≥ 101.5 g on the first day.
        self.assertEqual(found.day, self.day(-1))
        first = found.curve.points[0]
        self.assertEqual((first.fcr, first.feed_kg), (D('1.254'), D('1.520064')))
        self.assertEqual(first.weight_g, D('100.8') + D('1.520064') / D('1.254'))

    def test_step_is_the_table_as_it_always_was(self):
        # Proves decision 14 (the rule is the person's, per quantity) and that "step" gives the numbers the table gave
        # before: the 100–200 g band's own FCR 1.50 and SFR 2 %. Yesterday: 1 kg ÷ 1.50 = 0.6667 kg → 100.6667 g.
        made = self.two_bands(fcr_between='step', uneaten_between='step', sfr_between='step')
        self.assertEqual((made.fcr_between, made.uneaten_between, made.sfr_between), ('step',) * 3)
        found = self.row(self.big)['forecast']
        self.assertAlmostEqual(found.now_g, D(100) + D(1000) / D('1.50') / 1000, places=20)
        first = found.curve.points[0]
        self.assertEqual(first.fcr, D('1.50'))
        self.assertAlmostEqual(first.feed_kg, found.now_g * 2 / 100, places=20)        # 2 % of 1,000 fish, in kg
        refused = self.client.post(reverse('farm:feedingprotocol_create'), self.general(name='Other', fcr_between='x'))
        self.assertIn('fcr_between', refused.context['form'].errors)

    def test_the_protocol_page_shows_the_values_the_plan_uses_in_both_looks(self):
        # Proves decision 14: the page shows, per weight, the FCR, the uneaten share and the SFR at each temperature
        # column actually used, the entered band values marked; and they are the plan's own readings.
        made = self.two_bands()
        url = reverse('farm:feedingprotocol_edit', args=[made.pk])
        classic = self.client.get(url, {'ui': 'classic'})
        used = classic.context['used']
        said = [[row['cells'][key]['text'] for key in ('point', 'fcr', 'uneaten', 't0', 't1')]
                for row in used['rows']]
        self.assertEqual([row['cells']['weight']['text'] for row in used['rows']][1:], ['50.0 g', '100 g', '150 g'])
        # 0 g and 50 g: the first band's own; 100 g, the edge: half way; 150 g: the second band's own
        self.assertEqual(said, [
            ['the band’s lower weight', '1.00', '0.0 %', '1.000 %', '1.000 %'],
            ['entered for the band', '1.00', '0.0 %', '1.000 %', '1.000 %'],
            ['the band’s lower weight', '1.25', '0.0 %', '1.500 %', '1.500 %'],
            ['entered for the band', '1.50', '0.0 %', '2.000 %', '2.000 %'],
        ])
        for text in ('Values used over the fish’s weight', 'entered for the band',
                     'FCR: Smooth between bands · uneaten feed: Smooth between bands · SFR: Smooth between bands',
                     'The protocol is assigned, so its table is fixed'):
            self.assertContains(classic, text)
        new = self.client.get(url, {'ui': 'next'}).content.decode().replace('\u2019', '’').replace('\u00b7', '·')
        for text in ('Values used over the fish', 'entered for the band', '1.500 %', 'Smooth between bands'):
            self.assertIn(text, new)
        # the plan's first day reads the very function the page's rows were made by
        from ..feeding.read import tables
        table = tables([made.pk])[made.pk]
        first = self.row(self.big)['forecast'].curve.points[0]
        self.assertEqual(first.fcr, table.fcr_at(D('100.8')))
        self.assertEqual(first.feed_kg, D('100.8') * table.sfr_at(D('100.8'), D('10.0')).value / 100)
        # an assigned protocol's rules are fixed, and a copy's can be changed
        form = classic.context['form']
        self.assertTrue(all(form.fields[name].disabled for name in ('fcr_between', 'uneaten_between', 'sfr_between')))
        self.client.post(reverse('farm:feedingprotocol_duplicate', args=[made.pk]))
        copy = FeedingProtocol.objects.get(name='Two bands (copy)')
        changed = self.client.post(reverse('farm:feedingprotocol_edit', args=[copy.pk]), {
            **self.general(name='Two bands (copy)', uneaten_pct=''), 'sfr_between': 'step', 'fcr_between': 'smooth',
            'uneaten_between': 'smooth', 'version': copy.version})
        self.assertEqual(changed.status_code, 302)
        copy.refresh_from_db()
        self.assertEqual((copy.fcr_between, copy.sfr_between), ('smooth', 'step'))
        shown = self.client.get(reverse('farm:feedingprotocol_edit', args=[copy.pk])).context['used']['rows'][2]['cells']
        self.assertEqual((shown['fcr']['text'], shown['t0']['text']), ('1.25', '2.000 %'))     # at 100 g: its own band's SFR


class MortalityTests(PlanTestCase):
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



class TemperatureProfileTests(PlanTestCase):
    """Owner decisions 15–19, end to end. The 10,000 fish of 50 g in T-01 are graded five days ago: 4,000 of 60 g go to
    T-02, the 6,000 that stay weigh 40 g. One protocol feeds the whole batch wherever it is ("Two-column plan": one band,
    SFR 1 % at 10 °C and 2 % at 12 °C, FCR 1.00, nothing uneaten), so the SFR rises 0.5 % a degree. Two profiles: "Hall
    A" (0 g 10 °C, 100 g 12 °C, smooth: 10 + 0.02 × weight) on unit T-01, made in the classic look; "Batch plan" (0 g
    10 °C, 50 g 12 °C, a step) on the whole batch, made in the new look. T-02 has no water sample at all."""

    def setUp(self):
        HarvestTestCase.setUp(self)                     # not the base case's protocol on T-01: this one's own
        self.user.groups.add(role('Protocol keeper', *PROTOCOL_KEEPER), role('Setup keeper', *SETUP))
        self.user = type(self.user).objects.get(pk=self.user.pk)
        self.protocol = self.protocol_through_its_pages(name='Two-column plan', uneaten_pct='', rows=[
            self.band(sfr_100='1', sfr_120='2')])
        response = self.client.post(reverse('farm:protocolassignment_create'), {
            'protocol': str(self.protocol.pk), 'batch': str(self.batch.pk), 'valid_from': self.day(15).isoformat(),
            'valid_until': '', 'notes': ''}, headers={'X-Modal': '1'})
        self.assertEqual(response.status_code, 204)
        stock_services.record_grading(self.user, source=self.t1, batch=self.batch, day=self.day(5),
                                      outputs=[(self.t2, 4000, D(60), 'Large')], remainder_avg_weight_g=D(40))
        PlatformSettings.objects.update(plan_horizon_days=7)

    def profiles(self):
        hall = self.profile_through_its_pages('Hall A', [('0', '10'), ('100', '12')])
        planned = self.profile_through_its_pages('Batch plan', [('0', '10'), ('50', '12')], between='step',
                                                 look='?ui=next')
        self.assign_profile(hall, unit=self.t1)
        self.assign_profile(planned, batch=self.batch)
        return hall, planned

    def test_after_a_grading_each_part_follows_its_own_profile_by_hand(self):
        # Proves decisions 15 (a profile made in both looks), 16 (assigned to a unit and to a batch, the most specific
        # row wins), 17 (the temperature of a day ahead is the profile's at the projected weight), 18 (SFR bilinear,
        # feed, eaten, growth), 19 (each part of the graded batch follows the row resolved for its own place) and 20
        # (the service's projection gives the same days).
        # Before any profile: T-02 holds no temperature measured, so its plan stops and says why.
        self.assertContains(self.client.get(self.growth_url(self.t2)),
                            'No temperature recorded here yet: record one.')
        hall, planned = self.profiles()
        self.assertEqual((hall.temperature_between, planned.temperature_between), ('smooth', 'step'))
        # T-01, 6,000 fish of 40 g, read by Hall A (its unit's row beats the batch's):
        #   day 1: 10 + 0.02 × 40 = 10.8 °C; SFR 1 + 0.8 × 0.5 = 1.4 %; 40 × 0.014 = 0.56 g a fish, 3.36 kg;
        #          growth 0.56 g → 40.56 g; biomass 6,000 × 40.56 g = 243.36 kg
        #   day 2: 10 + 0.02 × 40.56 = 10.8112 °C; SFR 1.4056 %; 40.56 × 0.014056 = 0.57011136 g, 3.42066816 kg;
        #          → 41.13011136 g, 246.78066816 kg; feed to date 6.78066816 kg
        rows = self.file(unit=self.t1)
        self.assertEqual(rows[1][:3], [self.today.isoformat(), '40.0000', '6000'])
        self.assertEqual(rows[2], [self.day(-1).isoformat(), '40.5600', '6000', '243.360', '3.360', '3.360', '3.360',
                                   '0.000', '1.000', '1.000', '0.00', '10.8', 'Hall A', ''])
        self.assertEqual(rows[3], [self.day(-2).isoformat(), '41.1301', '6000', '246.781', '3.421', '6.781', '3.421',
                                   '0.000', '1.000', '1.000', '0.00', '10.8', 'Hall A', ''])
        # T-02, 4,000 fish of 60 g, graded in: no unit row there, so the whole batch's: Batch plan, a step at 50 g:
        #   12 °C from 50 g on; SFR 2 %; day 1: 1.2 g a fish, 4.8 kg → 61.2 g, 244.8 kg;
        #   day 2: 1.224 g, 4.896 kg → 62.424 g, 249.696 kg; feed to date 9.696 kg
        rows = self.file(unit=self.t2)
        self.assertEqual(rows[1][:3], [self.today.isoformat(), '60.0000', '4000'])
        self.assertEqual(rows[2], [self.day(-1).isoformat(), '61.2000', '4000', '244.800', '4.800', '4.800', '4.800',
                                   '0.000', '1.000', '1.000', '0.00', '12.0', 'Batch plan', ''])
        self.assertEqual(rows[3], [self.day(-2).isoformat(), '62.4240', '4000', '249.696', '4.896', '9.696', '4.896',
                                   '0.000', '1.000', '1.000', '0.00', '12.0', 'Batch plan', ''])
        # the service's projection (decision 20) gives the same days, read only (no target yet: the whole horizon)
        found = forecast.projection(str(self.t2.pk), str(self.batch.pk))         # ids as text, as a call in JSON
        self.assertEqual([(day['weight_g'], day['temperature_c'], day['temperature_source'])
                          for day in found['days'][:2]],
                         [(D('61.2'), D('12.0'), 'Batch plan'), (D('62.424'), D('12.0'), 'Batch plan')])
        empty = make_unit('T-09', self.hall)
        self.assertIsNone(forecast.projection(empty.pk, self.batch.pk))
        # the pages say it: the profile of the days, and the target day of the part that reaches it
        self.set_target('41.1')                         # T-01 reaches it on day 2 (41.13 g), T-02 is there already
        for look in ('classic', 'next'):
            page = self.client.get(reverse('farm:productionplan_list'), {'ui': look}).content.decode()
            self.assertIn(f'target on {shown(self.day(-2))}, on the temperature profile Hall A', page, look)
        plan = self.client.get(self.growth_url(self.t1), {'ui': 'classic'})
        self.assertContains(plan, 'The temperature of a day is the temperature profile Hall A at the fish’s weight '
                                  'that day.')
        self.assertEqual(plan.context['props']['table']['rows'][-1]['cells']['temperature']['sub'], ['Hall A'])

    def test_a_profile_is_shown_over_the_weight_fixed_once_assigned_and_changed_on_a_copy(self):
        # Proves decision 15 (visible in both looks; assigned: fixed; a copy is changed) for the profile, as decision 14
        # for the protocol. Hall A: 0 g 10 °C, half way 50 g 11 °C, 100 g 12 °C.
        hall, _planned = self.profiles()
        url = reverse('farm:temperatureprofile_edit', args=[hall.pk])
        classic = self.client.get(url, {'ui': 'classic'})
        self.assertEqual([(row['cells']['point']['text'], row['cells']['temperature']['text'])
                          for row in classic.context['used']['rows']],
                         [('entered', '10.0 °C'), ('half way', '11.0 °C'), ('entered', '12.0 °C')])
        new = self.client.get(url, {'ui': 'next'}).content.decode().replace('\\u2019', '’').replace('\\u00b0', '°')
        for text in ('Temperature over the fish', 'half way', '11.0 °C', 'Smooth between bands'):
            self.assertIn(text, new)
        self.assertContains(classic, 'The profile is assigned, so its points are fixed')
        refused = self.client.post(reverse('farm:temperatureprofile_points', args=[hall.pk]), rows_data(
            'points', [{'weight_g': '0', 'temperature_c': '15'}], record=hall))
        self.assertEqual(refused.status_code, 404)
        self.assertEqual(sorted(hall.points.values_list('temperature_c', flat=True)), [D('10.0'), D('12.0')])
        self.client.post(url, {'name': 'Hall A', 'species': str(self.salmon.pk), 'status': 'active',
                               'temperature_between': 'step', 'notes': '', 'version': str(hall.version)})
        hall.refresh_from_db()
        self.assertEqual(hall.temperature_between, 'smooth')
        copied = self.client.post(reverse('farm:temperatureprofile_duplicate', args=[hall.pk]))
        self.assertEqual(copied.status_code, 302)
        copy = TemperatureProfile.objects.get(name='Hall A (copy)')
        self.assertEqual((copy.status, sorted(copy.points.values_list('weight_g', 'temperature_c'))),
                         ('draft', [(D('0.00'), D('10.0')), (D('100.00'), D('12.0'))]))
        twice = self.client.post(reverse('farm:temperatureprofile_points', args=[copy.pk]), rows_data(
            'points', [{'weight_g': '0', 'temperature_c': '9'}, {'weight_g': '0', 'temperature_c': '11'}],
            record=copy))
        self.assertEqual(twice.status_code, 200)                    # each weight a point once: the page again
        too_hot = self.client.post(reverse('farm:temperatureprofile_points', args=[copy.pk]), rows_data(
            'points', [{'weight_g': '0', 'temperature_c': '41'}], record=copy))
        self.assertEqual(too_hot.status_code, 200)
        self.assertEqual(copy.points.count(), 2)
        log = AuditLog.objects.filter(entity_type='temperature profile', action='update')
        self.assertTrue(any('0 g 10 °C; 100 g 12 °C' in str(row.changes.get('Points')) for row in log))

    def test_an_assignment_of_a_profile_follows_the_protocols_rules(self):
        # Proves decision 16: the same rules as a protocol's rows (one in force per target, the species, active only),
        # and the one resolver counting the fish each row applies to now.
        hall, _planned = self.profiles()
        twice = self.client.post(reverse('farm:temperatureprofileassignment_create'), {
            'profile': str(hall.pk), 'units': [str(self.t1.pk)], 'batch': '', 'valid_from': self.day(3).isoformat(),
            'valid_until': '', 'notes': ''}, headers={'X-Modal': '1'})
        self.assertIn('T-01: Another temperature profile is assigned to this unit on some of these days.',
                      twice.context['form'].errors['units'])
        trout = TemperatureProfile.objects.create(name='Trout', species=self.trout, status='active')
        other = self.client.post(reverse('farm:temperatureprofileassignment_create'), {
            'profile': str(trout.pk), 'units': [str(self.t2.pk)], 'batch': str(self.batch.pk),
            'valid_from': self.day(1).isoformat(), 'valid_until': '', 'notes': ''}, headers={'X-Modal': '1'})
        self.assertEqual(other.context['form'].errors['batch'],
                         [f'{self.batch.code} is {self.salmon}; the profile is for {self.trout}.'])
        draft = TemperatureProfile.objects.create(name='Draft', species=self.salmon)
        refused = self.client.post(reverse('farm:temperatureprofileassignment_create'), {
            'profile': str(draft.pk), 'units': [str(self.t2.pk)], 'batch': '', 'valid_from': self.today.isoformat(),
            'valid_until': '', 'notes': ''}, headers={'X-Modal': '1'})
        self.assertIn('profile', refused.context['form'].errors)
        listing = self.client.get(reverse('farm:temperatureprofileassignment_list'))
        # Hall A applies to the 6,000 fish in T-01; Batch plan, read past there, to the 4,000 in T-02
        self.assertEqual(sorted(listing.context['feeds_now'].values()), [4000, 6000])
        for text in ('Hall A', 'Batch plan', 'Applies now', 'Whole batch'):
            self.assertContains(listing, text)


class PlannedAgainstActualTests(PlanTestCase):
    """Decisions 10–12. Beside the base case: 5 kg fed seven days ago and a second weighing five days ago at 62 g; the
    unit's temperature profile at 10 °C over every weight, so the plan from a past start reads a temperature whatever
    was sampled then (a profile is read for the days ahead of any start)."""

    def setUp(self):
        super().setUp()
        self.record(kilos='5', days_ago=7)
        stock_services.record_weighing(self.user, unit=self.t1, batch=self.batch, day=self.day(5), avg_weight_g=D(62))
        self.assign_profile(self.profile_through_its_pages('Hall at 10', [('0', '10'), ('1000', '10')]), unit=self.t1)
        self.recorded_back(16)                        # the rows were made back then, as on a farm

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
        # from the stocking, 20 days ago: the protocol was in force from 15 days ago only, so the plan as it stood then
        # stops at once and says why (the rows recorded by then are read: these were made 16 days ago)
        stocked = self.plan(self.day(20))
        self.assertEqual((stocked.chosen.day, stocked.forecast.now_g, stocked.forecast.curve.points,
                          stocked.forecast.why), (self.day(20), D(50), (), 'No protocol is assigned to these fish.'))
        self.assertIsNone(stocked.measured[1].planned_g)
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


class ReviewOneTests(PlanTestCase):
    """The findings of review 1 (F:/dev/balik-notes/plan/production-plan/REVIEW-1.md), each proved through the pages
    and services: H1, M1, M5, L3, L4 and the two FCRs."""

    def water_on(self, unit, days_ago, value):
        from ..water import services as water_services
        from .helpers import may_record, point_of
        may_record(self.user, 'add_watermeasurement')
        water_services.record(self.user, point=point_of(unit), measured_at=timezone.now() - timedelta(days=days_ago),
                              source='manual', values={'temperature_c': D(value)})

    def test_an_active_profile_keeps_its_points_and_a_profile_without_any_stops_the_plan_never_the_page(self):
        # H1: the points of an active profile cannot all be removed (the write path); and a profile without points
        # stored by any other path stops the plan with its reason naming the profile (the read never raises).
        profile = self.profile_through_its_pages('Hall B', [('0', '10'), ('100', '12')])
        emptied = self.client.post(reverse('farm:temperatureprofile_points', args=[profile.pk]),
                                   rows_data('points', [], record=profile))
        self.assertEqual(emptied.status_code, 422)
        self.assertContains(emptied, 'An active profile has points', status_code=422)
        self.assertEqual(profile.points.count(), 2)
        self.assign_profile(profile, unit=self.t1)
        profile.points.all().delete()                               # a path that is not the form: a script, a restore
        self.set_target('62')
        listed = self.client.get(reverse('farm:productionplan_list'))
        self.assertEqual(listed.status_code, 200)
        why = ('The temperature profile Hall B has no points: give its points (Operations › Feeding › Temperature '
               'profiles).')
        self.assertEqual(self.row()['forecast'].why, why)
        self.assertContains(self.client.get(self.growth_url(), {'ui': 'classic'}), why)

    def test_a_plan_from_a_past_start_is_the_plan_as_it_stood_that_day(self):
        # M1: the plan from the weighing ten days ago (60 g) reads the rows recorded by the end of that day and the
        # temperature measured by then; an assignment made since, and a reading taken since, do not enter it.
        stock_services.record_weighing(self.user, unit=self.t1, batch=self.batch, day=self.day(5), avg_weight_g=D(62))
        self.recorded_back(16)
        start = self.day(10)
        # no temperature measured by the start (the only sample is two hours old) and no profile: the plan says so
        found = forecast.projection(self.t1.pk, self.batch.pk, start)
        self.assertEqual(found['days'], [])
        self.assertEqual(found['why'], f'No temperature had been measured here by {shown(start)}, and no temperature '
                                       'profile applies: the plan as it stood then has none to read.')
        # a sample taken the day before the start, at 12 °C: held for every day of that plan (the later 10 °C is not)
        self.water_on(self.t1, 11, '12')
        found = forecast.projection(self.t1.pk, self.batch.pk, start)
        self.assertEqual((found['as_recorded'], found['temperature_held_c'], found['protocols']),
                         (True, D('12.0'), ['Salmon plan']))
        before = [(day['weight_g'], day['temperature_c']) for day in found['days'][:5]]
        # 60 g at 1 % a day, 20 % uneaten, FCR 1.00: 60 × 1.008^5 = 62.43870843076608 g on the fifth day
        self.assertEqual(before[4], (D('62.43870843076608'), D('12.0')))
        # an assignment made after the start, a warmer profile on the batch in T-01 from the start on: today's plan
        # reads it, the plan from the start does not
        warm = self.profile_through_its_pages('Warm', [('0', '11'), ('1000', '11')])
        self.assign_profile(warm, unit=self.t1, batch=self.batch, days_ago=10)
        self.assertEqual(forecast.projection(self.t1.pk, self.batch.pk)['temperature_profiles'], ['Warm'])
        again = forecast.projection(self.t1.pk, self.batch.pk, start)
        self.assertEqual([(day['weight_g'], day['temperature_c']) for day in again['days'][:5]], before)
        self.assertEqual(again['temperature_profiles'], [])
        # and the page says what the plan holds, with the rule for a past start (L3)
        page = self.client.get(self.growth_url(), {'from': start.isoformat(), 'ui': 'classic'})
        self.assertContains(page, f'The plan as it stood on {shown(start)}: the assignments recorded by then '
                                  '(Salmon plan) and the temperature measured by then')
        self.assertContains(page, 'Every day of this plan, from its past start on, counts the day’s ration as given')
        self.assertNotContains(page, 'A past day is never planned')

    def test_a_row_ended_after_the_start_is_read_as_it_was_then(self):
        # M1: the protocol's row on T-01 ended yesterday (its last day changed after the start): the plan from ten days
        # ago still reads it open, as it was recorded then; today's plan has no protocol.
        stock_services.record_weighing(self.user, unit=self.t1, batch=self.batch, day=self.day(5), avg_weight_g=D(62))
        self.recorded_back(16)
        self.water_on(self.t1, 11, '10')
        from ..feeding import assignments
        assignments.end(self.user, ProtocolAssignment.objects.get(), self.day(1))
        self.assertEqual(forecast.projection(self.t1.pk, self.batch.pk)['why'],
                         'No protocol is assigned to these fish.')
        then = forecast.projection(self.t1.pk, self.batch.pk, self.day(10))
        self.assertEqual(len(then['days']), 730)                          # the whole horizon: the row open as then

    def test_the_service_takes_a_horizon_checks_its_ids_returns_plain_values_and_writes_nothing(self):
        # M5: the stable contract of decision 20.
        from datetime import date as day_type
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as log:
            found = forecast.projection(str(self.t1.pk), self.batch.pk, horizon_days=3)
        statements = {query['sql'].split()[0].upper() for query in log.captured_queries}
        self.assertTrue(statements <= {'SELECT', 'SAVEPOINT', 'RELEASE'}, statements)
        self.assertEqual(sorted(found), sorted([
            'unit_id', 'unit', 'batch_id', 'batch', 'start_day', 'start_weight_g', 'start_fish', 'horizon_days',
            'as_recorded', 'target_g', 'target_day', 'why', 'feed_kg', 'eaten_kg', 'uneaten_kg', 'fcr_on_feed_given',
            'economic_fcr', 'protocols', 'temperature_profiles', 'temperature_held_c', 'days', 'measured']))
        self.assertEqual(sorted(found['days'][0]), sorted([
            'day', 'weight_g', 'fish', 'biomass_kg', 'feed_kg', 'eaten_kg', 'uneaten_kg', 'growth_kg',
            'feed_to_date_kg', 'fcr', 'uneaten_pct', 'temperature_c', 'temperature_source', 'fasting']))
        self.assertEqual(sorted(found['measured'][0]), sorted([
            'day', 'kind', 'fish', 'weight_g', 'source', 'sample_count', 'sample_weight_kg', 'planned_g',
            'difference_g']))
        self.assertEqual((len(found['days']), found['horizon_days'], found['unit_id']), (3, 3, str(self.t1.pk)))

        def plain(value):
            if isinstance(value, dict):
                return all(plain(each) for each in value.values())
            if isinstance(value, list):
                return all(plain(each) for each in value)
            return value is None or isinstance(value, (str, bool, int, D, day_type))
        self.assertTrue(plain(found))
        self.assertEqual(found['measured'][1]['source'], 'Manual sample')
        for wrong in ('T-01', 42, None, ''):
            with self.assertRaises(forecast.ProjectionError):
                forecast.projection(wrong, self.batch.pk)
        with self.assertRaises(forecast.ProjectionError):
            forecast.projection(self.t1.pk, self.batch.pk, horizon_days=-1)
        import uuid as uuids
        with self.assertRaises(forecast.ProjectionError):
            forecast.projection(uuids.uuid4(), self.batch.pk)
        self.assertIsNone(forecast.projection(self.t2.pk, self.batch.pk))   # a unit without the batch: no plan

    def test_a_profiles_temperature_outside_the_table_names_the_profile(self):
        # L4: the protocol's columns are 10 and 12 °C; a profile at 15 °C is outside them.
        hot = self.profile_through_its_pages('Too warm', [('0', '15'), ('1000', '15')])
        self.assign_profile(hot, unit=self.t1)
        self.set_target('62')
        self.assertEqual(self.row()['forecast'].why, '15.0 °C, the temperature profile Too warm’s at this weight, is '
                                                     'outside this table (10.0–12.0 °C).')

    def test_the_economic_fcr_counts_the_biomass_lost_to_mortality(self):
        # Economic FCR (decided): feed given ÷ the biomass gained, the dead fish's weight not gained. 1,000 fish of
        # 100 g in T-02 on a protocol with 3 % mortality a month (nothing uneaten, FCR 1.00, SFR 1 % at 10 °C):
        # day 1: 1 kg fed to the 1,000 fish, 1 kg grown → 101 g; then 1,000 × 0.97^(1/30) = 998.98… fish are left:
        # biomass 998.98… × 101 g = 100.897… kg: gained 0.897… kg for 1 kg fed: economic FCR 1.114…, FCR on feed
        # given 1.00 (the growth of the fish fed).
        dying = self.protocol_through_its_pages(name='Dying', uneaten_pct='', mortality_pct_month='3', rows=[
            self.band(sfr_120='1')])
        fish = self.stock(self.t2, count=1000, weight='100', days_ago=5)
        self.assign_through_the_dialog(dying, unit=self.t2)
        ProtocolTestCase.water(self, '10', unit=self.t2)
        found = forecast.projection(self.t2.pk, fish.pk, horizon_days=1)
        alive = D(1000) * (1 - D(3) / 100) ** (D(1) / 30)
        gained = alive * 101 / 1000 - 100
        self.assertEqual(found['fcr_on_feed_given'], D(1))
        self.assertEqual(found['economic_fcr'], 1 / gained)
        self.assertGreater(found['economic_fcr'], found['fcr_on_feed_given'])
        page = self.client.get(self.growth_url(self.t2, fish), {'ui': 'classic'})
        self.assertContains(page, 'Economic FCR, as the industry says it: the feed given divided by the biomass gained')

    def test_an_assignment_locks_its_table_and_asks_again_that_it_is_active(self):
        # L6: rows built while the profile was active are not written once it was retired meanwhile.
        from django.core.exceptions import ValidationError

        from ..feeding import assignments
        profile = self.profile_through_its_pages('Hall C', [('0', '10'), ('100', '12')])
        made, errors = assignments.rows(profile, [self.t2], None, self.today, None)
        self.assertEqual(errors, [])
        TemperatureProfile.objects.filter(pk=profile.pk).update(status='retired')
        with self.assertRaises(ValidationError) as caught:
            assignments.save(self.user, made)
        self.assertEqual(caught.exception.message_dict['profile'], ['Hall C is no longer active: it was changed meanwhile.'])
        self.assertFalse(TemperatureProfileAssignment.objects.exists())

    def test_a_past_start_reads_its_protocol_by_identity_never_by_name(self):
        # M1 by identity (the coordinator's round after review 1): the plan from the weighing ten days ago reads the
        # protocol row and its table as they were at the end of that day, found by the row's own id. Since then the
        # protocol was renamed through its page, a new protocol was given its old name, the row on T-01 was pointed at
        # the new one by a script, and the old table's cells were raised by a script. The plan from then still reads
        # 'Salmon plan' as it was: SFR 1 % at 12 °C, 20 % uneaten, FCR 1.00: 60 g × 1.008^5 = 62.43870843076608 g on
        # the fifth day. The new 'Salmon plan' (SFR 2 %) would give 60 × 1.016^5 = 64.93… g.
        stock_services.record_weighing(self.user, unit=self.t1, batch=self.batch, day=self.day(5), avg_weight_g=D(62))
        self.recorded_back(16)
        self.water_on(self.t1, 11, '12')
        start, first = self.day(10), self.protocol.pk
        renamed = self.client.post(reverse('farm:feedingprotocol_edit', args=[first]), {
            **self.general(name='Salmon plan 2025'), 'status': 'active',
            'version': str(FeedingProtocol.objects.get(pk=first).version)})
        self.assertEqual(renamed.status_code, 302)
        new = self.protocol_through_its_pages(rows=[self.band(sfr_100='2', sfr_120='2')])
        self.assertEqual(new.name, 'Salmon plan')
        ProtocolAssignment.objects.filter(unit=self.t1).update(protocol=new)            # a script, not the form
        ProtocolRate.objects.filter(band__protocol_id=first).update(sfr_pct=D(3))         # a script, not the form
        then = self.past_plan(start)
        self.assertEqual([(protocol.pk, protocol.name) for protocol in then.forecast.protocols], [(first, 'Salmon plan')])
        self.assertEqual(then.forecast.weight_on(self.day(5)), D('62.43870843076608'))
        found = forecast.projection(self.t1.pk, self.batch.pk, start)
        self.assertEqual(found['protocols'], ['Salmon plan'])
        self.assertEqual(found['days'][4]['weight_g'], D('62.43870843076608'))
        # today's plan reads the rows as they are now: the new protocol
        self.assertEqual([protocol.pk for protocol in self.past_plan(None).forecast.protocols], [new.pk])

    def test_a_past_start_reads_its_temperature_profile_by_identity_never_by_name(self):
        # The same for the temperature profile: 'Hall at 10' (10 °C at every weight) on T-01 from fifteen days ago. Since
        # the start it was renamed through its page, its points were warmed to 11 °C by a script, a new profile was
        # given its old name at 12 °C and the row was pointed at it by a script. The plan from ten days ago reads 10 °C
        # every day, under the name it had: 60 × 1.008^5 = 62.43870843076608 g on the fifth day (SFR 1 % at 10 °C).
        old = self.profile_through_its_pages('Hall at 10', [('0', '10'), ('1000', '10')])
        self.assign_profile(old, unit=self.t1)
        stock_services.record_weighing(self.user, unit=self.t1, batch=self.batch, day=self.day(5), avg_weight_g=D(62))
        self.recorded_back(16)
        start = self.day(10)
        renamed = self.client.post(reverse('farm:temperatureprofile_edit', args=[old.pk]), {
            'name': 'Hall old', 'species': str(self.salmon.pk), 'status': 'active', 'temperature_between': 'smooth',
            'notes': '', 'version': str(TemperatureProfile.objects.get(pk=old.pk).version)})
        self.assertEqual(renamed.status_code, 302)
        TemperatureProfilePoint.objects.filter(profile=old).update(temperature_c=D(11))      # a script
        new = self.profile_through_its_pages('Hall at 10', [('0', '12'), ('1000', '12')])
        TemperatureProfileAssignment.objects.filter(unit=self.t1).update(profile=new)       # a script
        found = forecast.projection(self.t1.pk, self.batch.pk, start)
        self.assertEqual(found['temperature_profiles'], ['Hall at 10'])
        self.assertEqual({day['temperature_c'] for day in found['days']}, {D('10.0')})
        self.assertEqual(found['days'][4]['weight_g'], D('62.43870843076608'))
        self.assertEqual([profile.pk for profile in self.past_plan(start).forecast.profiles], [old.pk])

    def test_a_past_start_reads_the_fasts_planned_by_then_and_none_planned_since(self):
        # Decision 12 for the fasts: a transport planned by the end of the start day (seven days ago, the rule's 24 h:
        # its day and the day before fast) asks its fast in the plan from then, though it was cancelled since; a
        # transport planned since (four days ago) asks none there. Today's plan reads neither: the one is cancelled,
        # the other is in the past.
        stock_services.record_weighing(self.user, unit=self.t1, batch=self.batch, day=self.day(5), avg_weight_g=D(62))
        planned = HandlingPlanItem.objects.create(kind='transport', date=self.day(7), unit=self.t1, batch=self.batch)
        self.recorded_back(16)
        self.water_on(self.t1, 11, '12')
        HandlingPlanItem.objects.filter(pk=planned.pk).update(cancelled_reason='Weather')
        HandlingPlanItem.objects.create(kind='transport', date=self.day(4), unit=self.t1, batch=self.batch)
        found = forecast.projection(self.t1.pk, self.batch.pk, self.day(10))
        self.assertEqual([day['day'] for day in found['days'] if day['fasting']], [self.day(8), self.day(7)])
        # nothing fed on the fasting days: the weight of the day before them (60 × 1.008 = 60.48 g) stands
        self.assertEqual([day['weight_g'] for day in found['days'][:3]], [D('60.48'), D('60.48'), D('60.48')])
        self.assertFalse(any(day['fasting'] for day in forecast.projection(self.t1.pk, self.batch.pk)['days']))

    def past_plan(self, start):
        unit = type(self.t1).objects.select_related('production_department__site').get(pk=self.t1.pk)
        share = stock_read.stock_of([unit])[unit.pk].counted[0]
        return forecast.plan(unit, share, D(70), start)
