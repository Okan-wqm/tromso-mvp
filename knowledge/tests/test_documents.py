"""Company › Knowledge › Library: every field and action through the pages, checked against the stored rows; the
file's rules, storage and serving; the delete plan; the activity log; the citation."""
import os
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import FETCH_ONE, FETCH_PEERS
from django.test import override_settings
from django.urls import reverse

from core import access, navigation
from core.audit import message
from core.models import AuditLog
from core.softdelete import plan_delete, restore
from farm.tests.helpers import make_species, role

from ..models import Document, DocumentPage, KnowledgeEntry, TextStatus
from .helpers import KnowledgeTestCase, document_data, make_pdf, upload

FIELDS = ('title', 'authors', 'year', 'venue', 'volume', 'issue', 'page_range', 'doi', 'url', 'abstract', 'language',
          'topics')


def stored(document, *names):
    document = Document.all_objects.get(pk=document.pk)
    return tuple(getattr(document, name) for name in names)


class DocumentTestCase(KnowledgeTestCase):
    def create(self, file=None, **overrides):
        data = document_data(**overrides)
        if file is not None:
            data['file'] = file
        return self.client.post(reverse('knowledge:document_create'), data)

    def edit(self, document, file=None, **overrides):
        overrides.setdefault('version', str(Document.all_objects.get(pk=document.pk).version))
        data = document_data(**overrides)
        if file is not None:
            data['file'] = file
        return self.client.post(reverse('knowledge:document_edit', args=[document.pk]), data)

    def make(self, title='Carbon dioxide and the growth of Atlantic salmon', content=None, **fields):
        document = Document(title=title, **fields)
        if content is not None:
            document.file = upload(content)
        document.save()
        return document

    def media_files(self):
        root = Path(self.media)
        return sorted(str(path.relative_to(root)).replace(os.sep, '/') for path in root.rglob('*') if path.is_file())


