"""The register of questions for the authority: the twelve of the coverage review are there as open, and the reports area creates,
reads, answers and deletes them through the pages, each checked against the stored rows and the database's rules."""
from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.urls import reverse

from core.models import AuditLog
from core.softdelete import plan_delete
from farm.tests.helpers import role

from ..models import OpenQuestion
from .helpers import ReportTestCase

PERMISSIONS = ('view_openquestion', 'add_openquestion', 'change_openquestion', 'delete_openquestion', 'view_auditlog')


class QuestionTests(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.user.groups.add(role('Question keeper', *PERMISSIONS))

    def data(self, **overrides):
        return {'code': 'Q20', 'question': 'Is the biomass form filed in Altinn?', 'authority': 'Fiskeridirektoratet',
                'affects': 'Biomass report, channel', 'status': 'open', 'asked_by': 'Kari Nord',
                'asked_on': '2026-11-04', 'answer': '', 'answered_on': '', **overrides}

    def test_the_twelve_questions_of_the_coverage_review_are_listed_as_open(self):
        codes = list(OpenQuestion.objects.order_by('created_at').values_list('code', flat=True))
        self.assertEqual(sorted(codes, key=lambda code: int(code[1:])), [f'Q{number}' for number in range(1, 13)])
        self.assertEqual(set(OpenQuestion.objects.values_list('status', flat=True)), {'open'})
        page = self.client.get(reverse('reports:openquestion_list'))
        self.assertContains(page, 'Questions for the authority')
        self.assertContains(page, 'In virkestoff.mengde, is the amount')

    def test_create_read_edit_delete(self):
        response = self.client.post(reverse('reports:openquestion_create'), self.data())
        self.assertEqual(response.status_code, 302)
        question = OpenQuestion.objects.get(code='Q20')
        self.assertEqual((question.question, question.authority, question.affects, question.status, question.asked_by,
                          question.asked_on, question.answer, question.answered_on, question.created_by),
                         ('Is the biomass form filed in Altinn?', 'Fiskeridirektoratet', 'Biomass report, channel',
                          'open', 'Kari Nord', date(2026, 11, 4), '', None, self.user))
        listed = self.client.get(reverse('reports:openquestion_list'), {'q': 'biomass form'})
        self.assertEqual(list(listed.context['objects']), [question])
        answer = self.data(status='answered', answer='Still Altinn, they said by mail on 5 November.',
                           answered_on='2026-11-05', version=str(question.version))
        self.client.post(reverse('reports:openquestion_edit', args=[question.pk]), answer)
        question.refresh_from_db()
        self.assertEqual((question.status, question.answer, question.answered_on, question.version),
                         ('answered', 'Still Altinn, they said by mail on 5 November.', date(2026, 11, 5), 2))
        entry = AuditLog.objects.filter(entity_type='open question', action='update').latest('created_at')
        self.assertEqual(entry.changes['Answer'], [None, 'Still Altinn, they said by mail on 5 November.'])
        self.assertEqual(self.client.get(reverse('reports:openquestion_list'), {'status': 'open'}).context[
            'chosen_status'], 'open')
        self.client.post(reverse('reports:openquestion_delete', args=[question.pk]))
        self.assertTrue(OpenQuestion.all_objects.get(pk=question.pk).is_deleted)
        self.assertFalse(OpenQuestion.objects.filter(code='Q20').exists())
        self.assertEqual(plan_delete(OpenQuestion.all_objects.get(pk=question.pk)).blockers, [])

    def test_what_the_form_refuses(self):
        response = self.client.post(reverse('reports:openquestion_create'), self.data(code='Q1'))
        self.assertEqual(response.context['form'].errors['code'] if 'code' in response.context['form'].errors
                         else response.context['form'].non_field_errors(), ['Another question has this number.'])
        response = self.client.post(reverse('reports:openquestion_create'), self.data(status='answered'))
        self.assertIn('An answered question has its answer and the day it came', ' '.join(
            response.context['form'].non_field_errors() + sum(response.context['form'].errors.values(), [])))
        self.assertFalse(OpenQuestion.objects.filter(code='Q20').exists())

    def test_the_database_holds_the_answer_rule_and_the_days(self):
        base = {'code': 'Q30', 'question': 'x', 'authority': 'y', 'affects': 'z'}
        for fields in ({'status': 'answered'},                                   # no answer
                       {'status': 'answered', 'answer': 'a'},                    # no day
                       {'status': 'open', 'answered_on': date(2026, 11, 5)},     # a day without an answer
                       {'status': 'maybe'},
                       {'code': 'Q1'},                                           # the number is taken
                       {'asked_on': date(2026, 11, 5), 'status': 'answered', 'answer': 'a',
                        'answered_on': date(2026, 11, 4)}):
            with self.subTest(fields), self.assertRaises(IntegrityError), transaction.atomic():
                OpenQuestion.objects.create(**{**base, **fields})

    def test_each_action_needs_its_permission(self):
        reader = get_user_model().objects.create_user('ola', 'ola@example.com', 'x')
        reader.groups.add(role('Question reader', 'view_openquestion'))
        self.client.force_login(reader)
        self.assertEqual(self.client.get(reverse('reports:openquestion_list')).status_code, 200)
        question = OpenQuestion.objects.get(code='Q1')
        for url in (reverse('reports:openquestion_create'), reverse('reports:openquestion_edit', args=[question.pk]),
                    reverse('reports:openquestion_delete', args=[question.pk])):
            self.assertEqual(self.client.post(url, self.data()).status_code, 403, url)
        nobody = get_user_model().objects.create_user('per', 'per@example.com', 'x')
        self.client.force_login(nobody)
        self.assertEqual(self.client.get(reverse('reports:openquestion_list')).status_code, 403)
