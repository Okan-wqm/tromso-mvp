"""The production panel's pages in the new look (?ui=next), on the test world (core/test_world.py), its clock pinned: every
page says all its classic page says (core.pagesays) in three languages, nothing of it opens the classic dialog, and its
rows are the classic page's rows (the same view reads them: a row the classic page hides, the new one hides too).

Recurring tasks, Questions for the authority and Experiments are drawn by the list-page island (core/listprops.py); Tasks
(with its drawer), Regulatory reports, Storage and Messages by the server from the classic page's own context."""
import json
import re
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from core.pagesays import unsaid

MANIFEST = str(Path(__file__).resolve().parent / 'testdata' / 'islands-company-manifest.json')
LANGUAGES = ('en', 'nb', 'tr')

# The list pages the list-page island draws: {name: (route, query)}.
LISTS = {
    'recurring-tasks': ('tasks:taskseries_list', {}),
    'recurring-tasks-paused': ('tasks:taskseries_list', {'state': 'paused'}),
    'questions': ('reports:openquestion_list', {}),
    'questions-open': ('reports:openquestion_list', {'status': 'open', 'q': 'Test'}),
    'experiments': ('experiments:experiment_list', {}),
    'experiments-mine': ('experiments:experiment_list', {'view': 'mine'}),
    'experiments-templates': ('experiments:experiment_list', {'view': 'templates'}),
}