class DocumentRoundTripTests(DocumentTestCase):
    def setUp(self):
        super().setUp()
        self.salmon = make_species()
        self.trout = make_species(code='RBT', common_name='Rainbow trout', scientific_name='Oncorhynchus mykiss',
                                  local_name='Regnbueørret')

    def test_create_read_edit_delete(self):
        # Create: every field typed, and a PDF with text on two of its three pages
        pdf = make_pdf('Carbon dioxide above 15 mg/L', None, 'Nephrocalcinosis in smolt')
        response = self.create(
            file=upload(pdf, name='Olsen 2019 CO2.pdf'), title=' Carbon dioxide and growth ',
            authors=' Olsen,  Bjørn Erik \n\n Hansen, Kari ', year='2019', venue='Aquaculture', volume='512',
            issue='3', page_range='45–67', doi='https://doi.org/10.1016/J.AQUA.2019.01.001',
            url='example.com/olsen', abstract='We grew salmon at four CO2 levels.', language='en',
            topics=['health', 'water_quality'], species=[str(self.salmon.pk), str(self.trout.pk)])
        document = Document.objects.get()
        self.assertRedirects(response, reverse('knowledge:document_edit', args=[document.pk]),
                             fetch_redirect_response=False)
        self.assertEqual(stored(document, *FIELDS, 'created_by', 'version'), (
            'Carbon dioxide and growth', 'Olsen, Bjørn Erik\nHansen, Kari', 2019, 'Aquaculture', '512', '3', '45–67',
            '10.1016/J.AQUA.2019.01.001', 'https://example.com/olsen', 'We grew salmon at four CO2 levels.', 'en',
            ['water_quality', 'health'], self.user, 1))
        self.assertEqual(set(document.species.all()), {self.salmon, self.trout})
        self.assertEqual(stored(document, 'file_name', 'file_size', 'text_status', 'page_count', 'text_error'),
                         ('Olsen 2019 CO2.pdf', len(pdf), TextStatus.EXTRACTED, 3, ''))
        self.assertRegex(document.file.name, r'^knowledge/documents/[0-9a-f]{32}\.pdf$')
        self.assertEqual(self.media_files(), [document.file.name])
        self.assertEqual(default_storage.open(document.file.name).read(), pdf)
        pages = list(document.pages.values_list('number', 'text'))
        self.assertEqual(pages, [(1, 'Carbon dioxide above 15 mg/L'), (2, ''), (3, 'Nephrocalcinosis in smolt')])

        # Read: listed, the read page has the reference, and the edit form is filled from the database
        listing = self.client.get(reverse('knowledge:document_list'))
        self.assertEqual(list(listing.context['objects']), [document])
        self.assertContains(listing, 'Olsen &amp; Hansen (2019)')
        detail = self.client.get(reverse('knowledge:document_detail', args=[document.pk]))
        self.assertContains(detail, 'Olsen, B. E., &amp; Hansen, K. (2019). Carbon dioxide and growth. '
                                    '<i>Aquaculture</i>, <i>512</i>(3), 45–67.')
        self.assertContains(detail, 'https://doi.org/10.1016/J.AQUA.2019.01.001')
        self.assertContains(detail, 'Text found on 2 of 3 pages.')
        self.assertContains(detail, reverse('knowledge:document_file', args=[document.pk]))
        form = self.client.get(reverse('knowledge:document_edit', args=[document.pk])).context['form']
        self.assertEqual({name: form[name].value() for name in FIELDS + ('version',)}, {
            'title': 'Carbon dioxide and growth', 'authors': 'Olsen, Bjørn Erik\nHansen, Kari', 'year': 2019,
            'venue': 'Aquaculture', 'volume': '512', 'issue': '3', 'page_range': '45–67',
            'doi': '10.1016/J.AQUA.2019.01.001', 'url': 'https://example.com/olsen',
            'abstract': 'We grew salmon at four CO2 levels.', 'language': 'en', 'topics': ['water_quality', 'health'],
            'version': 1})
        self.assertEqual(set(form['species'].value()), {self.salmon.pk, self.trout.pk})

        # Edit: every field changed, and the PDF replaced; the old file goes once the change is committed
        old_file = document.file.name
        new_pdf = make_pdf('Rainbow trout feeding tables')
        with self.captureOnCommitCallbacks(execute=True):
            self.edit(document, file=upload(new_pdf, name='trout.pdf'), title='Feeding rainbow trout',
                      authors='Mattilsynet', year='2021', venue='Rapport', volume='7', issue='1', page_range='1–30',
                      doi='10.1000/xyz', url='https://mattilsynet.no/rapport', abstract='Tables.', language='no',
                      topics=['feeding'], species=[str(self.trout.pk)])
        self.assertEqual(stored(document, *FIELDS, 'updated_by', 'version'), (
            'Feeding rainbow trout', 'Mattilsynet', 2021, 'Rapport', '7', '1', '1–30', '10.1000/xyz',
            'https://mattilsynet.no/rapport', 'Tables.', 'no', ['feeding'], self.user, 2))
        self.assertEqual(list(document.species.all()), [self.trout])
        document.refresh_from_db()
        self.assertEqual((document.file_name, document.file_size, document.page_count), ('trout.pdf', len(new_pdf), 1))
        self.assertEqual(list(document.pages.values_list('text', flat=True)), ['Rainbow trout feeding tables'])
        self.assertEqual(self.media_files(), [document.file.name])
        self.assertNotEqual(document.file.name, old_file)

        # Delete: hidden, not erased; its file and pages stay for a restore
        self.client.post(reverse('knowledge:document_delete', args=[document.pk]))
        self.assertFalse(Document.objects.exists())
        self.assertEqual(stored(document, 'is_deleted', 'deleted_by'), (True, self.user))
        self.assertEqual(self.media_files(), [document.file.name])
        self.assertEqual(DocumentPage.objects.count(), 1)
        self.assertEqual(list(self.client.get(reverse('knowledge:document_list')).context['objects']), [])
        self.assertEqual(self.client.get(reverse('knowledge:document_detail', args=[document.pk])).status_code, 404)

    def test_every_optional_field_can_be_cleared_when_editing(self):
        document = self.make(content=make_pdf('Some text'), authors='Olsen, B.', year=2019, venue='V', volume='1',
                             issue='2', page_range='3', doi='10.1000/a', url='https://a.no', abstract='x',
                             language='en', topics=['health'])
        document.species.add(self.salmon)
        file_name = document.file.name
        with self.captureOnCommitCallbacks(execute=True):
            self.edit(document, **{'file-clear': 'on'})
        self.assertEqual(stored(document, *FIELDS[1:]), ('', None, '', '', '', '', '', '', '', '', []))
        self.assertEqual(list(Document.objects.get().species.all()), [])
        self.assertEqual(stored(document, 'file', 'file_name', 'file_size', 'text_status', 'page_count'),
                         ('', '', None, TextStatus.NO_FILE, None))
        self.assertFalse(DocumentPage.objects.exists())
        self.assertFalse(default_storage.exists(file_name))
        self.assertEqual(AuditLog.objects.get().changes, {
            'Authors': ['Olsen, B.', None], 'Year': ['2019', None], 'Published in': ['V', None], 'Volume': ['1', None],
            'Issue': ['2', None], 'Pages': ['3', None], 'DOI': ['10.1000/a', None], 'Web address': ['https://a.no', None],
            'Abstract': ['x', None], 'Language': [message('English'), None], 'Topics': [[message('Health')], None],
            'Species': ['Atlantic salmon (SAL)', None], 'PDF file': ['article.pdf', None],
            'Text': [message('Text found'), None], 'Number of pages': ['1', None],
        })

    def test_a_save_that_is_rolled_back_keeps_the_file(self):
        document = self.make(content=make_pdf('Kept'))
        file_name = document.file.name
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            self.edit(document, file=upload(make_pdf('New')))
        self.assertEqual(len(callbacks), 1, 'the old file is removed only once the change is committed')
        self.assertTrue(default_storage.exists(file_name))

    def test_the_form_opens_in_the_dialog_with_its_tabs(self):
        response = self.client.get(reverse('knowledge:document_create'), headers={'X-Modal': '1'})
        self.assertContains(response, 'class="modal-head"')
        self.assertContains(response, 'enctype="multipart/form-data"')
        for key, label in (('reference', 'Reference'), ('content', 'Content'), ('file', 'File')):
            self.assertContains(response, f'data-tab="{key}">{label}</button>')
        self.assertContains(response, 'accept="application/pdf,.pdf"')
        self.assertContains(response, 'A PDF of up to 20.0\xa0MB.')

    def test_the_edit_form_shows_the_file_by_its_own_name_never_its_storage_address(self):
        document = self.make(content=make_pdf('x'))
        page = self.client.get(reverse('knowledge:document_edit', args=[document.pk])).content.decode()
        self.assertIn(reverse('knowledge:document_file', args=[document.pk]), page)
        self.assertIn('article.pdf', page)
        self.assertNotIn(document.file.name, page)
        self.assertIn('Remove the file', page)
        self.assertIn('Text found on 1 of 1 page.', page)


