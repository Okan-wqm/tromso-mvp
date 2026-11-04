"""The id the authority's API returned is recorded at the filing, and the export of a correction says how the API takes it: a PUT to
that id for a smolt, cleaner-fish or planned-slaughter report, with the client reference of the filing it replaces (coverage review C02)."""
import json

from django.db import IntegrityError, transaction
from django.urls import reverse

from core.models import AuditLog

from .. import exports
from ..models import Report
from .test_pages import ReportPagesTestCase


class AuthorityIdTests(ReportPagesTestCase):
    def setUp(self):
        super().setUp()
        self.october()
        _response, self.original = self.start()

    def correction_of(self, original):
        self.client.post(reverse('reports:report_correct', args=[original.pk]))
        return Report.objects.get(corrects=original)

    def test_the_id_is_recorded_at_the_filing_shown_and_logged(self):
        self.file(self.original, channel='api', reference='R-1', authority_id=' 7f3a-91 ')
        self.original.refresh_from_db()
        self.assertEqual(self.original.authority_id, '7f3a-91')
        self.assertContains(self.client.get(reverse('reports:report_detail', args=[self.original.pk])), 'API id 7f3a-91')
        entry = AuditLog.objects.filter(entity_type='regulatory report', action='update').latest('created_at')
        self.assertEqual(entry.changes['Id returned by the authority’s API'], [None, '7f3a-91'])

    def test_a_first_filing_is_a_post_and_a_correction_is_a_put_to_the_id_with_the_originals_client_reference(self):
        self.file(self.original, channel='api', reference='R-1', authority_id='7f3a-91')
        first = self.client.get(reverse('reports:report_export', args=[self.original.pk, 'json']))
        self.assertEqual((first['X-Api-Method'], first['X-Api-Path']), ('POST', '/api/settefisk/v1/settefisk'))
        self.assertNotIn('X-Corrects-Client-Reference', first)
        correction = self.correction_of(self.original)
        response = self.client.get(reverse('reports:report_export', args=[correction.pk, 'json']))
        self.assertEqual((response['X-Api-Method'], response['X-Api-Path']), ('PUT', '/api/settefisk/v1/settefisk/7f3a-91'))
        self.assertEqual(response['X-Corrects-Client-Reference'], str(self.original.pk))
        body = json.loads(response.content)
        self.assertEqual(body['klientReferanse'], str(correction.pk))              # its own, unique for the reporting
        page = self.client.get(reverse('reports:report_print', args=[correction.pk]))
        self.assertContains(page, 'PUT /api/settefisk/v1/settefisk/7f3a-91')
        self.assertContains(page, str(self.original.pk))

    def test_without_the_recorded_id_the_correction_says_it_is_needed(self):
        self.file(self.original, channel='altinn')
        correction = self.correction_of(self.original)
        call = exports.api_call(correction)
        self.assertEqual((call['method'], call['path']), ('PUT', '/api/settefisk/v1/settefisk/{id}'))
        self.assertIn('was not recorded', call['note'])

    def test_the_sea_lice_endpoint_has_post_only(self):
        lice = Report(kind='sea_lice', site=self.sea, period_start=self.original.period_start)
        original = Report(pk=self.original.pk, kind='sea_lice')
        lice.corrects = original
        call = exports.api_call(lice)
        self.assertEqual((call['method'], call['path']), ('POST', '/api/lakselus/v1/lakselus'))
        self.assertIn('no PUT', call['note'])

    def test_a_kind_without_an_endpoint_has_no_call(self):
        self.assertIsNone(exports.api_call(Report(kind='biomass')))

    def test_the_database_holds_that_only_a_filed_report_has_the_id(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Report.objects.filter(pk=self.original.pk).update(authority_id='x')