def props_of(html):
    found = re.search(r'<script id="island-list-page-1" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(found.group(1)) if found else None


def main_of(html):
    return html[html.index('<main'):html.index('</main>')]


def row_titles(html):
    """The addresses of the classic list's row titles (class row-title)."""
    return re.findall(r'<a class="row-title" href="([^"]+)"', main_of(html))


@override_settings(ISLANDS_MANIFEST=MANIFEST, ALLOWED_HOSTS=['localhost', 'testserver'])
class WorldTestCase(TestCase):
    """The test world once for the class, the clock pinned, the test admin signed in."""

    @classmethod
    def setUpTestData(cls):
        from core.test_world import MOMENT, world
        with mock.patch('django.utils.timezone.now', return_value=MOMENT):
            cls.admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
            world(cls.admin)

    def setUp(self):
        from core.test_world import MOMENT
        clock = mock.patch('django.utils.timezone.now', return_value=MOMENT)
        clock.start()
        self.addCleanup(clock.stop)
        self.client.force_login(self.admin)

    def pages(self, address, query=None, language='en'):
        """The classic page and the new one at `address` (a route name or an address) with `query`, in `language`."""
        address = address if address.startswith('/') else reverse(address)
        self.client.cookies['django_language'] = language
        old = self.client.get(address, {**(query or {}), 'ui': 'classic'})
        new = self.client.get(address, {**(query or {}), 'ui': 'next'})
        self.assertEqual((old.status_code, new.status_code), (200, 200))
        return old.content.decode(), new.content.decode()

    def assertDrawnByTheServer(self, old, new):
        """A server-drawn page: the design system's plates, no classic table, all the classic page says, no style
        attribute (the policy refuses it) and no link to the classic dialog."""
        self.assertIn('class="ui-plates"', new)
        self.assertNotIn('class="data-table', new)
        self.assertEqual(unsaid(old, {}, new_html=new), [])
        main = main_of(new)
        self.assertIsNone(re.search(r'\sstyle=', main), 'no style attribute: the policy refuses it')
        self.assertIsNone(re.search(r'\sdata-modal[\s>=]', main), 'no link opens the classic dialog')


class ListPagesTests(WorldTestCase):
    def test_every_list_says_everything_its_classic_page_says_in_three_languages(self):
        for name, (route, query) in LISTS.items():
            for language in LANGUAGES:
                with self.subTest(page=name, language=language):
                    old, new = self.pages(route, query, language)
                    props = props_of(new)
                    self.assertIsNotNone(props)
                    self.assertTrue(props['table']['rows'], 'the test world has rows on every list')
                    self.assertEqual(unsaid(old, props, new_html=new), [])
                    self.assertIsNone(re.search(r'\sdata-modal[\s>=]', main_of(new)), 'no link opens the classic dialog')

    def test_the_recurring_tasks_link_to_the_tasks_views(self):
        props = props_of(self.pages('tasks:taskseries_list')[1])
        base = reverse('tasks:task_list')
        self.assertEqual([(tab['href'], tab['current']) for tab in props['tabs']['tabs']],
                         [(base, False), (f'{base}?view=open', False), (f'{base}?view=completed', False),
                          (reverse('tasks:taskseries_list'), True)])
        rows = {row['cells']['title']['text']: row for row in props['table']['rows']}
        self.assertEqual(rows['Test filter wash']['cells']['status']['chip'], {'kind': 'neutral', 'text': 'Paused'})
        self.assertEqual(rows['Test filter wash']['cells']['assignees']['chip']['kind'], 'warning')
        self.assertEqual(rows['Test filter wash']['cells']['next']['text'], '—')
        self.assertTrue(rows['Test oxygen round']['cells']['title']['href'].endswith('/edit/'))

    def test_an_experiment_list_shows_the_rows_of_the_classic_list_and_nothing_more(self):
        reader = get_user_model().objects.create_user('test.reader', 'test.reader@example.com', 'x')
        group = Group.objects.create(name='Test experiments reader')
        group.permissions.set(Permission.objects.filter(content_type__app_label='experiments',
                                                        codename='view_experiment'))
        reader.groups.add(group)
        for user in (self.admin, reader):
            self.client.force_login(user)
            for view in ('', 'mine', 'templates'):
                with self.subTest(user=user.username, view=view):
                    old, new = self.pages('experiments:experiment_list', {'view': view} if view else {})
                    props = props_of(new)
                    shown = [row['cells']['experiment']['href'] for row in props['table']['rows']]
                    self.assertEqual(shown, row_titles(old))
                    self.assertEqual(unsaid(old, props, new_html=new), [])
                    if user == reader:      # Read only: no edit, no delete, nothing to add
                        self.assertFalse(any(row['actions'] for row in props['table']['rows']))
                        self.assertIsNone(props['toolbar']['add'])
        # the reader is in no experiment's team: Mine is empty, as on the classic page
        self.client.force_login(reader)
        self.assertEqual(props_of(self.pages('experiments:experiment_list', {'view': 'mine'})[1])['table']['rows'], [])

    def test_an_experiment_says_where_it_is_in_its_days_as_its_read_page(self):
        props = props_of(self.pages('experiments:experiment_list')[1])
        rows = {row['cells']['experiment']['text']: row for row in props['table']['rows']}
        self.assertEqual(rows['Test diet trial']['cells']['status']['sub'], ['Day 0 is in 10 days'])
        self.assertEqual(rows['Test light trial']['cells']['status']['sub'], [])
        self.assertEqual([action['icon'] for action in rows['Test diet trial']['actions']], ['pencil', 'trash'])

    def test_a_question_says_its_status_asked_and_answer(self):
        props = props_of(self.pages('reports:openquestion_list')[1])
        rows = {row['cells']['number']['text']: row for row in props['table']['rows']}
        self.assertEqual(rows['TQ1']['cells']['status']['chip']['kind'], 'accent')
        self.assertEqual((rows['TQ1']['cells']['asked']['text'], rows['TQ1']['cells']['answer']['text']), ('—', '—'))
        self.assertEqual(rows['TQ2']['cells']['asked']['sub'], ['Test Person'])
        self.assertEqual(rows['TQ2']['cells']['answer']['text'], 'Test answer.')


class TasksPageTests(WorldTestCase):
    """Operations › Tasks: every view, a filter with no match and the open drawer say all the classic page says; the
    drawer's actions are the classic page's forms and addresses."""

    def test_every_view_and_the_drawer_say_all_the_classic_page_says_in_three_languages(self):
        from tasks.models import Task
        late, done = Task.objects.get(title='Test net check'), Task.objects.get(title='Test sample round')
        views = {'today': {}, 'open': {'view': 'open'}, 'completed': {'view': 'completed'},
                 'no match': {'view': 'open', 'q': 'nothing like this'}, 'priority': {'priority': 'high'},
                 'drawer': {'task': str(late.pk)}, 'drawer done': {'view': 'completed', 'task': str(done.pk)}}
        for name, query in views.items():
            for language in LANGUAGES:
                with self.subTest(view=name, language=language):
                    self.assertDrawnByTheServer(*self.pages('tasks:task_list', query, language))

    def test_the_drawer_posts_to_the_tasks_own_addresses_and_comes_back(self):
        from tasks.models import Task
        late = Task.objects.get(title='Test net check')
        new = self.pages('tasks:task_list', {'task': str(late.pk)})[1]
        self.assertIn('aria-labelledby="drawer-title"', new)
        self.assertIn(f'action="{reverse("tasks:task_start", args=[late.pk])}?next=', new)
        line = late.checklist.first()
        self.assertIn(f'action="{reverse("tasks:task_tick", args=[late.pk, line.pk])}"', new)
        self.assertIn(f'href="{reverse("tasks:task_complete", args=[late.pk])}?next=', new)
        # the overdue task is marked on its row (warning) and counted above the table
        self.assertRegex(new, r'<tr data-status="warning"[^>]*>\s*<th scope="row"><span class="ui-row-status">')
        self.assertIn('1 overdue task', new)


class ReportsPageTests(WorldTestCase):
    """Regulatory reports: all reports and every one of the eleven kinds say all the classic page says."""

    def test_all_reports_and_every_kind_say_all_the_classic_page_says_in_three_languages(self):
        from reports.models import Report
        self.assertEqual(len(Report.Kind.values), 11)
        queries = [{}, {'status': 'draft'}, {'q': 'nothing like this'}, *({'kind': kind} for kind in Report.Kind.values)]
        for query in queries:
            for language in LANGUAGES:
                with self.subTest(query=query, language=language):
                    self.assertDrawnByTheServer(*self.pages('reports:report_list', query, language))

    def test_the_kinds_strip_has_every_kind_and_the_list_its_reports(self):
        from reports.models import Report
        new = self.pages('reports:report_list')[1]
        for kind in Report.Kind.values:
            self.assertIn(f'href="{reverse("reports:report_list")}?kind={kind}"', new)
        self.assertEqual(new.count('<tr'), Report.objects.count() + 1)      # the head row and one a report


class StoragePageTests(WorldTestCase):
    """Operations › Storage: its four tabs, their filters and the feed given say all the classic page says; the actions
    are the classic addresses, opened as pages."""

    def test_every_tab_says_all_the_classic_page_says_in_three_languages(self):
        queries = [{}, {'tab': 'stock'}, {'tab': 'stock', 'empty': '1'}, {'tab': 'stock', 'item': 'not-one'},
                   {'tab': 'movements'}, {'tab': 'movements', 'voided': '1'}, {'tab': 'movements', 'kind': 'feeding'},
                   {'tab': 'movements', 'kind': 'issue'}, {'tab': 'counts'}]
        for query in queries:
            for language in LANGUAGES:
                with self.subTest(query=query, language=language):
                    self.assertDrawnByTheServer(*self.pages('inventory:storage', query, language))

    def test_the_overview_warns_of_low_stock_and_the_expiring_lot(self):
        new = self.pages('inventory:storage')[1]
        self.assertIn('id="low-title"', new)
        self.assertIn('id="expiring-title"', new)
        self.assertIn(reverse('inventory:receive'), new)


class MessagesPageTests(WorldTestCase):
    """Messages: the inbox and an open conversation, direct and channel, say all the classic page says; the polled
    fragments are the classic ones, and a message is deleted on its own page."""

    def test_the_inbox_and_each_conversation_say_all_the_classic_page_says_in_three_languages(self):
        from messaging.models import Conversation
        addresses = [reverse('messaging:inbox'), *(reverse('messaging:conversation', args=[conversation.pk])
                                                   for conversation in Conversation.objects.order_by('kind'))]
        for address in addresses:
            for language in LANGUAGES:
                with self.subTest(address=address, language=language):
                    self.assertDrawnByTheServer(*self.pages(address, language=language))

    def test_the_poll_draws_the_same_fragments_in_both_looks(self):
        from messaging.models import Conversation
        direct = Conversation.objects.get(kind=Conversation.Kind.DIRECT)
        new = self.pages(reverse('messaging:conversation', args=[direct.pk]))[1]
        self.assertIn(f'data-poll="{reverse("messaging:poll", args=[direct.pk])}?after=', new)
        self.assertIn('class="chat-messages"', new)
        self.assertIn(f'data-poll="{reverse("messaging:inbox_list")}?open={direct.pk}"', new)
        listed = self.client.get(reverse('messaging:inbox_list'), {'open': direct.pk}).content.decode()
        self.assertNotIn('data-modal', listed)
        self.assertIn('href="/messages/', new)