class FileRuleTests(DocumentTestCase):
    def test_a_pdf_without_text_is_kept_and_said_to_have_no_text(self):
        response = self.create(file=upload(make_pdf(None, None), name='scan.pdf'))
        document = Document.objects.get()
        self.assertEqual(stored(document, 'text_status', 'page_count', 'text_error'), (TextStatus.NO_TEXT, 2, ''))
        self.assertEqual(list(document.pages.values_list('text', flat=True)), ['', ''])
        page = self.client.get(response['Location'])
        self.assertContains(page, 'No text found: the pages are images, as in a scan.')

    def test_a_damaged_pdf_is_kept_with_the_reason_its_text_could_not_be_read(self):
        self.create(file=upload(b'%PDF-1.4\nnot really a PDF'))
        document = Document.objects.get()
        self.assertEqual(document.text_status, TextStatus.FAILED)
        self.assertIsNone(document.page_count)
        self.assertTrue(document.text_error)
        self.assertFalse(document.pages.exists())
        self.assertContains(self.client.get(reverse('knowledge:document_detail', args=[document.pk])),
                            'The text could not be read:')

    def test_a_file_that_is_not_a_pdf_is_refused(self):
        png = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
        errors = self.errors(self.create(file=upload(png, name='photo.pdf', content_type='application/pdf')))
        self.assertEqual(errors['file'], ['This file is not a PDF.'])
        errors = self.errors(self.create(file=upload(make_pdf('x'), name='article.txt')))
        self.assertIn('File extension “txt” is not allowed.', errors['file'][0])
        errors = self.errors(self.create(file=upload(b'', name='empty.pdf')))
        self.assertEqual(errors['file'], ['The submitted file is empty.'])
        self.assertFalse(Document.all_objects.exists())
        self.assertEqual(self.media_files(), [])

    def test_a_file_above_the_limit_is_refused(self):
        content = make_pdf('x' * 2000)
        with override_settings(KNOWLEDGE_MAX_FILE_BYTES=len(content) - 1):
            errors = self.errors(self.create(file=upload(content)))
        self.assertIn('the library takes PDFs of up to', errors['file'][0])
        self.assertFalse(Document.all_objects.exists())
        with override_settings(KNOWLEDGE_MAX_FILE_BYTES=len(content)):
            self.create(file=upload(content))
        self.assertTrue(Document.objects.exists())

    def test_a_long_file_name_is_kept_cut_to_its_column_with_its_extension(self):
        name = 'x' * 300 + '.pdf'
        self.create(file=upload(make_pdf('y'), name=name))
        document = Document.objects.get()
        self.assertEqual(len(document.file_name), 255)
        self.assertTrue(document.file_name.endswith('.pdf'))


