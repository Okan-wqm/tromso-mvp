"""Company › Knowledge › Knowledge entries: every kind of source and every action through the pages, checked
against the stored rows; exactly one source, held by the database; the review."""
from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from core.audit import message
from core.crud import DRAFT
from core.models import AuditLog
from farm.tests.helpers import make_species, role

from ..models import Document, KnowledgeEntry
from .helpers import KnowledgeTestCase, entry_data
from core.testing import delete_confirmed

SOURCE = ('source_kind', 'document', 'pages', 'section', 'quote', 'citation', 'url', 'expert', 'observed_on')


def stored(entry, *names):
    entry = KnowledgeEntry.all_objects.get(pk=entry.pk)
    return tuple(getattr(entry, name) for name in names)


class EntryTestCase(KnowledgeTestCase):
    def setUp(self):
        super().setUp()
        self.document = Document.objects.create(title='Carbon dioxide and growth', authors='Olsen, Bjørn\nHansen, Kari',
                                                year=2019)

    def create(self, **overrides):
        return self.client.post(reverse('knowledge:knowledgeentry_create'), entry_data(**overrides))

    def edit(self, entry, **overrides):
        overrides.setdefault('version', str(KnowledgeEntry.all_objects.get(pk=entry.pk).version))
        return self.client.post(reverse('knowledge:knowledgeentry_edit', args=[entry.pk]), entry_data(**overrides))

    def make(self, **fields):
        values = {'statement': 'CO2 above 15 mg/L harms smolt.', 'topics': ['water_quality'], 'source_kind': 'document',
                  'document': self.document, **fields}
        return KnowledgeEntry.objects.create(**values)

    def review(self, entry, status='reviewed', version=None):
        version = str(KnowledgeEntry.all_objects.get(pk=entry.pk).version) if version is None else version
        return self.client.post(reverse('knowledge:entry_review', args=[entry.pk]), {'status': status, 'version': version})


