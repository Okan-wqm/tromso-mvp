"""The stock operation "Issue" (taking stock out for use) is a word of its own in every language: it shared its message
with a journal's issue (knowledge.Document.issue), so Turkish read it as "Sayı" (a number) on the storage page."""
from django.test import SimpleTestCase
from django.utils import translation

from knowledge.models import Document

from ..models import OperationKind
from ..views import DEPARTURES

STOCK_ISSUE = {'tr': 'Çıkış', 'nb': 'Uttak', 'en': 'Issue'}
JOURNAL_ISSUE = {'tr': 'Sayı', 'nb': 'Hefte', 'en': 'Issue'}


class IssueWordTests(SimpleTestCase):
    def test_a_stock_issue_is_not_a_journal_issue(self):
        for language in ('en', 'tr', 'nb'):
            with self.subTest(language=language), translation.override(language):
                self.assertEqual(str(OperationKind.ISSUE.label), STOCK_ISSUE[language])
                self.assertEqual(str(DEPARTURES['issue'][1]), STOCK_ISSUE[language])
                self.assertEqual(str(Document._meta.get_field('issue').verbose_name), JOURNAL_ISSUE[language])
