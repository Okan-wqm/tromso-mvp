"""The library's and the entries' full-text search (knowledge.search), on real PDFs and through the list pages."""
from django.urls import reverse

from ..models import Document, KnowledgeEntry
from ..search import highlight, parse
from .helpers import KnowledgeTestCase, make_pdf, upload


class SearchTestCase(KnowledgeTestCase):
    def document(self, title, pdf=None, **fields):
        document = Document(title=title, **fields)
        if pdf is not None:
            document.file = upload(pdf)
        document.save()
        return document

    def found(self, query, **filters):
        response = self.client.get(reverse('knowledge:document_list'), {'q': query, **filters})
        self.assertEqual(response.status_code, 200)
        return list(response.context['objects'])

    def found_entries(self, query):
        return list(self.client.get(reverse('knowledge:knowledgeentry_list'), {'q': query}).context['objects'])


class DocumentSearchTests(SearchTestCase):
    def test_the_text_of_an_uploaded_pdf_is_found_with_its_page_and_passage(self):
        document = self.document('Kidney health of smolt', make_pdf('Methods and tanks', 'Nephrocalcinosis was seen '
                                                                    'above 15 mg/L of free CO2.'))
        self.document('Feeding tables')
        response = self.client.get(reverse('knowledge:document_list'), {'q': 'nephrocalcinosis'})
        self.assertEqual(list(response.context['objects']), [document])
        hit = response.context['objects'][0]
        self.assertEqual((hit.hit_page, hit.hit_label), (2, ''))
        self.assertIn('<mark>Nephrocalcinosis</mark>', str(highlight(hit.hit_text)))
        self.assertContains(response, '<span class="hit-page">p. 2</span>', html=True)
        detail = self.client.get(reverse('knowledge:document_detail', args=[document.pk]), {'q': 'nephrocalcinosis'})
        self.assertContains(detail, '<mark>Nephrocalcinosis</mark>')
        self.assertContains(detail, f"{reverse('knowledge:document_text', args=[document.pk])}?page=1#page-2")

    def test_a_title_hit_ranks_above_a_hit_in_the_text(self):
        in_text = self.document('Recirculation basics', make_pdf('Salinity is kept at 12 g/kg.'))
        in_abstract = self.document('Growth of cod', abstract='Salinity had no effect on growth.')
        in_title = self.document('Salinity and smolt quality')
        self.assertEqual(self.found('salinity'), [in_title, in_abstract, in_text])

    def test_a_word_is_found_in_any_of_the_three_languages(self):
        english = self.document('Disease in sea cages')
        norwegian = self.document('Rapport', abstract='Fiskehelse og velferd i oppdrett.', language='no')
        turkish = self.document('Rapor', abstract='Balıklarda hastalık ve refah.', language='tr')
        self.assertEqual(self.found('diseases'), [english])
        self.assertEqual(self.found('fisken'), [norwegian])
        self.assertEqual(self.found('balıklar'), [turkish])
        self.assertEqual(self.found('VELFERD'), [norwegian])

    def test_every_word_must_be_in_the_document_but_may_be_in_different_parts_of_it(self):
        document = self.document('Kidney health', make_pdf('Nephrocalcinosis in smolt'), authors='Olsen, Bjørn')
        self.assertEqual(self.found('Olsen nephrocalcinosis'), [document])
        self.assertEqual(self.found('Olsen zebrafish'), [])

    def test_short_stems_and_numbers_match_whole(self):
        ph = self.document('pH and alkalinity')
        self.document('Phosphorus in feed')
        fifteen = self.document('CO2 above 15 mg/L')
        self.document('CO2 above 150 mg/L')
        self.assertEqual(self.found('pH'), [ph])
        self.assertEqual(self.found('15'), [fifteen])

    def test_what_is_typed_is_never_read_as_query_syntax(self):
        document = self.document("Salmon's welfare & (oxygen)")
        for query in ("salmon's", "salmon & | ! ( ) :* \\ '", 'oxygen)', "welfare:*A"):
            self.assertIn(document, self.found(query), query)
        self.assertIsNone(parse('& | ! ( )'))
        response = self.client.get(reverse('knowledge:document_list'), {'q': '&|!'})
        self.assertEqual(list(response.context['objects']), [])
        self.assertContains(response, 'No documents match')

    def test_a_deleted_document_is_not_found_nor_its_pages(self):
        document = self.document('Lumpfish welfare', make_pdf('Lumpfish need shelter'))
        document.soft_delete(self.user)
        self.assertEqual(self.found('lumpfish'), [])
        self.assertEqual(self.found('shelter'), [])

    def test_search_and_filters_combine(self):
        health = self.document('Gill health', topics=['health'], year=2020)
        self.document('Gill design of feeders', topics=['equipment'], year=2020)
        self.document('Smolt quality', year=2021)
        self.assertEqual(self.found('gill', topic='health'), [health])
        self.assertEqual(self.found('gill', year='2021'), [])
        self.assertEqual(len(self.found('gill', year='2020')), 2)

    def test_a_passage_is_escaped_with_only_the_found_words_marked(self):
        document = self.document('Odd text', make_pdf('<script>alert(1)</script> oxygen'))
        response = self.client.get(reverse('knowledge:document_list'), {'q': 'oxygen'})
        self.assertNotContains(response, '<script>alert')
        self.assertContains(response, '<mark>oxygen</mark>')
        self.assertEqual(str(highlight('a <b>\x02x & y\x03')), 'a &lt;b&gt;<mark>x &amp; y</mark>')
        self.assertEqual(highlight(None), '')
        self.assertEqual(self.found('oxygen'), [document])


class EntrySearchTests(SearchTestCase):
    def test_entries_are_found_by_their_words_and_by_those_of_the_document_they_cite(self):
        olsen = self.document('Kidney health of smolt', authors='Olsen, Bjørn')
        cited = KnowledgeEntry.objects.create(statement='CO2 above 15 mg/L causes nephrocalcinosis.',
                                              topics=['health'], source_kind='document', document=olsen)
        observed = KnowledgeEntry.objects.create(statement='Feed orders arrive three days after they are placed.',
                                                 topics=['procurement'], source_kind='expert',
                                                 expert='Kari Nordmann')
        self.assertEqual(self.found_entries('nephrocalcinosis'), [cited])
        self.assertEqual(self.found_entries('Olsen'), [cited])
        self.assertEqual(self.found_entries('ordered'), [observed])
        self.assertEqual(self.found_entries('Nordmann'), [observed])
        self.assertEqual(self.found_entries('placed Nordmann'), [observed])
        self.assertEqual(self.found_entries('zebrafish'), [])

    def test_the_statement_ranks_above_the_quote(self):
        in_quote = KnowledgeEntry.objects.create(statement='Smolt need clean water.', quote='Turbidity above 10 NTU.',
                                                 topics=['water_quality'], source_kind='external', citation='A')
        in_statement = KnowledgeEntry.objects.create(statement='Turbidity above 10 NTU stresses smolt.',
                                                     topics=['water_quality'], source_kind='external', citation='B')
        self.assertEqual(self.found_entries('turbidity'), [in_statement, in_quote])