class EntryRoundTripTests(EntryTestCase):
    def test_create_read_edit_delete_through_every_kind_of_source(self):
        salmon = make_species()
        # Create: from a document of the library, with the page, the section and its words
        self.create(statement=' In salmon under 50 g, CO2 above 15 mg/L causes disease. ',
                    topics=['health', 'water_quality'], species=[str(salmon.pk)], document=str(self.document.pk),
                    pages='4', section='3.2 Results', quote='Above 15 mg/L, nephrocalcinosis was seen in all tanks.')
        entry = KnowledgeEntry.objects.get()
        self.assertEqual(stored(entry, 'statement', 'topics', *SOURCE, 'status', 'reviewed_by', 'created_by', 'version'), (
            'In salmon under 50 g, CO2 above 15 mg/L causes disease.', ['water_quality', 'health'], 'document',
            self.document, '4', '3.2 Results', 'Above 15 mg/L, nephrocalcinosis was seen in all tanks.', '', '', '',
            None, 'draft', None, self.user, 1))
        self.assertEqual(list(entry.species.all()), [salmon])

        # Read: listed with its source, its page shows the source and the review, the form is filled
        listing = self.client.get(reverse('knowledge:knowledgeentry_list'))
        self.assertEqual(list(listing.context['objects']), [entry])
        self.assertContains(listing, 'Olsen &amp; Hansen (2019), p. 4, 3.2 Results')
        detail = self.client.get(reverse('knowledge:knowledgeentry_detail', args=[entry.pk]))
        self.assertContains(detail, 'Above 15 mg/L, nephrocalcinosis was seen in all tanks.')
        self.assertContains(detail, 'Olsen, B., &amp; Hansen, K. (2019). Carbon dioxide and growth.')
        self.assertContains(detail, 'Not reviewed yet.')
        form = self.client.get(reverse('knowledge:knowledgeentry_edit', args=[entry.pk])).context['form']
        self.assertEqual({name: form[name].value() for name in ('statement', 'topics', 'source_kind', 'document', 'pages',
                                                                 'section', 'quote')}, {
            'statement': 'In salmon under 50 g, CO2 above 15 mg/L causes disease.', 'topics': ['water_quality', 'health'],
            'source_kind': 'document', 'document': self.document.pk, 'pages': '4', 'section': '3.2 Results',
            'quote': 'Above 15 mg/L, nephrocalcinosis was seen in all tanks.'})
        self.assertNotIn('citation', form.fields)

        # Edit: another published source; the document's fields are emptied
        self.edit(entry, statement='A feed order is at least 20 t.', topics=['procurement'], species=[],
                  source_kind='external', citation='Feed AS (2026). Terms of sale.', url='feed.example.com/terms',
                  quote='Minimum order 20 tonnes.')
        self.assertEqual(stored(entry, 'statement', 'topics', *SOURCE, 'updated_by', 'version'), (
            'A feed order is at least 20 t.', ['procurement'], 'external', None, '', '', 'Minimum order 20 tonnes.',
            'Feed AS (2026). Terms of sale.', 'https://feed.example.com/terms', '', None, self.user, 2))
        self.assertEqual(list(entry.species.all()), [])

        # Edit: an expert's observation; the published source's fields are emptied
        self.edit(entry, source_kind='expert', expert='Kari Nordmann, fish health vet', observed_on='2026-10-03')
        self.assertEqual(stored(entry, *SOURCE), ('expert', None, '', '', '', '', '', 'Kari Nordmann, fish health vet',
                                                  date(2026, 10, 3)))
        self.assertContains(self.client.get(reverse('knowledge:knowledgeentry_detail', args=[entry.pk])),
                            'Kari Nordmann, fish health vet')

        # Delete: hidden, not erased
        delete_confirmed(self.client, reverse('knowledge:knowledgeentry_delete', args=[entry.pk]))
        self.assertFalse(KnowledgeEntry.objects.exists())
        self.assertEqual(stored(entry, 'is_deleted', 'deleted_by'), (True, self.user))
        self.assertEqual(list(self.client.get(reverse('knowledge:knowledgeentry_list')).context['objects']), [])

    def test_every_optional_field_can_be_cleared_when_editing(self):
        salmon = make_species()
        entry = self.make(pages='4', section='Results', quote='Words')
        entry.species.add(salmon)
        self.edit(entry, statement=entry.statement, document=str(self.document.pk))
        self.assertEqual(stored(entry, 'pages', 'section', 'quote'), ('', '', ''))
        self.assertEqual(list(KnowledgeEntry.objects.get().species.all()), [])
        self.assertEqual(AuditLog.objects.get().changes, {
            'Species': ['Atlantic salmon (SAL)', None], 'Page(s)': ['4', None], 'Section': ['Results', None],
            'Quote': ['Words', None]})

        external = self.make(source_kind='external', document=None, citation='A citation', url='https://a.no',
                             quote='q')
        self.edit(external, source_kind='external', url='https://a.no')
        self.assertEqual(stored(external, 'citation', 'url', 'quote'), ('', 'https://a.no', ''))
        self.edit(external, source_kind='external', citation='Only a citation')
        self.assertEqual(stored(external, 'citation', 'url'), ('Only a citation', ''))

        expert = self.make(source_kind='expert', document=None, expert='Kari', observed_on=date(2026, 1, 2))
        self.edit(expert, source_kind='expert', expert='Kari')
        self.assertIsNone(stored(expert, 'observed_on')[0])

    def test_the_form_shows_the_fields_of_the_kind_of_source_chosen(self):
        url = reverse('knowledge:knowledgeentry_create')
        form = self.client.get(url).context['form']
        self.assertEqual(form['source_kind'].value(), 'document')
        self.assertEqual([name for name in form.fields if name in SOURCE],
                         ['source_kind', 'document', 'pages', 'section', 'quote'])
        for kind, fields in (('external', ['source_kind', 'citation', 'url', 'quote']),
                             ('expert', ['source_kind', 'expert', 'observed_on'])):
            draft = self.client.post(url, {**entry_data(source_kind=kind), DRAFT: 'source_kind'})
            self.assertEqual([name for name in draft.context['form'].fields if name in SOURCE], fields)
            self.assertEqual(draft.context['open_tab'], 'source')
        self.assertFalse(KnowledgeEntry.objects.exists(), 'a draft saves nothing')
        page = self.client.get(url, headers={'X-Modal': '1'})
        self.assertContains(page, 'data-refresh="_draft"')
        for key, label in (('statement', 'Statement'), ('source', 'Source')):
            self.assertContains(page, f'data-tab="{key}">{label}</button>')

    def test_a_new_entry_from_a_documents_page_starts_with_that_document(self):
        form = self.client.get(reverse('knowledge:knowledgeentry_create'), {'document': self.document.pk}).context['form']
        self.assertEqual((form['source_kind'].value(), form['document'].value()), ('document', self.document.pk))
        for junk in ('not-a-uuid', '00000000-0000-0000-0000-000000000000'):
            form = self.client.get(reverse('knowledge:knowledgeentry_create'), {'document': junk}).context['form']
            self.assertIsNone(form['document'].value())
        page = self.client.get(reverse('knowledge:document_detail', args=[self.document.pk]))
        self.assertContains(page, f"{reverse('knowledge:knowledgeentry_create')}?document={self.document.pk}")


