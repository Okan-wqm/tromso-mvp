"""A value filed on a reading the authority has not confirmed (the amount of a medicinal treatment, Q1; the types of a medicated
feed and an injection, Q2) is shown to the person at the filing: recording it is refused until they confirm it by hand, and the
confirmation is logged with the question's text (coverage review R03, R04)."""
from datetime import datetime, timezone as utc

from django.core.exceptions import ValidationError
from django.urls import reverse

from core.models import AuditLog

from .. import compute, services
from ..models import OpenQuestion, Report
from .helpers import day
from .test_lice import WARM, LiceTestCase, temperature


class AcknowledgementTests(LiceTestCase):
    def setUp(self):
        super().setUp()
        self.count(self.m1, 10, 27)
        self.count(self.m2, 10, 28)

    def submit(self, report, **overrides):
        with temperature(WARM):
            digest = compute.content_hash(compute.compute(report).content)
            values = {'submitted_at': datetime(2026, 11, 3, 9, 0, tzinfo=utc.utc), 'channel': 'altinn',
                      'reference': 'AR-1', 'version': report.version, 'content_sha256': digest, **overrides}
            return services.submit(self.user, report, **values)

    def test_a_week_with_a_medicinal_treatment_needs_the_confirmation_and_logs_it(self):
        self.treat([self.m1, self.m2], day(10, 26), day(10, 26))
        with temperature(WARM):
            self.assertEqual(compute.compute(self.draft).questions, ['Q1'])
        with self.assertRaises(ValidationError) as caught:
            self.submit(self.draft)
        self.assertIn('Open question Q1: In virkestoff.mengde, is the amount', caught.exception.message_dict['acknowledged'][0])
        self.assertIsNone(Report.objects.get(pk=self.draft.pk).submitted_at)
        self.submit(self.draft, acknowledged=['Q1'])
        self.assertIsNotNone(Report.objects.get(pk=self.draft.pk).submitted_at)
        entry = AuditLog.objects.filter(entity_type='regulatory report', action='update').latest('created_at')
        self.assertEqual(len(entry.changes['Open questions acknowledged'][1].split('; ')), 1)
        self.assertTrue(entry.changes['Open questions acknowledged'][1].startswith('Q1: In virkestoff.mengde'))

    def test_an_answered_question_needs_no_confirmation(self):
        self.treat([self.m1, self.m2], day(10, 26), day(10, 26))
        OpenQuestion.objects.filter(code='Q1').update(status='answered', answer='The product', answered_on=day(11, 3))
        self.submit(self.draft)
        entry = AuditLog.objects.filter(entity_type='regulatory report', action='update').latest('created_at')
        self.assertNotIn('Open questions acknowledged', entry.changes)

    def test_a_week_without_such_a_value_needs_none(self):
        self.treat([self.m1], day(10, 30), day(10, 30), method='thermal')
        with temperature(WARM):
            self.assertEqual(compute.compute(self.draft).questions, [])
        self.submit(self.draft)

    def test_a_medicated_feed_and_an_injection_rest_on_q2(self):
        self.medicine.administration = 'in_feed'
        self.medicine.save()
        self.treat([self.m1, self.m2], day(10, 26), day(10, 26), method='in_feed')
        with temperature(WARM):
            self.assertEqual(compute.compute(self.draft).questions, ['Q1', 'Q2'])

    def test_the_page_lists_the_question_and_the_box_and_the_post_needs_it(self):
        self.treat([self.m1, self.m2], day(10, 26), day(10, 26))
        url = reverse('reports:report_detail', args=[self.draft.pk])
        with temperature(WARM):
            page = self.client.get(url)
            self.assertContains(page, 'Not confirmed by the authority')
            self.assertContains(page, 'name="acknowledged" value="Q1"')
            data = {'submitted_at': '2026-11-03T09:30', 'channel': 'altinn', 'reference': 'AR-1',
                    'version': str(self.draft.version), 'content_sha256': page.context['preview_hash']}
            refused = self.client.post(reverse('reports:report_submit', args=[self.draft.pk]), data, follow=True)
            self.assertContains(refused, 'Open question Q1')
            self.assertIsNone(Report.objects.get(pk=self.draft.pk).submitted_at)
            self.client.post(reverse('reports:report_submit', args=[self.draft.pk]),
                             {**data, 'acknowledged': ['Q1']}, follow=True)
        self.assertIsNotNone(Report.objects.get(pk=self.draft.pk).submitted_at)
