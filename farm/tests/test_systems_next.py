"""Setup › Systems in the new look (?ui=next, core.crud.ListView with SystemResource.list_rows): the shared list page says
everything the classic list (templates/farm/system_list.html, unchanged) says, in three languages, on THE test world
(core/test_world.py, clock at MOMENT) and with a nested system without a production department (its "in …" line, its
warning chip and the notice with its "Show them" link); each row adds the way to its water history (System › Water) for
a person who may read the water, and nothing opens the classic dialog. The props are kept for the browser test
(frontend/test/prodrest.pages.ts)."""
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.island_props import keep, props_of
from core.pagesays import unsaid
from core.test_world import MOMENT, world
from core.testing import FrozenClock

from ..models import System

MANIFEST = str(Path(__file__).resolve().parents[2] / 'core' / 'testdata' / 'islands-prodrest-manifest.json')


@override_settings(ISLANDS_MANIFEST=MANIFEST)
class SystemsListNextTests(FrozenClock, TestCase):
    NOW = MOMENT

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
        world(cls.admin, Client())
        cls.loop = System.objects.get(code='TL1')

    def setUp(self):
        self.client.force_login(self.admin)

    def pages(self, language='en', **query):
        self.client.cookies['django_language'] = language
        url = reverse('farm:system_list')
        old = self.client.get(url, {**query, 'ui': 'classic'}).content.decode()
        new = self.client.get(url, {**query, 'ui': 'next'}).content.decode()
        return old, new

    def test_the_new_list_says_everything_the_classic_list_says_in_three_languages(self):
        from core.language import save_account_language
        for language in ('en', 'nb', 'tr'):
            save_account_language(self.admin, language)
            old, new = self.pages(language)
            props = props_of(new, 'list-page')
            self.assertTrue(props['table']['rows'])
            self.assertEqual(unsaid(old, props, new_html=new), [], language)
            main = new[new.index('<main'):new.index('</main>')]
            self.assertIsNone(re.search(r'\sdata-modal[\s>=]', main), 'nothing opens the classic dialog')
            if language == 'en':
                keep('production-systems-en', {'island': 'list-page', 'props': props})

    def test_a_nested_system_without_a_department_and_the_notice_that_shows_them(self):
        System.objects.create(name='Test Biofilter 1', code='TB1', site=self.loop.site, parent=self.loop)
        for query in ({}, {'production_department': 'none'}):
            old, new = self.pages('en', **query)
            props = props_of(new, 'list-page')
            self.assertEqual(unsaid(old, props, new_html=new), [], query)
        _old, new = self.pages('en')
        props = props_of(new, 'list-page')
        [notice] = props['notices']
        self.assertEqual(notice['text'], '1 system is not in any production department.')
        self.assertEqual(notice['link'], {'href': '?production_department=none', 'label': 'Show them'})
        row = next(each for each in props['table']['rows'] if each['cells']['system']['text'] == '↳ Test Biofilter 1')
        self.assertEqual(row['cells']['system']['sub'], ['TB1 · in Test Loop 1'])
        self.assertEqual(row['cells']['department']['chip'], {'kind': 'warning', 'text': 'No production department'})

    def test_each_row_leads_to_its_water_history_for_a_person_who_may_read_the_water(self):
        _old, new = self.pages('en')
        row = next(each for each in props_of(new, 'list-page')['table']['rows'] if each['key'] == str(self.loop.pk))
        water = reverse('farm:system_water', args=[self.loop.pk])
        self.assertIn(water, [action['href'] for action in row['actions']])
        reader = get_user_model().objects.create_user('test.reader', 'test.reader@example.com', 'x')
        reader.user_permissions.add(Permission.objects.get(content_type__app_label='farm', codename='view_system'))
        self.client.force_login(reader)
        _old, new = self.pages('en')
        row = next(each for each in props_of(new, 'list-page')['table']['rows'] if each['key'] == str(self.loop.pk))
        self.assertNotIn(water, [action['href'] for action in row['actions']], 'no water right, no water link')