class SourceRuleTests(EntryTestCase):
    def test_each_kind_needs_its_source(self):
        self.assertEqual(self.errors(self.create(document=''))['document'],
                         ['Choose the document in the library it comes from.'])
        self.assertEqual(self.errors(self.create(source_kind='external'))['citation'],
                         ['Give the citation of the source, its web address, or both.'])
        self.assertEqual(self.errors(self.create(source_kind='expert', expert='  '))['expert'],
                         ['Name the person whose observation or advice it is.'])
        self.assertIn('source_kind', self.errors(self.create(source_kind='')))
        self.assertIn('source_kind', self.errors(self.create(source_kind='rumour')))
        self.assertEqual(self.errors(self.create(document=str(self.document.pk), topics=[]))['topics'],
                         ['Tick at least one topic.'])
        self.assertIn('statement', self.errors(self.create(document=str(self.document.pk), statement=' ')))
        self.assertIn('url', self.errors(self.create(source_kind='external', url='ftp://x.example/a')))
        self.assertFalse(KnowledgeEntry.objects.exists())

    def test_a_deleted_document_is_not_offered_as_a_source(self):
        other = Document.objects.create(title='Gone')
        other.soft_delete(self.user)
        self.assertIn('document', self.errors(self.create(document=str(other.pk))))
        form = self.client.get(reverse('knowledge:knowledgeentry_create')).context['form']
        self.assertEqual(list(form.fields['document'].queryset), [self.document])
        self.assertEqual(form.fields['document'].label_from_instance(self.document),
                         'Olsen & Hansen (2019) · Carbon dioxide and growth')

    def test_the_database_holds_exactly_one_source(self):
        cases = {
            'chk_knowledge_entries_document_source': [
                {'source_kind': 'document', 'document': None},
                {'source_kind': 'external', 'citation': 'c', 'document': self.document},
                {'source_kind': 'expert', 'expert': 'Kari', 'pages': '4', 'document': None},
            ],
            'chk_knowledge_entries_external_source': [
                {'source_kind': 'external', 'document': None},
                {'source_kind': 'document', 'url': 'https://a.no'},
                {'source_kind': 'expert', 'expert': 'Kari', 'citation': 'c', 'document': None},
            ],
            'chk_knowledge_entries_expert_source': [
                {'source_kind': 'expert', 'expert': ' ', 'document': None},
                {'source_kind': 'document', 'expert': 'Kari'},
                {'source_kind': 'external', 'citation': 'c', 'observed_on': date(2026, 1, 1), 'document': None},
            ],
            'chk_knowledge_entries_quote': [{'source_kind': 'expert', 'expert': 'Kari', 'quote': 'q', 'document': None}],
            'chk_knowledge_entries_source_kind': [{'source_kind': 'rumour', 'document': None}],
            'chk_knowledge_entries_topics_not_empty': [{'topics': []}],
            'chk_knowledge_entries_topics': [{'topics': ['astrology']}],
            'chk_knowledge_entries_statement': [{'statement': '  '}],
            'chk_knowledge_entries_review': [
                {'status': 'approved'},
                {'status': 'reviewed'}, {'status': 'draft', 'reviewed_by': self.user},
                {'status': 'reviewed', 'reviewed_by': self.user},
            ],
            'chk_knowledge_entries_url': [{'source_kind': 'external', 'url': 'javascript:x', 'document': None}],
        }
        for constraint, rows in cases.items():
            for values in rows:
                with self.subTest(constraint=constraint, values=values), \
                        self.assertRaisesMessage(IntegrityError, constraint), transaction.atomic():
                    self.make(**values)
        self.assertFalse(KnowledgeEntry.all_objects.exists())
        for values in ({}, {'source_kind': 'external', 'url': 'https://a.no', 'quote': 'q', 'document': None},
                       {'source_kind': 'expert', 'expert': 'Kari', 'observed_on': date(2026, 1, 1), 'document': None},
                       {'status': 'reviewed', 'reviewed_by': self.user, 'reviewed_at': timezone.now()}):
            self.make(**values)
        self.assertEqual(KnowledgeEntry.objects.count(), 4)


