"""The organisation chart drawn as a family tree (hr.read.org_tree, templates/hr/orgchart.html, static/css/hr.css): who is in
each box, the boxes' nesting in the page, and the stylesheet that draws the connectors, keeps a wide tree in its own frame,
falls back to a vertical tree on a phone and keeps the tree on paper."""
import re
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.urls import reverse

from .. import read
from .helpers import user
from .helpers_people import employee, place
from .test_overview_chart import OverviewTestCase, walk

HR_CSS = Path(settings.BASE_DIR) / 'static' / 'css' / 'hr.css'


def box(tree, label):
    return next(node for node in walk(tree) if node.label == label)


class PeopleInTheBoxesTests(OverviewTestCase):
    """A department's box can open to its people: those placed in it today whom the viewer may reach, and only for a viewer
    who may read people at all (hr.view_employee). The manager's title is their placement's."""

    def test_a_department_has_its_people_with_their_titles(self):
        tree = read.org_tree(self.hr, read.PRODUCTION)
        self.assertEqual([(p.name, p.title) for p in box(tree, 'Hatchery A').people], [('Ann Alfa', 'Technician')])
        self.assertEqual([(p.name, p.title) for p in box(tree, 'Nursery B').people], [('Bob Bravo', 'Feeder')])
        self.assertEqual(box(tree, 'Bergen').people, [])
        office = read.org_tree(self.hr, read.OFFICE)
        self.assertEqual([p.name for p in box(office, 'Finance').people], ['Cy Charlie'])

    def test_the_people_are_the_count_and_sorted_by_name(self):
        place(employee('E-20', 'Aaberg', 'Zed'), self.dept_a, title='Feeder')
        node = box(read.org_tree(self.hr, read.PRODUCTION), 'Hatchery A')
        self.assertEqual([p.name for p in node.people], ['Zed Aaberg', 'Ann Alfa'])
        self.assertEqual(len(node.people), node.direct)

    def test_a_lead_sees_only_their_own_people(self):
        tree = read.org_tree(self.lead, read.PRODUCTION)
        self.assertEqual([p.name for p in box(tree, 'Hatchery A').people], ['Ann Alfa'])
        self.assertEqual(box(tree, 'Nursery B').people, [])

    def test_a_reader_of_departments_only_sees_no_person(self):
        reader = user('office', 'view_officedepartment', 'all_employee', group='Office reader role')
        tree = read.org_tree(reader, read.OFFICE)
        self.assertEqual(box(tree, 'Finance').direct, 1)                   # counted as today
        self.assertEqual([node.people for node in walk(tree)], [[] for _node in walk(tree)])
        self.client.force_login(reader)
        page = self.client.get(reverse('hr:orgchart'))
        self.assertNotContains(page, 'Charlie')
        self.assertNotContains(page, 'Accountant')

    def test_the_managers_title_is_their_placement_and_hidden_from_a_reader_of_departments_only(self):
        place(employee('E-30', 'Boss', 'Ola', user=self.lead), self.dept_a, title='Hatchery manager')
        self.assertEqual(box(read.org_tree(self.hr, read.PRODUCTION), 'Hatchery A').manager_title, 'Hatchery manager')
        self.assertEqual(box(read.org_tree(self.hr, read.PRODUCTION), 'Nursery B').manager_title, '')
        reader = user('office', 'view_officedepartment', 'all_employee', group='Office reader role')
        from farm.models import ProductionDepartment
        from ..models import OfficeDepartment
        OfficeDepartment.objects.filter(pk=self.finance.pk).update(manager=self.lead)
        self.assertEqual(box(read.org_tree(self.hr, read.OFFICE), 'Finance').manager_title, 'Hatchery manager')
        self.assertEqual(box(read.org_tree(reader, read.OFFICE), 'Finance').manager_title, '')
        self.assertTrue(ProductionDepartment.objects.filter(manager=self.lead).exists())