class FileServingTests(DocumentTestCase):
    def setUp(self):
        super().setUp()
        self.pdf = make_pdf('Carbon dioxide')
        self.document = self.make(content=self.pdf)
        self.url = reverse('knowledge:document_file', args=[self.document.pk])

    def test_the_file_is_sent_to_a_person_who_may_read_the_library(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), self.pdf)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(response['Content-Disposition'], 'inline; filename="article.pdf"')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response['Cache-Control'], 'private, no-cache')
        download = self.client.get(self.url, {'download': ''})
        self.assertEqual(download['Content-Disposition'], 'attachment; filename="article.pdf"')

    def test_not_without_signing_in_nor_without_the_read_permission(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertRedirects(response, f"{reverse('login')}?next={self.url}", fetch_redirect_response=False)
        stranger = get_user_model().objects.create_user('ola', 'ola@example.com', 'x')
        stranger.groups.add(role('Feeder', 'view_site'))
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.get(reverse('knowledge:document_text', args=[self.document.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('knowledge:document_detail', args=[self.document.pk])).status_code,
                         403)

    def test_the_storage_has_no_public_address(self):
        for path in (f'/media/{self.document.file.name}', f'/{self.document.file.name}'):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_no_file_for_a_deleted_document_or_one_without_a_file(self):
        bare = self.make(title='A book')
        self.assertEqual(self.client.get(reverse('knowledge:document_file', args=[bare.pk])).status_code, 404)
        self.client.post(reverse('knowledge:document_delete', args=[self.document.pk]))
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url).status_code, 405)

    def test_a_file_missing_from_the_storage_is_not_found_rather_than_an_error(self):
        default_storage.delete(self.document.file.name)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_the_text_page_shows_the_text_page_by_page(self):
        document = self.make(title='Report', content=make_pdf('First page text', None, 'Third page text',
                                                              first_label=233))
        page = self.client.get(reverse('knowledge:document_text', args=[document.pk]))
        self.assertContains(page, 'First page text')
        self.assertContains(page, 'Third page text')
        self.assertContains(page, '(printed as 235)')
        self.assertContains(page, 'No text on this page.')


class LoadingTests(DocumentTestCase):
    def test_a_loaded_document_keeps_its_querysets_fetch_mode_and_remembers_its_stored_file(self):
        # Document.from_db keeps the file as stored; it must still hand Django the fetch mode the queryset asked for
        # (Django 6.1: a from_db() without fetch_mode is deprecated and loses it).
        made = self.make(content=make_pdf('x'))
        for mode in (FETCH_PEERS, FETCH_ONE):
            with self.subTest(mode=mode):
                document = Document.objects.fetch_mode(mode).get(pk=made.pk)
                self.assertIs(document._state.fetch_mode, mode)
                self.assertEqual(document._stored_file, made.file.name)
        deferred = Document.objects.defer('file').get(pk=made.pk)
        self.assertIsNone(deferred._stored_file)