class ReviewTests(EntryTestCase):
    def test_review_records_who_and_when_and_an_edit_takes_it_back_to_draft(self):
        entry = self.make()
        before = timezone.now()
        response = self.review(entry)
        self.assertRedirects(response, reverse('knowledge:knowledgeentry_detail', args=[entry.pk]),
                             fetch_redirect_response=False)
        status, reviewer, when, version = stored(entry, 'status', 'reviewed_by', 'reviewed_at', 'version')
        self.assertEqual((status, reviewer, version), ('reviewed', self.user, 2))
        self.assertGreaterEqual(when, before)
        logged = AuditLog.objects.get()
        self.assertEqual(logged.changes['Status'], [message('Draft'), message('Reviewed')])
        self.assertEqual(logged.changes['Reviewed by'], [None, 'kari'])
        detail = self.client.get(reverse('knowledge:knowledgeentry_detail', args=[entry.pk]))
        self.assertContains(detail, 'by kari,')
        self.assertContains(detail, 'Back to draft')

        # Saving it unchanged keeps the review; changing what it says takes it back to draft
        self.edit(entry)
        self.assertEqual(stored(entry, 'status', 'reviewed_by'), ('reviewed', self.user))
        response = self.edit(entry, statement='CO2 above 20 mg/L harms smolt.', document=str(self.document.pk))
        self.assertEqual(stored(entry, 'status', 'reviewed_by', 'reviewed_at'), ('draft', None, None))
        self.assertContains(self.client.get(response['Location']), 'after this change it is a draft again')
        self.assertEqual(AuditLog.objects.order_by('-created_at').first().changes['Status'],
                         [message('Reviewed'), message('Draft')])

    def test_a_species_or_source_change_also_takes_it_back_to_draft(self):
        salmon = make_species()
        for change in ({'species': [str(salmon.pk)]}, {'pages': '9'}):
            entry = self.make()
            self.review(entry)
            self.edit(entry, document=str(self.document.pk), **change)
            self.assertEqual(stored(entry, 'status'), ('draft',), change)

    def test_back_to_draft_and_a_stale_review_is_refused(self):
        entry = self.make()
        self.review(entry)
        self.review(entry, status='draft')
        self.assertEqual(stored(entry, 'status', 'reviewed_by', 'reviewed_at', 'version'), ('draft', None, None, 3))
        response = self.review(entry, version='1', )
        self.assertEqual(stored(entry, 'status'), ('draft',))
        page = self.client.get(response['Location'])
        self.assertContains(page, 'Someone changed this entry while you were reading it.')
        self.assertEqual(self.review(entry, status='approved').status_code, 400)
        self.assertEqual(self.client.get(reverse('knowledge:entry_review', args=[entry.pk])).status_code, 405)

    def test_reviewing_needs_the_edit_permission(self):
        entry = self.make()
        reader = get_user_model().objects.create_user('ola', 'ola@example.com', 'x')
        reader.groups.add(role('Student', 'view_knowledgeentry', 'view_document'))
        self.client.force_login(reader)
        self.assertEqual(self.review(entry).status_code, 403)
        self.assertEqual(stored(entry, 'status'), ('draft',))
        detail = self.client.get(reverse('knowledge:knowledgeentry_detail', args=[entry.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, 'Mark as reviewed')
        self.assertNotContains(detail, f'href="{reverse("knowledge:knowledgeentry_edit", args=[entry.pk])}"')
        for url in (reverse('knowledge:knowledgeentry_create'), reverse('knowledge:knowledgeentry_edit', args=[entry.pk]),
                    reverse('knowledge:knowledgeentry_delete', args=[entry.pk])):
            self.assertEqual(self.client.post(url, entry_data()).status_code, 403, url)

    def test_the_review_tab_is_on_the_form_of_an_existing_entry(self):
        entry = self.make()
        page = self.client.get(reverse('knowledge:knowledgeentry_edit', args=[entry.pk]), headers={'X-Modal': '1'})
        self.assertContains(page, 'data-tab="review">Review</button>')
        self.assertContains(page, f'action="{reverse("knowledge:entry_review", args=[entry.pk])}"')
        self.assertNotContains(self.client.get(reverse('knowledge:knowledgeentry_create')), 'data-tab="review"')
