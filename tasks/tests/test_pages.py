"""Tasks through the pages, checked against the stored rows: create, read, edit and delete at every kind of place,
every field cleared on edit, what the Location, Batch and Assignees lists offer, the views and filters, the
drawer's actions with who may do them, overdue on the site's clock, the activity log, the delete plan of a place
and the menu, the role matrix and the database viewer."""
import uuid
from datetime import datetime, time, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from core import access, database, navigation, softdelete
from core.audit import english, private
from core.models import AuditLog, EntryKey, Profile
from core.widgets import NONE
from farm.tests.helpers import stock_fish

from .. import places, read, services
from ..models import PLACES, Status, Task, TaskChecklistItem, TaskNote
from . import TasksTestCase, form_data

LIST = reverse('tasks:task_list')
NEW = reverse('tasks:task_create')


def setUpModule():
    call_command('compile_catalogs', verbosity=0)    # the language test reads the built catalogs


def edit_url(task):
    return reverse('tasks:task_edit', args=[task.pk])


class CreateReadEditDeleteTests(TasksTestCase):
    def post_new(self, place, **fields):
        data = form_data(site=places.site_key(place), location=places.token(place),
                         due_date=self.today.isoformat(), assignees=[self.ali.pk], **fields)
        return self.client.post(NEW, data)

    def test_a_task_at_every_kind_of_place_is_created_read_edited_and_deleted(self):
        for place in (self.bergen, self.hall, self.ras, self.t1, self.pump, self.loose, self.t9):
            with self.subTest(place=places.token(place)):
                response = self.post_new(place, title=f'Job at {places.label(place)}')
                task = Task.objects.get(title=f'Job at {places.label(place)}')
                self.assertRedirects(response, edit_url(task), fetch_redirect_response=False)
                self.assertEqual(task.place, place)
                self.assertEqual(sum(bool(getattr(task, f'{name}_id')) for name in PLACES), 1)
                self.assertEqual(list(task.assignees.all()), [self.ali])
                self.assertEqual((task.status, task.created_by, task.due_date), (Status.OPEN, self.boss, self.today))
                listing = self.client.get(LIST)
                self.assertContains(listing, task.title)
                self.assertContains(self.client.get(f'{LIST}?task={task.pk}'), f'id="drawer-title">{task.title}<')
                # edit: another place, title and priority
                other = self.t2
                response = self.client.post(edit_url(task), form_data(
                    title='Moved job', site=places.site_key(other), location=places.token(other), priority='urgent',
                    due_date=self.day(1).isoformat(), assignees=[self.ali.pk, self.kari.pk], version=task.version))
                self.assertRedirects(response, LIST, fetch_redirect_response=False)
                task.refresh_from_db()
                self.assertEqual((task.title, task.place, task.priority, task.due_date, task.version),
                                 ('Moved job', other, 'urgent', self.day(1), 2))
                self.assertEqual(set(task.assignees.all()), {self.ali, self.kari})
                # delete: a soft delete, gone from the list, logged
                self.assertContains(self.client.get(reverse('tasks:task_delete', args=[task.pk])), 'Moved job')
                self.client.post(reverse('tasks:task_delete', args=[task.pk]))
                self.assertFalse(Task.objects.filter(pk=task.pk).exists())
                self.assertTrue(Task.all_objects.get(pk=task.pk).is_deleted)
                self.assertTrue(AuditLog.objects.filter(entity_id=str(task.pk), action='delete').exists())

    def test_every_optional_field_can_be_cleared_on_edit(self):
        batch = stock_fish(self.stocker, self.t1)
        task = self.make_task(description='Use the long brush', due_time=time(8, 0), batch=batch)
        response = self.client.post(edit_url(task), form_data(
            site=str(self.bergen.pk), location=places.token(self.t1), due_date=self.today.isoformat(),
            assignees=[self.ali.pk], version=task.version))
        self.assertEqual(response.status_code, 302)
        task.refresh_from_db()
        self.assertEqual((task.description, task.due_time, task.batch), ('', None, None))

    def test_what_is_stored_is_what_was_entered(self):
        batch = stock_fish(self.stocker, self.t1)
        self.post_new(self.t1, title='Weigh a sample', description='30 fish', category='health', priority='high',
                      due_time='14:30', batch=str(batch.pk))
        task = Task.objects.get(title='Weigh a sample')
        self.assertEqual((task.description, task.category, task.priority, task.due_time, task.batch),
                         ('30 fish', 'health', 'high', time(14, 30), batch))
        log = AuditLog.objects.get(entity_id=str(task.pk), action='create')
        self.assertEqual(log.changes['Location'], [None, 'T-01 · Unit T-01 (Unit)'])
        self.assertEqual(log.changes['Assignees'], [None, 'ali'])

    def test_the_required_fields_and_the_site_of_the_place(self):
        response = self.client.post(NEW, form_data(title='  '))
        form = response.context['form']
        for name in ('title', 'site', 'location', 'due_date', 'assignees'):
            self.assertIn(name, form.errors, name)
        response = self.client.post(NEW, form_data(site=str(self.tromso.pk), location=places.token(self.t1),
                                                   due_date=self.today.isoformat(), assignees=[self.ali.pk]))
        self.assertEqual(response.context['form'].errors['location'], ['This place is not on the chosen site.'])
        response = self.client.post(NEW, form_data(site=str(self.bergen.pk), location='unit:not-a-uuid',
                                                   due_date=self.today.isoformat(), assignees=[self.ali.pk]))
        self.assertIn('location', response.context['form'].errors)
        self.assertFalse(Task.objects.exists())

    def test_a_form_sent_twice_creates_one_task(self):
        response = self.client.get(NEW)
        key = response.context['form']['entry_key'].value()
        data = form_data(site=str(self.bergen.pk), location=places.token(self.t1), due_date=self.today.isoformat(),
                         assignees=[self.ali.pk], entry_key=key)
        first = self.client.post(NEW, data)
        second = self.client.post(NEW, data)
        task = Task.objects.get()
        self.assertEqual(first['Location'], second['Location'])
        self.assertEqual(second['Location'], edit_url(task))
        self.assertEqual(EntryKey.record_of(uuid.UUID(str(key)), Task), task)
        self.assertEqual(AuditLog.objects.filter(entity_id=str(task.pk), action='create').count(), 1)

    def test_two_sendings_at_once_create_one_task(self):
        # The second request does not see the first one's task yet; its insert waits on the key and is refused.
        key = uuid.uuid4()
        data = form_data(site=str(self.bergen.pk), location=places.token(self.t1), due_date=self.today.isoformat(),
                         assignees=[self.ali.pk], entry_key=str(key))
        self.client.post(NEW, data)
        task = Task.objects.get()
        with mock.patch('tasks.forms.TaskForm.sent_before', side_effect=[None, task]):
            response = self.client.post(NEW, data)
        self.assertEqual(response['Location'], edit_url(task))
        self.assertEqual(Task.objects.count(), 1)

    def test_an_outdated_version_is_refused(self):
        task = self.make_task()
        data = form_data(title='Mine', site=str(self.bergen.pk), location=places.token(self.t1),
                         due_date=self.today.isoformat(), assignees=[self.ali.pk], version=task.version)
        Task.objects.filter(pk=task.pk).update(version=5)
        self.client.post(edit_url(task), data)
        task.refresh_from_db()
        self.assertEqual(task.title, 'Clean the drum filter')


