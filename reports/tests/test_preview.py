"""What the person is about to record as filed is shown first, with its hash, and exactly that is frozen (coverage review C06)."""
from django.urls import reverse

from farm.stock import services as stock_services

from .. import compute
from ..models import Report, ReportSnapshot
from .helpers import OCTOBER, previewed
from .test_pages import ReportPagesTestCase


class PreviewTests(ReportPagesTestCase):
    def setUp(self):
        super().setUp()
        self.october()
        _response, self.report_ = self.start()

    def test_the_page_shows_the_hash_and_the_values_to_type_before_the_filing(self):
        page = self.client.get(reverse('reports:report_detail', args=[self.report_.pk]))
        digest = previewed(self.report_)
        self.assertContains(page, 'What you are about to record as filed')
        self.assertContains(page, digest)
        self.assertEqual(page.context['submit_form'].initial['content_sha256'], digest)
        printed = self.client.get(reverse('reports:report_print', args=[self.report_.pk]))
        self.assertContains(printed, digest)
        exported = self.client.get(reverse('reports:report_export', args=[self.report_.pk, 'csv']))
        self.assertEqual(exported['X-Content-SHA256'], digest)

    def test_what_is_frozen_is_the_content_that_was_previewed(self):
        digest = previewed(self.report_)
        self.file(self.report_)
        snapshot = ReportSnapshot.objects.get(report=self.report_)
        self.assertEqual(snapshot.content_sha256, digest)
        filed = self.client.get(reverse('reports:report_print', args=[self.report_.pk]))
        self.assertContains(filed, digest)

    def test_the_filing_is_refused_when_the_records_changed_after_the_person_looked(self):
        digest = previewed(self.report_)
        stock_services.record_mortality(self.user, unit=self.k1, batch=self.first, day=self.today_in_october(),
                                        count=1, cause='unknown')
        response = self.file(self.report_, content_sha256=digest)
        self.assertContains(response, 'The records changed after you looked at the report: review it again')
        self.assertIsNone(Report.objects.get(pk=self.report_.pk).submitted_at)
        self.assertFalse(ReportSnapshot.objects.exists())
        # Looking again gives the new hash, and then it is recorded.
        self.assertContains(self.file(self.report_), 'Recorded as filed.')

    def test_a_filing_without_the_hash_or_with_a_wrong_one_is_refused(self):
        self.file(self.report_, content_sha256='')
        self.assertIsNone(Report.objects.get(pk=self.report_.pk).submitted_at)
        self.file(self.report_, content_sha256='0' * 64)
        self.assertIsNone(Report.objects.get(pk=self.report_.pk).submitted_at)

    def today_in_october(self):
        return OCTOBER.start.replace(day=28)

    def test_the_hash_is_the_one_of_the_computed_content(self):
        self.assertEqual(previewed(self.report_), compute.content_hash(compute.compute(self.report_).content))