class DocumentRuleTests(DocumentTestCase):
    def test_a_doi_is_stored_without_its_link_and_is_unique_among_live_documents_whatever_its_case(self):
        self.create(doi='doi:10.1000/ABC')
        first = Document.objects.get()
        self.assertEqual(first.doi, '10.1000/ABC')
        errors = self.errors(self.create(title='Another', doi='https://dx.doi.org/10.1000/abc'))
        self.assertEqual(errors['doi'], ['Another document in the library has this DOI.'])
        self.assertEqual(self.errors(self.create(title='Bad', doi='11.1000/abc'))['doi'],
                         ['A DOI starts with 10. and has no spaces, e.g. 10.1016/j.aquaculture.2019.01.001.'])
        self.client.post(reverse('knowledge:document_delete', args=[first.pk]))
        self.create(title='Again', doi='10.1000/abc')
        self.assertEqual(Document.objects.get().title, 'Again')

    def test_year_title_and_address_are_checked(self):
        self.assertIn('year', self.errors(self.create(year='1499')))
        self.assertEqual(self.errors(self.create(year='2999'))['year'],
                         ['Ensure this value is less than or equal to 2100.'])
        self.assertIn('later than next year', self.errors(self.create(year='2099'))['year'][0])
        self.assertIn('title', self.errors(self.create(title='  ')))
        self.assertIn('url', self.errors(self.create(url='ftp://example.com/x.pdf')))
        self.assertIn('url', self.errors(self.create(url='javascript:alert(1)')))
        self.assertFalse(Document.all_objects.exists())

    def test_the_database_holds_the_rules_whatever_writes_the_row(self):
        document = self.make(content=make_pdf('x'))
        cases = {
            'chk_documents_authors': {'authors': 'Olsen\n\nHansen'},
            'chk_documents_doi': {'doi': 'not a doi'},
            'chk_documents_year': {'year': 1200},
            'chk_documents_url': {'url': 'ftp://x'},
            'chk_documents_topics': {'topics': ['astrology']},
            'chk_documents_language': {'language': 'xx'},
            'chk_documents_file': {'file_name': ''},
            'chk_documents_text_error': {'text_error': 'why'},
            'chk_documents_page_count': {'page_count': None},
            'chk_documents_title': {'title': ' '},
        }
        for constraint, values in cases.items():
            with self.subTest(constraint), self.assertRaisesMessage(IntegrityError, constraint), transaction.atomic():
                Document.objects.filter(pk=document.pk).update(**values)
        with self.assertRaisesMessage(IntegrityError, 'chk_documents_file'), transaction.atomic():
            Document.objects.filter(pk=document.pk).update(file='', file_name='', file_size=None, page_count=None)
        with self.assertRaisesMessage(IntegrityError, 'uq_document_pages_number'), transaction.atomic():
            DocumentPage.objects.create(document=document, number=1, text='again')

    def test_the_search_vector_follows_the_text_whatever_writes_it(self):
        document = self.make(title='Lumpfish welfare')
        Document.objects.filter(pk=document.pk).update(title='Wrasse welfare')
        document.refresh_from_db()
        self.assertIn("'wrasse':1A", document.search_vector)


class DeletePlanTests(DocumentTestCase):
    def test_a_document_cited_by_a_live_entry_cannot_be_deleted(self):
        document = self.make()
        entry = KnowledgeEntry.objects.create(statement='CO2 above 15 mg/L harms smolt.', topics=['water_quality'],
                                              source_kind='document', document=document, pages='4')
        confirm = self.client.get(reverse('knowledge:document_delete', args=[document.pk]))
        self.assertContains(confirm, 'cannot be deleted yet')
        self.assertContains(confirm, '1 knowledge entry still belongs to it.')
        self.assertContains(confirm, 'disabled')
        self.client.post(reverse('knowledge:document_delete', args=[document.pk]))
        self.assertTrue(Document.objects.filter(pk=document.pk).exists())

        # Once the entry is deleted the document can go; restoring the entry then waits for the document
        self.client.post(reverse('knowledge:knowledgeentry_delete', args=[entry.pk]))
        self.assertTrue(plan_delete(document).can_delete)
        self.client.post(reverse('knowledge:document_delete', args=[document.pk]))
        self.assertFalse(Document.objects.exists())

    def test_a_restore_brings_the_document_back_with_its_file_and_an_entry_waits_for_its_document(self):
        document = self.make(content=make_pdf('Kept text'), doi='10.1000/kept')
        entry = KnowledgeEntry.objects.create(statement='Kept.', topics=['health'], source_kind='document',
                                              document=document)
        entry.soft_delete(self.user)
        document.soft_delete(self.user)
        with self.assertRaisesMessage(ValidationError, 'is deleted'), transaction.atomic():
            restore(KnowledgeEntry.all_objects.get(pk=entry.pk), self.user)
        restore(Document.all_objects.get(pk=document.pk), self.user)
        restored = Document.objects.get()
        self.assertEqual((restored.text_status, restored.page_count, restored.doi), (TextStatus.EXTRACTED, 1, '10.1000/kept'))
        self.assertTrue(default_storage.exists(restored.file.name))
        self.assertEqual(self.client.get(reverse('knowledge:document_file', args=[document.pk])).status_code, 200)
        restore(KnowledgeEntry.all_objects.get(pk=entry.pk), self.user)
        self.assertEqual(list(KnowledgeEntry.objects.all()), [entry])
        restored_types = AuditLog.objects.filter(action='restore').order_by('created_at').values_list('entity_type',
                                                                                                    flat=True)
        self.assertEqual(list(restored_types), ['document', 'knowledge entry'])

    def test_deleting_a_species_keeps_the_documents_link_rows_out_of_sight(self):
        salmon = make_species()
        document = self.make()
        document.species.add(salmon)
        self.assertEqual(plan_delete(salmon).unlinked, [document])
        salmon.soft_delete(self.user)
        self.assertEqual(list(Document.objects.get().species.all()), [])
        self.assertEqual(Document.species.through.objects.count(), 1)