class ListsOfferedTests(TasksTestCase):
    def test_the_assignee_list_offers_exactly_the_active_people_who_can_read_tasks(self):
        form = self.client.get(NEW).context['form']
        self.assertEqual(list(form.fields['assignees'].queryset), [self.ali, self.boss, self.kari])
        admin = type(self.boss).objects.create_superuser('root', 'root@example.com', 'x')
        direct = type(self.boss).objects.create_user('dora', 'dora@example.com', 'x')
        direct.user_permissions.add(Permission.objects.get(codename='view_task'))
        form = self.client.get(NEW).context['form']
        self.assertEqual(set(form.fields['assignees'].queryset), {self.ali, self.boss, self.kari, admin, direct})
        html = self.client.get(NEW).content.decode()
        self.assertIn('Ali Kaya', html)
        self.assertNotIn('Gone Away', html)
        self.assertNotIn('olav', html)

    def test_a_person_who_cannot_be_given_tasks_is_refused_but_one_already_given_stays(self):
        response = self.client.post(NEW, form_data(site=str(self.bergen.pk), location=places.token(self.t1),
                                                   due_date=self.today.isoformat(), assignees=[self.outsider.pk]))
        self.assertIn('assignees', response.context['form'].errors)
        task = self.make_task(assignees=[self.ali, self.kari])
        self.kari.is_active = False
        self.kari.save()
        form = self.client.get(edit_url(task)).context['form']
        self.assertIn(self.kari, form.fields['assignees'].queryset)
        self.assertIn('(can no longer be chosen)', self.client.get(edit_url(task)).content.decode())
        response = self.client.post(edit_url(task), form_data(
            site=str(self.bergen.pk), location=places.token(self.t1), due_date=self.today.isoformat(),
            assignees=[self.ali.pk, self.kari.pk], version=task.version))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(set(task.assignees.all()), {self.ali, self.kari})

    def test_the_location_list_offers_every_live_place_grouped_and_tied_to_its_site(self):
        html = self.client.get(NEW).content.decode()
        self.assertIn('data-depends-on="site"', html)
        for place in (self.bergen, self.tromso, self.hall, self.sea, self.ras, self.t1, self.t2, self.pump):
            self.assertIn(f'value="{places.token(place)}" data-group="{places.site_of(place).pk}"', html)
        # a place without a site belongs to "Without a site", which the Site list offers
        self.assertIn(f'value="{places.token(self.loose)}" data-group="{NONE}"', html)
        self.assertIn(f'value="{places.token(self.t9)}" data-group="{NONE}"', html)
        self.assertIn(f'<option value="{NONE}">Without a site</option>', html)
        for label in ('Whole site', 'Production departments', 'Systems', 'Units', 'Equipment'):
            self.assertIn(f'<optgroup label="{label}">', html)
        self.t2.soft_delete(self.boss)
        html = self.client.get(NEW).content.decode()
        self.assertNotIn(places.token(self.t2), html)

    def test_without_places_without_a_site_the_site_list_has_no_such_choice(self):
        self.t9.soft_delete(self.boss)
        self.loose.soft_delete(self.boss)
        self.assertNotIn(f'value="{NONE}"', self.client.get(NEW).content.decode())

    def test_a_place_without_a_site_is_chosen_with_without_a_site(self):
        response = self.client.post(NEW, form_data(site=NONE, location=places.token(self.t9),
                                                   due_date=self.today.isoformat(), assignees=[self.ali.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Task.objects.get().unit, self.t9)

    def test_the_batch_list_offers_the_batches_with_fish_tied_to_their_places(self):
        batch = stock_fish(self.stocker, self.t1)
        empty = stock_fish(self.stocker, self.t2)
        from farm.stock import services as stock
        stock.record_mortality(self.boss, unit=self.t2, batch=empty, day=stock.local_today(self.t2), count=1000,
                               cause='disease')
        html = self.client.get(NEW).content.decode()
        self.assertIn('data-depends-on="location"', html)
        groups = ' '.join(sorted(places.token(place) for place in (self.t1, self.hall, self.bergen)))
        self.assertIn(f'value="{batch.pk}" data-group="{groups}"', html)
        self.assertNotIn(f'value="{empty.pk}"', html)
        # chosen at a place where it has no fish, refused; at its unit, stored
        data = form_data(site=str(self.tromso.pk), location=places.token(self.sea), due_date=self.today.isoformat(),
                         assignees=[self.ali.pk], batch=str(batch.pk))
        response = self.client.post(NEW, data)
        self.assertEqual(response.context['form'].errors['batch'], [f'{batch.code} has no fish at Sea now.'])
        data.update(site=str(self.bergen.pk), location=places.token(self.hall))
        self.assertEqual(self.client.post(NEW, data).status_code, 302)
        self.assertEqual(Task.objects.get().batch, batch)

    def test_a_task_keeps_its_batch_after_the_fish_left(self):
        batch = stock_fish(self.stocker, self.t1)
        task = self.make_task(batch=batch)
        from farm.stock import services as stock
        stock.record_mortality(self.boss, unit=self.t1, batch=batch, day=stock.local_today(self.t1), count=1000,
                               cause='disease')
        response = self.client.post(edit_url(task), form_data(
            title='Renamed', site=str(self.bergen.pk), location=places.token(self.t1), batch=str(batch.pk),
            due_date=self.today.isoformat(), assignees=[self.ali.pk], version=task.version))
        self.assertEqual(response.status_code, 302)
        task.refresh_from_db()
        self.assertEqual((task.title, task.batch), ('Renamed', batch))

    def test_a_new_task_can_start_at_a_known_place(self):
        form = self.client.get(f'{NEW}?place={places.token(self.ras)}').context['form']
        self.assertEqual((form['site'].value(), form['location'].value()), (str(self.bergen.pk), places.token(self.ras)))


class DeletedPlaceTests(TasksTestCase):
    def test_an_open_task_does_not_hold_its_place_back_and_shows_it_deleted_until_it_is_restored(self):
        task = self.make_task(place=self.t2)
        self.client.force_login(type(self.boss).objects.create_superuser('root', 'root@example.com', 'x'))
        confirm = self.client.get(reverse('farm:tank_delete', args=[self.t2.pk]))
        plan = confirm.context['plan']
        self.assertTrue(plan.can_delete)
        self.assertEqual(plan.kept_groups()[0]['label'], 'Tasks')
        self.assertEqual(plan.kept_groups()[0]['count'], 1)
        self.assertContains(confirm, 'They stay in the task lists, which show this as deleted')
        self.client.post(reverse('farm:tank_delete', args=[self.t2.pk]))
        task.refresh_from_db()
        self.assertFalse(task.is_deleted)
        self.assertTrue(task.unit.is_deleted)
        self.assertContains(self.client.get(LIST), 'Place deleted')
        self.assertContains(self.client.get(f'{LIST}?task={task.pk}'), 'Place deleted')
        # it can still be completed, and editing it asks for another place
        services.complete(self.ali, task)
        form = self.client.get(edit_url(task)).context['form']
        self.assertIn('is deleted: choose another', form.fields['location'].help_text)
        self.assertEqual(form['location'].value(), None)
        softdelete.restore(self.t2.__class__.all_objects.get(pk=self.t2.pk), self.boss)
        self.assertNotContains(self.client.get(LIST + '?view=completed'), 'Place deleted')

    def test_deleting_a_site_counts_the_tasks_of_its_places_once_each(self):
        self.make_task(place=self.ras)
        self.make_task(place=self.tromso, title='Report to Mattilsynet')
        plan = softdelete.plan_delete(self.bergen)
        self.assertEqual(plan.kept_groups(), [{'label': 'Tasks', 'count': 1, 'note': Task.kept_note}])


class ViewsAndFiltersTests(TasksTestCase):
    def test_today_lists_the_overdue_first_then_due_today_then_done_today(self):
        self.make_task(title='Late', due_date=self.day(-2))
        today = self.make_task(title='Today', due_date=self.today, due_time=time(23, 59))
        done = self.make_task(title='Done', due_date=self.day(-5))
        services.complete(self.ali, done)
        later = self.make_task(title='Later', due_date=self.day(3))
        cancelled = self.make_task(title='Dropped', due_date=self.today)
        services.cancel(self.boss, cancelled, 'Unit emptied')
        response = self.client.get(LIST)
        self.assertEqual([task.title for task in response.context['objects']], ['Late', 'Today', 'Done'])
        self.assertTrue(response.context['objects'][0].overdue)
        self.assertContains(response, 'Overdue')
        opened = self.client.get(f'{LIST}?view=open').context['objects']
        self.assertEqual([task.title for task in opened], ['Late', 'Today', 'Later'])
        closed = self.client.get(f'{LIST}?view=completed').context['objects']
        self.assertEqual([task.title for task in closed], ['Dropped', 'Done'])
        self.assertNotIn(later, list(self.client.get(LIST).context['objects']))
        self.assertEqual({item['key']: item['count'] for item in response.context['views']},
                         {'today': 2, 'open': 3, 'completed': None})
        self.assertEqual(today.status, Status.OPEN)

    def test_filters_narrow_on_the_server(self):
        mine = self.make_task(title='Mine', place=self.t1, priority='high', category='feeding', assignees=[self.boss])
        theirs = self.make_task(title='Theirs', place=self.t2, due_date=self.day(4))
        loose = self.make_task(title='Loose', place=self.t9)
        cases = {
            'assignee=me': [mine], f'assignee={self.ali.pk}': [theirs, loose],
            f'site={self.tromso.pk}': [theirs], f'site={NONE}': [loose],
            f'location={places.token(self.t1)}': [mine], 'priority=high': [mine], 'category=feeding': [mine],
            f'from={self.day(1).isoformat()}': [theirs], f'to={self.today.isoformat()}': [mine, loose],
            'q=Thei': [theirs], 'site=nonsense': [mine, theirs, loose],
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                found = self.client.get(f'{LIST}?view=open&{query}').context['objects']
                self.assertEqual({task.title for task in found}, {task.title for task in expected})

    def test_the_list_is_paged_on_the_server(self):
        for number in range(55):
            self.make_task(title=f'Job {number:02d}')
        page = self.client.get(f'{LIST}?view=open')
        self.assertEqual(len(page.context['objects']), 50)
        self.assertEqual(len(self.client.get(f'{LIST}?view=open&page=2').context['objects']), 5)


class OverdueOnTheSitesClockTests(TasksTestCase):
    """A task due 3 Nov at 23:00 on an Oslo site: 23:30 UTC on 2 Nov is 00:30 on 3 Nov in Oslo (due today, not
    overdue); 22:30 UTC on 3 Nov is 23:30 in Oslo (its time has passed: overdue)."""

    def test_overdue_and_today_follow_the_sites_clock(self):
        task = self.make_task(due_date=datetime(2026, 11, 3).date(), due_time=time(23, 0), place=self.bergen)
        utc = ZoneInfo('UTC')
        early = datetime(2026, 11, 2, 23, 30, tzinfo=utc)
        late = datetime(2026, 11, 3, 22, 30, tzinfo=utc)
        tasks = Task.objects.all()
        self.assertEqual(list(read.view(tasks, read.TODAY, early)), [task])
        self.assertFalse(read.view(tasks, read.TODAY, early).get().overdue)
        self.assertTrue(read.view(tasks, read.TODAY, late).get().overdue)
        # without a due time it is overdue only once its day is over on that clock
        Task.objects.filter(pk=task.pk).update(due_time=None)
        self.assertFalse(read.view(tasks, read.TODAY, late).get().overdue)
        self.assertTrue(read.view(tasks, read.TODAY, datetime(2026, 11, 3, 23, 30, tzinfo=utc)).get().overdue)
        # a UTC site is still on 3 Nov at 23:30 UTC
        utc_site = type(self.bergen).objects.create(name='Utc', code='UT', timezone='UTC')
        Task.objects.filter(pk=task.pk).update(site=utc_site)
        self.assertFalse(read.view(tasks, read.TODAY, datetime(2026, 11, 3, 23, 30, tzinfo=utc)).get().overdue)

    def test_done_today_is_the_sites_today(self):
        task = self.make_task(due_date=datetime(2026, 11, 1).date())
        moment = datetime(2026, 11, 3, 23, 30, tzinfo=ZoneInfo('UTC'))     # 4 Nov 00:30 in Oslo
        Task.objects.filter(pk=task.pk).update(status=Status.DONE, completed_by=self.ali,
                                               completed_at=datetime(2026, 11, 3, 22, 0, tzinfo=ZoneInfo('UTC')))
        self.assertEqual(list(read.view(Task.objects.all(), read.TODAY, moment)), [])
        self.assertEqual(list(read.view(Task.objects.all(), read.TODAY, moment - timedelta(hours=1))), [task])


class ActionTests(TasksTestCase):
    def act(self, user, name, task, data=None):
        self.client.force_login(user)
        return self.client.post(reverse(f'tasks:task_{name}', args=[task.pk]), data or {})

    def test_an_assignee_starts_ticks_and_completes_and_a_non_assignee_with_read_may_not(self):
        task = self.make_task(assignees=[self.ali])
        item = TaskChecklistItem.objects.create(task=task, text='Brush the screens')
        self.assertEqual(self.act(self.kari, 'start', task).status_code, 403)
        self.assertEqual(self.act(self.kari, 'complete', task, {'note': ''}).status_code, 403)
        self.client.force_login(self.kari)
        self.assertEqual(self.client.post(reverse('tasks:task_tick', args=[task.pk, item.pk]), {'done': '1'}).status_code,
                         403)
        self.act(self.ali, 'start', task)
        task.refresh_from_db()
        self.assertEqual((task.status, task.started_by), (Status.IN_PROGRESS, self.ali))
        self.assertIsNotNone(task.started_at)
        self.client.post(reverse('tasks:task_tick', args=[task.pk, item.pk]), {'done': '1'})
        self.client.post(reverse('tasks:task_tick', args=[task.pk, item.pk]), {'done': '1'})     # the same set twice
        item.refresh_from_db()
        self.assertEqual(item.done_by, self.ali)
        self.assertEqual(AuditLog.objects.filter(entity_id=str(task.pk), changes__has_key='Checklist').count(), 1)
        response = self.act(self.ali, 'complete', task, {'note': '2 dead fish removed'})
        self.assertEqual(response.status_code, 302)
        task.refresh_from_db()
        self.assertEqual((task.status, task.completed_by, task.completion_note),
                         (Status.DONE, self.ali, '2 dead fish removed'))
        # the log says a completion note was given, never its words (a person's free text, owner decision F-061)
        done = AuditLog.objects.get(entity_id=str(task.pk), changes__has_key='Completion note')
        self.assertEqual(done.changes['Completion note'], [None, private('2 dead fish removed')])
        self.assertNotIn('dead fish', str(list(AuditLog.objects.values_list('changes', flat=True))))
        # a closed task's checklist is not ticked
        self.client.post(reverse('tasks:task_tick', args=[task.pk, item.pk]), {'done': '0'})
        item.refresh_from_db()
        self.assertIsNotNone(item.done_at)

    def test_whoever_may_edit_completes_cancels_and_reopens_any_task(self):
        task = self.make_task(assignees=[self.ali])
        self.assertEqual(self.act(self.ali, 'cancel', task, {'reason': 'No'}).status_code, 403)
        response = self.act(self.boss, 'cancel', task, {'reason': ''})
        self.assertIn('reason', response.context['form'].errors)
        self.act(self.boss, 'cancel', task, {'reason': 'The unit was emptied'})
        task.refresh_from_db()
        self.assertEqual((task.status, task.cancelled_by, task.cancel_reason),
                         (Status.CANCELLED, self.boss, 'The unit was emptied'))
        self.assertEqual(self.act(self.ali, 'reopen', task).status_code, 403)
        self.act(self.boss, 'reopen', task)
        task.refresh_from_db()
        self.assertEqual((task.status, task.cancelled_by, task.cancel_reason, task.cancelled_at),
                         (Status.OPEN, None, '', None))
        self.act(self.boss, 'complete', task, {'note': ''})
        task.refresh_from_db()
        self.assertEqual(task.completed_by, self.boss)
        self.act(self.boss, 'reopen', task)
        task.refresh_from_db()
        self.assertEqual((task.status, task.completed_by, task.completed_at, task.started_at), (Status.OPEN, None, None,
                                                                                             None))
        self.assertEqual(task.version, 5)
        changes = [log.changes.get('Status') for log in AuditLog.objects.filter(entity_id=str(task.pk), action='update')
                   .order_by('created_at')]
        self.assertEqual([change[1]['msgid'] for change in changes if change],
                         ['Cancelled', 'Open', 'Done', 'Open'])
        # the reason for cancelling is private in the log: given, then cleared by the reopening, the same value both times
        reasons = [log.changes['Reason for cancelling'] for log in AuditLog.objects.filter(
            entity_id=str(task.pk), changes__has_key='Reason for cancelling').order_by('created_at')]
        self.assertEqual(reasons, [[None, private('The unit was emptied')], [private('The unit was emptied'), None]])
        self.assertNotIn('emptied', str(list(AuditLog.objects.values_list('changes', flat=True))))

    def test_the_dialogs_render_and_a_closed_task_cannot_be_closed_again(self):
        task = self.make_task()
        for name in ('complete', 'cancel'):
            for headers in ({}, {'X-Modal': '1'}):
                response = self.client.get(reverse(f'tasks:task_{name}', args=[task.pk]), headers=headers)
                self.assertEqual(response.status_code, 200)
        services.complete(self.boss, task)
        response = self.act(self.boss, 'complete', task, {'note': ''})
        self.assertIn('This task is already done.', response.context['form'].non_field_errors())

    def test_anyone_who_reads_tasks_adds_a_note_and_it_is_kept_and_logged(self):
        task = self.make_task()
        next_url = f'{LIST}?task={task.pk}&view=open'
        response = self.act(self.kari, 'note', task, {'body': '  Filter cleaned  ', 'next': next_url})
        self.assertRedirects(response, next_url, fetch_redirect_response=False)
        note = TaskNote.objects.get()
        self.assertEqual((note.body, note.author), ('Filter cleaned', self.kari))
        # kept on the task for who reads it; in the log only that a note was added (private, with its digest)
        self.assertEqual(AuditLog.objects.get(entity_id=str(task.pk), changes__has_key='Note').changes['Note'],
                         [None, private('Filter cleaned')])
        self.assertNotIn('Filter cleaned', str(list(AuditLog.objects.values_list('changes', flat=True))))
        self.act(self.kari, 'note', task, {'body': '   '})
        self.assertEqual(TaskNote.objects.count(), 1)
        self.assertEqual(self.act(self.outsider, 'note', task, {'body': 'x'}).status_code, 403)
        # `next` only goes to a Tasks address
        response = self.act(self.kari, 'note', task, {'body': 'Again', 'next': 'https://evil.example/'})
        self.assertEqual(response['Location'], f'{LIST}?task={task.pk}')

    def test_the_drawer_offers_what_the_person_may_do(self):
        task = self.make_task(assignees=[self.ali])
        TaskChecklistItem.objects.create(task=task, text='Brush the screens')
        self.client.force_login(self.ali)
        actions = self.client.get(f'{LIST}?task={task.pk}').context['actions']
        self.assertTrue(actions['start'] and actions['complete'])
        self.assertFalse(actions['cancel'] or actions['reopen'] or actions['edit'] or actions['delete'])
        self.client.force_login(self.kari)
        drawer = self.client.get(f'{LIST}?task={task.pk}')
        self.assertFalse(any(drawer.context['actions'].values()))
        self.assertFalse(drawer.context['may_tick'])
        self.client.force_login(self.boss)
        actions = self.client.get(f'{LIST}?task={task.pk}').context['actions']
        self.assertTrue(all(actions[name] for name in ('start', 'complete', 'cancel', 'edit', 'delete')))

    def test_the_checklist_is_edited_as_a_list_until_its_first_tick(self):
        task = self.make_task()
        url = reverse('tasks:task_checklist', args=[task.pk])
        from farm.tests.helpers import rows_data
        self.client.post(url, rows_data('checklist', [{'text': 'Stop the pump'}, {'text': 'Brush the screens'}], record=task))
        self.assertEqual(list(task.checklist.values_list('text', flat=True)), ['Stop the pump', 'Brush the screens'])
        first = task.checklist.first()
        services.tick(self.ali, first, True)
        rows = [{'id': item.pk, 'text': item.text} for item in task.checklist.all()]
        response = self.client.post(url, rows_data('checklist', rows + [{'text': 'More'}], initial=2, record=task))
        self.assertEqual(task.checklist.count(), 2)
        self.assertContains(response, 'The checklist has been started')
        self.assertContains(self.client.get(edit_url(task)), 'its lines can no longer be changed')


class IntegrationTests(TasksTestCase):
    def test_the_menu_the_role_matrix_and_the_page_heading(self):
        place = navigation.place('tasks.view_task')
        self.assertEqual((english(place.workspace.label), english(place.section.label), english(place.entry.label)),
                         ('Production', 'Operations', 'Tasks'))
        self.assertEqual(english(navigation.place('tasks.view_taskseries').entry.label), 'Recurring tasks')
        areas = {area.model: area.actions for area in access.areas()}
        self.assertEqual(areas['tasks.Task'], ('view', 'add', 'change', 'delete'))
        self.assertEqual(areas['tasks.TaskSeries'], ('view', 'add', 'change', 'delete'))
        page = self.client.get(LIST)
        self.assertContains(page, '<h1')
        self.assertEqual(self.client.get(reverse('tasks:taskseries_list')).status_code, 200)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(LIST).status_code, 403)
        self.assertNotContains(self.client.get(reverse('home')), LIST)

    def test_the_database_viewer_shows_the_tables(self):
        names = {table.name for _, tables in database.sections() for table in tables}
        self.assertTrue({'tasks', 'task_assignees', 'task_checklist_items', 'task_notes', 'task_series',
                         'task_series_assignees', 'task_series_checklist_items'} <= names)

    def test_the_overview_counts_tasks_due_today_and_overdue(self):
        self.make_task(due_date=self.day(-1))
        self.make_task(due_date=self.today, due_time=time(23, 59))
        page = self.client.get(reverse('production_home'))
        tiles = {english(tile['label']): tile['count'] for tile in page.context['task_tiles']}
        self.assertEqual(tiles, {'Tasks due today': 1, 'Overdue tasks': 1})

    def test_every_page_renders_in_each_language(self):
        task = self.make_task()
        TaskNote.objects.create(task=task, author=self.ali, body='Done half')
        pages = [LIST, f'{LIST}?task={task.pk}', f'{LIST}?view=open', f'{LIST}?view=completed', NEW, edit_url(task),
                 reverse('tasks:task_delete', args=[task.pk]), reverse('tasks:task_complete', args=[task.pk]),
                 reverse('tasks:task_cancel', args=[task.pk]), reverse('tasks:taskseries_list'),
                 reverse('tasks:taskseries_create')]
        for language in ('en', 'tr', 'nb'):
            Profile.objects.update_or_create(user=self.boss, defaults={'language': language})
            for url in pages:
                for headers in ({}, {'X-Modal': '1'}):
                    with self.subTest(language=language, url=url, modal=bool(headers)):
                        response = self.client.get(url, headers=headers)
                        self.assertEqual(response.status_code, 200)
                        self.assertNotIn('%(', response.content.decode())
                        self.assertEqual(response['Content-Language'], language)
        Profile.objects.update_or_create(user=self.boss, defaults={'language': 'nb'})
        self.assertContains(self.client.get(LIST), 'Oppgaver')

    def test_the_moment_a_task_is_due_now_is_not_yet_overdue(self):
        with mock.patch('farm.clocks.timezone.now', return_value=timezone.now()):
            self.make_task(due_date=self.today, due_time=None)
            self.assertEqual(read.counts(Task.objects.all())['overdue'], 0)
