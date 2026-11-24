"""The Team list in the new look (core.crud.ListView behind ?ui=next, core/listprops.py, island `list-page`): the same view
reads the same rows, so the island's props say everything the classic page says (core.pagesays) in three languages and
under both mounts (Company › HR and Production › Team); the search and the filters are the address's, read by the server;
a row opens the record's own page, never a dialog; the pager keeps the search and the filters."""
import json
import re
from pathlib import Path
from unittest import mock

from django.test import override_settings
from django.urls import reverse

from core import listprops
from core.pagesays import unsaid

from ..resources.employee import EmployeeResource
from .helpers_people import PeopleTestCase, employee

MANIFEST = str(Path(__file__).resolve().parents[2] / 'core' / 'testdata' / 'islands-company-manifest.json')


def props_of(html):
    found = re.search(r'<script id="island-list-page-1" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(found.group(1)) if found else None


@override_settings(ISLANDS_MANIFEST=MANIFEST)
class TeamListNextTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.left = employee('E-9', 'Delta', 'Dag', left_on='2026-01-31')
        self.client.force_login(self.hr)

    def pages(self, url, **query):
        old = self.client.get(url, {**query, 'ui': 'classic'}).content.decode()
        new = self.client.get(url, {**query, 'ui': 'next'}).content.decode()
        return old, new, props_of(new)

    def test_the_new_list_says_everything_the_classic_list_says_in_three_languages_and_both_mounts(self):
        for name in ('hr:employee_list', 'hr:production_employee_list'):
            for language in ('en', 'nb', 'tr'):
                with self.subTest(page=name, language=language):
                    self.client.cookies['django_language'] = language
                    old, new, props = self.pages(reverse(name))
                    self.assertIsNotNone(props)
                    self.assertNotIn('class="data-table"', new)
                    self.assertEqual(unsaid(old, props, new_html=new), [])

    def test_a_row_opens_the_records_own_page_under_its_mount(self):
        _old, _new, props = self.pages(reverse('hr:production_employee_list'))
        rows = {row['cells']['employee']['text']: row for row in props['table']['rows']}
        ann = rows['Ann Alfa']
        self.assertEqual(ann['cells']['employee']['href'], reverse('hr:production_employee_edit', args=[self.in_a.pk]))
        self.assertEqual([action['href'] for action in ann['actions']],
                         [reverse('hr:production_employee_detail', args=[self.in_a.pk]),
                          reverse('hr:production_employee_edit', args=[self.in_a.pk])])
        self.assertEqual(props['toolbar']['add']['href'], reverse('hr:production_employee_create'))
        self.assertEqual(rows['Dag Delta']['cells']['status']['chip']['kind'], 'neutral')
        self.assertEqual(rows['Dag Delta']['cells']['department']['chip']['kind'], 'warning')

    def test_the_search_and_the_filters_are_the_addresss_read_by_the_server(self):
        old, new, props = self.pages(reverse('hr:employee_list'), q='Alfa', status='current', tab='x')
        self.assertEqual([row['cells']['employee']['text'] for row in props['table']['rows']], ['Ann Alfa'])
        self.assertEqual(props['toolbar']['search']['value'], 'Alfa')
        filters = {each['name']: each for each in props['toolbar']['filters']}
        self.assertEqual(filters['status']['value'], 'current')
        self.assertEqual(props['toolbar']['keep'], [{'name': 'tab', 'value': 'x'}])
        self.assertEqual(unsaid(old, props, new_html=new), [])
        old, new, props = self.pages(reverse('hr:employee_list'), q='nobody here')
        self.assertEqual(props['table']['rows'], [])
        self.assertEqual(props['empty']['title'], 'No employees match “nobody here”')
        self.assertEqual(props['empty']['link']['href'], reverse('hr:employee_list'))
        self.assertEqual(unsaid(old, props, new_html=new), [])

    def test_the_pager_keeps_the_search_and_the_filters(self):
        with mock.patch.object(EmployeeResource, 'page_size', 1):
            old, new, props = self.pages(reverse('hr:employee_list'), status='current', page='2')
        pager = props['pager']
        self.assertEqual(pager['previous']['href'], '?status=current&ui=next&page=1')
        self.assertEqual(pager['next']['href'], '?status=current&ui=next&page=3')
        self.assertEqual(unsaid(old.replace('ui=classic', 'ui=next'), props, new_html=new), [])

    def test_a_tab_without_its_new_list_keeps_the_classic_list(self):
        from django.contrib.auth import get_user_model

        from alarms.resources import ParameterDeadbandResource
        self.assertIsNone(ParameterDeadbandResource.list_rows)
        self.client.force_login(get_user_model().objects.create_superuser('lister', 'lister@example.com', 'x'))
        page = self.client.get(reverse('alarms:parameterdeadband_list'), {'ui': 'next'}).content.decode()
        self.assertIsNone(props_of(page))
        self.assertIn('class="data-table"', page)


class ListPropsTests(PeopleTestCase):
    def test_an_icon_or_a_tone_the_island_cannot_draw_is_refused_on_the_server(self):
        with self.assertRaises(ValueError):
            listprops.link('/x/', 'Go', 'no-such-icon')
        with self.assertRaises(ValueError):
            listprops.chip('purple', 'Odd')
        with self.assertRaises(ValueError):
            listprops.notice('n', 'loud', 'Odd')
        self.assertEqual(listprops.cell('Ann', sub=['', None, 'E-1'])['sub'], ['E-1'])
