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
        place(employee('E-30', '', '', user=self.lead), self.dept_a, title='Hatchery manager')
        self.assertEqual(box(read.org_tree(self.hr, read.PRODUCTION), 'Hatchery A').manager_title, 'Hatchery manager')
        self.assertEqual(box(read.org_tree(self.hr, read.PRODUCTION), 'Nursery B').manager_title, '')
        reader = user('office', 'view_officedepartment', 'all_employee', group='Office reader role')
        from farm.models import ProductionDepartment
        from ..models import OfficeDepartment
        OfficeDepartment.objects.filter(pk=self.finance.pk).update(manager=self.lead)
        self.assertEqual(box(read.org_tree(self.hr, read.OFFICE), 'Finance').manager_title, 'Hatchery manager')
        self.assertEqual(box(read.org_tree(reader, read.OFFICE), 'Finance').manager_title, '')
        self.assertTrue(ProductionDepartment.objects.filter(manager=self.lead).exists())


class Outline(HTMLParser):
    """The chart's boxes as nested (name, [children]) read from the page's lists: an li.org-node is a box, its .org-name its
    name, a box inside another box's list its child. People's cards (li.org-person) are collected per box."""

    def __init__(self):
        super().__init__()
        self.stack, self.roots, self.tags, self.reading, self.person = [], [], [], None, None
        self.frames = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get('class') or '').split()
        self.tags.append((tag, classes))
        if 'org-frame' in classes:
            self.frames.append(attrs)
        if tag == 'li' and 'org-node' in classes:
            node = {'name': '', 'children': [], 'people': [], 'classes': classes}
            (self.stack[-1]['children'] if self.stack else self.roots).append(node)
            self.stack.append(node)
        elif tag == 'li' and 'org-person' in classes:
            self.person = ''
        if 'org-name' in classes:
            self.reading = ''

    def handle_endtag(self, tag):
        opened, classes = self.tags.pop()
        if 'org-name' in classes:
            self.stack[-1]['name'] = ' '.join(self.reading.split())
            self.reading = None
        if opened == 'li' and 'org-person' in classes:
            self.stack[-1]['people'].append(' '.join(self.person.split()))
            self.person = None
        elif opened == 'li' and 'org-node' in classes:
            self.stack.pop()

    def handle_data(self, data):
        if self.reading is not None:
            self.reading += data
        if self.person is not None:
            self.person += data


def outline(response):
    parser = Outline()
    parser.feed(response.content.decode())
    return parser


def shape(nodes):
    return [(node['name'], shape(node['children'])) for node in nodes]


class TreePageTests(OverviewTestCase):
    """The page is a list of lists: a child box is an item of the list inside its parent's item, so the tree reads, prints and
    is announced without script."""

    def test_the_company_page_nests_the_production_box_under_the_one_top_department(self):
        self.client.force_login(self.hr)
        page = outline(self.client.get(reverse('hr:orgchart')))
        self.assertEqual(shape(page.roots), [('Administration', [('Finance', []), ('Production', [])])])

    def test_the_production_page_nests_site_departments_and_their_people(self):
        self.client.force_login(self.hr)
        page = outline(self.client.get(reverse('hr:production_orgchart')))
        self.assertEqual(shape(page.roots), [('Bergen', [('Hatchery A', []), ('Nursery B', [])])])
        hatchery = page.roots[0]['children'][0]
        self.assertEqual(len(hatchery['people']), 1)
        self.assertIn('Ann Alfa', hatchery['people'][0])
        self.assertIn('Technician', hatchery['people'][0])

    def test_each_box_says_its_kind_manager_and_count(self):
        self.client.force_login(self.hr)
        response = self.client.get(reverse('hr:production_orgchart'))
        html = response.content.decode()
        hatchery = re.search(r'<li class="org-node org-production[^"]*">.*?Hatchery A.*?</div>', html, re.S).group(0)
        self.assertIn('Production', hatchery)
        self.assertIn('boss', hatchery)                                      # the manager (no full name: the username)
        self.assertIn('1 person', hatchery)

    def test_a_lead_sees_no_one_outside_their_team(self):
        self.client.force_login(self.lead)
        page = outline(self.client.get(reverse('hr:production_orgchart')))
        people = [person for node in page.roots[0]['children'] for person in node['people']]
        self.assertEqual(len(people), 1)
        self.assertIn('Ann Alfa', people[0])

    def test_the_tree_scrolls_in_its_own_labelled_frame_with_a_cue(self):
        self.client.force_login(self.hr)
        response = self.client.get(reverse('hr:orgchart'))
        frame, = outline(response).frames
        self.assertEqual((frame.get('role'), frame.get('tabindex')), ('region', '0'))
        self.assertTrue(frame.get('aria-labelledby') or frame.get('aria-label'))
        self.assertContains(response, 'class="org-scroll-cue')

    def test_the_people_open_with_a_native_disclosure(self):
        self.client.force_login(self.hr)
        html = self.client.get(reverse('hr:production_orgchart')).content.decode()
        self.assertRegex(html, r'<details class="org-people">\s*<summary>')
        self.assertNotIn('<script', html.split('class="org-frame')[1].split('</main>')[0])


def blocks(css):
    """[(the @media it sits in or '', selector, body)]: the rules of a stylesheet, comments dropped."""
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    found, heads, text = [], [], ''
    for char in css:
        if char == '{':
            heads.append(' '.join(text.split()))
            text = ''
        elif char == '}':
            head = heads.pop()
            if not head.startswith('@media'):
                found.append((' '.join(h for h in heads if h.startswith('@media')), head, ' '.join(text.split())))
            text = ''
        else:
            text += char
    return found


def rules(media, selector_part):
    return ' '.join(body for at, selector, body in blocks(HR_CSS.read_text(encoding='utf-8'))
                    if media in at and selector_part in selector)


class TreeStylesheetTests(OverviewTestCase):
    """What the stylesheet must keep: no library and no script draws the tree, so the rules are the drawing."""

    def test_connectors_are_drawn_with_pseudo_elements_from_the_tokens(self):
        css = HR_CSS.read_text(encoding='utf-8')
        self.assertRegex(css, r'\.org-tree li::before')
        self.assertRegex(css, r'\.org-tree li::after')
        self.assertRegex(css, r'\.org-tree ul::before')
        self.assertRegex(rules('', '.org-tree li::before'), r'border-top: 1px solid var\(--(muted|line|line-hair|line-control)\)')

    def test_a_wide_tree_scrolls_in_its_frame_and_never_the_page(self):
        frame = rules('', '.org-frame')
        self.assertRegex(frame, r'overflow-x:\s*auto')
        self.assertRegex(frame, r'max-width:\s*100%')
        self.assertRegex(rules('', '.org-tree'), r'width:\s*max-content')

    def test_a_phone_reads_a_vertical_tree(self):
        phone = rules('max-width: 767px', '.org-tree')
        self.assertRegex(phone, r'display:\s*block')
        self.assertRegex(phone, r'width:\s*auto')

    def test_paper_keeps_the_tree_landscape_and_drops_the_menu_and_the_frame(self):
        css = HR_CSS.read_text(encoding='utf-8')
        self.assertRegex(css, r'@page\s+org-chart\s*\{[^}]*size:\s*A4 landscape', )
        self.assertRegex(rules('print', '.org-frame'), r'overflow:\s*visible')
        self.assertRegex(rules('print', '.rail'), r'display:\s*none')
        self.assertRegex(rules('print', '.org-scroll-cue'), r'display:\s*none')
