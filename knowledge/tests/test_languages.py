"""The knowledge pages in each language; the activity log stays English at rest."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

from core.audit import message
from core.models import AuditLog, Profile
from farm.tests.helpers import make_species

from ..models import Document, KnowledgeEntry
from .helpers import KnowledgeTestCase, document_data, make_pdf, upload

LANGUAGES = [code for code, _ in settings.LANGUAGES]


def setUpModule():
    call_command('compile_catalogs', verbosity=0)


class KnowledgePagesInEveryLanguageTests(KnowledgeTestCase):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        salmon = make_species()
        self.document = Document(title='Kidney health', authors='Olsen, Bjørn\nHansen, Kari\nBerg, Ola',
                                 topics=['health'], language='no')
        self.document.file = upload(make_pdf('Nephrocalcinosis', None))
        self.document.save()
        self.document.species.add(salmon)
        self.entry = KnowledgeEntry.objects.create(statement='CO2 above 15 mg/L harms smolt.', topics=['health'],
                                                   source_kind='document', document=self.document, pages='1')
        self.entry.species.add(salmon)
        self.entry.review(self.admin)
        self.entry.save()

    def urls(self):
        document, entry = self.document.pk, self.entry.pk
        return [
            reverse('knowledge:document_list'), f"{reverse('knowledge:document_list')}?q=nephrocalcinosis",
            reverse('knowledge:document_create'), reverse('knowledge:document_edit', args=[document]),
            reverse('knowledge:document_delete', args=[document]), reverse('knowledge:document_detail', args=[document]),
            f"{reverse('knowledge:document_detail', args=[document])}?q=nephrocalcinosis",
            reverse('knowledge:document_text', args=[document]),
            reverse('knowledge:knowledgeentry_list'), f"{reverse('knowledge:knowledgeentry_list')}?q=smolt",
            reverse('knowledge:knowledgeentry_create'), reverse('knowledge:knowledgeentry_edit', args=[entry]),
            reverse('knowledge:knowledgeentry_delete', args=[entry]),
            reverse('knowledge:knowledgeentry_detail', args=[entry]),
            reverse('core:database_table', args=['documents']), reverse('core:database_table', args=['knowledge_entries']),
        ]

    def test_every_page_and_dialog_renders_in_each_language(self):
        for language in LANGUAGES:
            Profile.objects.update_or_create(user=self.admin, defaults={'language': language})
            self.client.force_login(self.admin)
            for url in self.urls():
                for headers in ({}, {'X-Modal': '1'}):
                    with self.subTest(language=language, url=url, modal=bool(headers)):
                        response = self.client.get(url, headers=headers)
                        self.assertEqual(response.status_code, 200)
                        self.assertNotIn('%(', response.content.decode())
                        self.assertEqual(response['Content-Language'], language)

    def test_each_language_shows_its_own_words(self):
        expected = {
            'en': ('Knowledge', 'Library', 'Knowledge entries', 'Olsen et al.', 'p. 1'),
            'tr': ('Bilgi', 'Kütüphane', 'Bilgi kayıtları', 'Olsen vd.', 's. 1'),
            'nb': ('Kunnskap', 'Bibliotek', 'Kunnskapsoppføringer', 'Olsen mfl.', 's. 1'),
        }
        for language, (group, library, entries, cited, page) in expected.items():
            Profile.objects.update_or_create(user=self.admin, defaults={'language': language})
            self.client.force_login(self.admin)
            home = self.client.get(reverse('home'))
            for word in (group, library, entries):
                self.assertContains(home, word, msg_prefix=language)
            listing = self.client.get(reverse('knowledge:knowledgeentry_list'))
            self.assertContains(listing, cited, msg_prefix=language)
            self.assertContains(listing, page, msg_prefix=language)

    def test_the_log_is_english_whatever_the_language_of_the_change(self):
        Profile.objects.update_or_create(user=self.user, defaults={'language': 'tr'})
        self.client.post(reverse('knowledge:document_create'),
                         {**document_data(title='Velferd', topics=['welfare'], language='tr'),
                          'file': upload(make_pdf(None))})
        created = AuditLog.objects.get(entity_type='document', entity_id=str(Document.objects.get(title='Velferd').pk))
        self.assertEqual(created.changes['Topics'], [None, [message('Welfare')]])
        self.assertEqual(created.changes['Language'], [None, message('Turkish')])
        self.assertEqual(created.changes['Text'], [None, message('No text found')])