class ActivityLogTests(DocumentTestCase):
    def test_metadata_and_the_file_are_logged_never_the_text(self):
        self.create(file=upload(make_pdf('The secret full text of the article'), name='olsen.pdf'),
                    authors='Olsen, Bjørn', topics=['health'])
        document = Document.objects.get()
        created = AuditLog.objects.get()
        self.assertEqual((created.action, created.entity_type, created.entity_id), ('create', 'document', str(document.pk)))
        self.assertEqual(created.changes, {
            'Title': [None, 'Carbon dioxide and the growth of Atlantic salmon'], 'Authors': [None, 'Olsen, Bjørn'],
            'Topics': [None, [message('Health')]], 'PDF file': [None, 'olsen.pdf'],
            'Text': [None, message('Text found')], 'Number of pages': [None, '1'],
        })
        self.assertNotIn('secret', str(list(AuditLog.objects.values_list('changes', flat=True))))
        history = self.client.get(reverse('knowledge:document_edit', args=[document.pk])).context['history']
        self.assertEqual(list(history), [created])


class AccessTests(DocumentTestCase):
    def test_the_library_sits_in_the_company_panel_under_knowledge(self):
        place = navigation.place('knowledge.view_document')
        self.assertEqual((str(place.workspace.label), str(place.group.label), str(place.entry.label)),
                         ('Company', 'Knowledge', 'Library'))
        self.assertEqual(str(place.path), 'Company · Knowledge')
        areas = {area.model: area.actions for area in access.areas()}
        self.assertEqual(areas['knowledge.Document'], ('view', 'add', 'change', 'delete'))
        self.assertEqual(areas['knowledge.KnowledgeEntry'], ('view', 'add', 'change', 'delete'))
        home = self.client.get(reverse('home'))
        self.assertContains(home, reverse('knowledge:document_list'))
        self.assertContains(home, reverse('knowledge:knowledgeentry_list'))

    def test_a_reader_reads_and_changes_nothing(self):
        document = self.make(content=make_pdf('x'))
        reader = get_user_model().objects.create_user('ola', 'ola@example.com', 'x')
        reader.groups.add(role('Student', 'view_document'))
        self.client.force_login(reader)
        listing = self.client.get(reverse('knowledge:document_list'))
        self.assertEqual(list(listing.context['objects']), [document])
        self.assertNotContains(listing, f'href="{reverse("knowledge:document_edit", args=[document.pk])}"')
        self.assertNotContains(listing, reverse('knowledge:document_create'))
        detail = self.client.get(reverse('knowledge:document_detail', args=[document.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, f'href="{reverse("knowledge:document_edit", args=[document.pk])}"')
        self.assertNotContains(detail, 'Knowledge taken from it')       # entries are an area of their own
        self.assertEqual(self.client.get(reverse('knowledge:document_file', args=[document.pk])).status_code, 200)
        for url, method in ((reverse('knowledge:document_create'), 'get'),
                            (reverse('knowledge:document_edit', args=[document.pk]), 'post'),
                            (reverse('knowledge:document_delete', args=[document.pk]), 'post')):
            self.assertEqual(getattr(self.client, method)(url, document_data()).status_code, 403, url)
        self.assertEqual(stored(document, 'title', 'is_deleted'), (document.title, False))


class DatabaseViewerTests(DocumentTestCase):
    def test_the_knowledge_tables_are_shown_and_a_pages_text_is_cut_in_the_grid(self):
        admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(admin)
        long_text = ' '.join(['salmon'] * 200)
        self.make(content=make_pdf(long_text))
        overview = self.client.get(reverse('core:database'))
        for table in ('documents', 'document_pages', 'document_species', 'knowledge_entries',
                      'knowledge_entry_species'):
            self.assertContains(overview, f'>{table}</a>')
        grid = self.client.get(reverse('core:database_table', args=['document_pages']))
        self.assertEqual(grid.status_code, 200)
        cells = [cell for row in grid.context['grid'].rows for cell in row.cells if cell.kind == 'long']
        self.assertTrue(cells)
        self.assertTrue(all(len(cell.text) <= 81 for cell in cells))
