"""A filing says whether it was late, the biomass report's condition of the harvested fish is said by the person, the cleaner-fish
feed is a statement and not a silence, and the cleaner-fish API rows are per species (coverage review C07, R19, R11, R09)."""
from datetime import date, datetime, timezone as utc
from unittest import mock

from django.db import IntegrityError, transaction
from django.urls import reverse

from core.models import AuditLog

from .. import exports, services
from ..compute import biomass
from ..models import HarvestCondition, Report
from .helpers import OCTOBER, previewed
from .test_cleaner import CleanerFishTestCase
from .test_pages import ReportPagesTestCase


class FiledLateTests(ReportPagesTestCase):
    def setUp(self):
        super().setUp()
        self.october()
        _response, self.report_ = self.start()           # the October smolt report: deadline 7 November

    def file_on(self, moment):
        with mock.patch('reports.services.timezone.now', return_value=moment.replace(hour=23)):
            return services.submit(self.user, self.report_, submitted_at=moment, channel='altinn', reference='AR-1',
                                   version=self.report_.version, content_sha256=previewed(self.report_))

    def test_a_filing_in_time_says_so(self):
        filed = self.file_on(datetime(2026, 11, 3, 9, 0, tzinfo=utc.utc))
        self.assertEqual((filed.deadline_on, filed.filed_late, filed.days_late), (date(2026, 11, 7), False, 0))
        page = self.client.get(reverse('reports:report_detail', args=[filed.pk]))
        self.assertContains(page, 'In time')

    def test_a_filing_after_the_deadline_is_late_and_says_by_how_many_days(self):
        filed = self.file_on(datetime(2026, 11, 9, 9, 0, tzinfo=utc.utc))             # Monday 9 November
        self.assertEqual((filed.deadline_on, filed.filed_late, filed.days_late), (date(2026, 11, 7), True, 2))
        page = self.client.get(reverse('reports:report_detail', args=[filed.pk]))
        self.assertContains(page, 'Filed 2 days after its deadline')
        self.assertContains(self.client.get(reverse('reports:report_list')), '2 days late')
        entry = AuditLog.objects.filter(entity_type='regulatory report', action='update').latest('created_at')
        self.assertEqual((entry.changes['Deadline'][1], entry.changes['Filed late'][1]),
                         ('2026-11-07', {'msgid': 'Yes'}))

    def test_the_day_is_oslos_the_last_minute_of_the_deadline_is_in_time(self):
        filed = self.file_on(datetime(2026, 11, 7, 22, 59, tzinfo=utc.utc))            # 23:59 in Oslo
        self.assertFalse(filed.filed_late)

    def test_a_notice_has_no_deadline_and_is_never_late(self):
        _response, notice = self.start(kind='welfare', site=str(self.sea.pk), period_start='', occurred_on='2026-10-30',
                                       what_happened='Oxygen fell', found_at='2026-10-30T06:15')
        self.file(notice)
        notice.refresh_from_db()
        self.assertEqual((notice.deadline_on, notice.filed_late), (None, False))

    def test_the_database_holds_that_only_a_filed_report_is_late_or_on_time(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Report.objects.filter(pk=self.report_.pk).update(filed_late=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Report.objects.filter(pk=self.report_.pk).update(deadline_on=date(2026, 11, 7))


class ConditionAndFeedFieldsTests(CleanerFishTestCase):
    def test_the_cleaner_answer_belongs_to_its_own_kind_of_report_and_the_database_holds_it(self):
        cleaner = self.report(Report.Kind.CLEANER_FISH, OCTOBER, site=self.sea, no_cleaner_feed=True)
        self.assertTrue(cleaner.no_cleaner_feed)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Report.objects.create(site=self.sea, period_start=date(2026, 9, 1), kind='biomass', no_cleaner_feed=True)

    def test_the_harvest_condition_is_the_weights_never_an_answer(self):
        """The farm holds only round kilos (weighed at harvest): a person's "gutted" labelled them gutted in a filing to
        Fiskeridirektoratet (F-086). No report asks it or keeps it; every harvested row says round."""
        self.assertNotIn('harvest_condition', {field.name for field in Report._meta.get_fields()})
        form = self.client.get(reverse('reports:report_create'), {'kind': 'biomass'}).context['form']
        self.assertNotIn('harvest_condition', form.fields)
        self.assertEqual(biomass.HARVEST_CONDITION, HarvestCondition.ROUND)

    def test_the_page_offers_the_cleaner_answer_to_its_own_report_only_and_stores_it(self):
        data = {'site': str(self.sea.pk), 'period_start': '2026-10-17', 'contact_name': 'Kari Nord',
                'contact_email': 'kari@example.com', 'contact_phone': '+47 98989898', 'notes': ''}
        form = self.client.get(reverse('reports:report_create'), {'kind': 'biomass'}).context['form']
        self.assertNotIn('no_cleaner_feed', form.fields)
        form = self.client.get(reverse('reports:report_create'), {'kind': 'cleaner_fish'}).context['form']
        self.assertIn('no_cleaner_feed', form.fields)
        self.client.post(reverse('reports:report_create'), {**data, 'kind': 'cleaner_fish', 'no_cleaner_feed': 'on'})
        self.assertTrue(Report.objects.get(kind='cleaner_fish').no_cleaner_feed)

    def test_the_cleaner_api_has_one_row_per_species_with_the_mixed_origin_only_when_both_are_there(self):
        rows = [{'species': 'LUM', 'origin': 'farmed', 'opening': 10, 'stocked': 0, 'moved_in': 0, 'died': 1,
                 'moved_out': 0, 'unaccounted': 0, 'culled': {'sick': 1}},
                {'species': 'LUM', 'origin': 'wild_caught', 'opening': 5, 'stocked': 2, 'moved_in': 1, 'died': 0,
                 'moved_out': 3, 'unaccounted': 4, 'culled': {'sick': 2}},
                {'species': 'WRA', 'origin': 'wild_caught', 'opening': 7, 'stocked': 0, 'moved_in': 0, 'died': 0,
                 'moved_out': 0, 'unaccounted': 0, 'culled': {'sick': 0}}]
        merged = {row['species']: row for row in exports._per_species(rows)}
        self.assertEqual((merged['LUM']['origin'], merged['LUM']['opening'], merged['LUM']['stocked'],
                          merged['LUM']['moved_in'], merged['LUM']['died'], merged['LUM']['moved_out'],
                          merged['LUM']['unaccounted'], merged['LUM']['culled']['sick']),
                         ('VILLFANGET_OG_OPPDRETTET', 15, 2, 1, 1, 3, 4, 3))
        self.assertEqual(merged['WRA']['origin'], 'VILLFANGET')
        self.assertEqual(rows[0]['opening'], 10)                       # the content itself is not changed
