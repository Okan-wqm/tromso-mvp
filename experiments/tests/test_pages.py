"""Research › Experiments through its pages, each checked against the stored rows: create (the number, the creator as
lead, a form sent twice), read, edit (the log, a stale version, what a started experiment fixes), the team, delete
through the plan, the list, who may do what on every URL, the menu, and the database viewer."""
import uuid

from django.contrib.auth import get_user_model
from django.urls import reverse

from core import access, database, navigation, softdelete
from core.models import AuditLog, Profile
from farm.models import Species
from farm.tests.helpers import make_species, role, rows_data

from ..models import Experiment, ExperimentGroup, Factor, Level, Member, Replicate, ReplicateUnit
from . import ExperimentTestCase
from core.testing import delete_confirmed

RESEARCHER = ('view_experiment', 'add_experiment', 'change_experiment', 'delete_experiment', 'view_auditlog')
STUDENT = ('view_experiment', 'add_experiment', 'change_experiment')
READER = ('view_experiment',)


def person(username, *codenames, **fields):
    user = get_user_model().objects.create_user(username, f'{username}@example.com', 'x', **fields)
    if codenames:
        user.groups.add(role(f'{username} role', *codenames))
    return user


class PageTestCase(ExperimentTestCase):
    def setUp(self):
        super().setUp()
        self.user.groups.add(role('Researcher', *RESEARCHER))

    def data(self, **fields):
        return {'entry_key': str(uuid.uuid4()), 'name': 'Diet trial', 'species': str(self.salmon.pk),
                'site': str(self.bergen.pk), 'hypothesis': 'More protein grows salmon faster',
                'primary_endpoint': 'bfcr', 'starts_on': self.day(7).isoformat(), 'duration_days': '56',
                'notes': 'Hall A', **fields}

    def create(self, **fields):
        response = self.client.post(reverse('experiments:experiment_create'), self.data(**fields))
        return response

    def started(self, trial):
        """The experiment started by the ORM past the service (what the page's rules are tested against)."""
        Experiment.objects.filter(pk=trial.pk).update(
            status='running', starts_on=self.today, hypothesis='More protein grows salmon faster',
            primary_endpoint='bfcr', allocation_method='manual', allocation_note='by hand')
        trial.refresh_from_db()
        return trial


class CreateTests(PageTestCase):
    def test_a_new_experiment_is_stored_numbered_logged_and_led_by_its_creator(self):
        response = self.create()
        trial = Experiment.objects.get()
        self.assertRedirects(response, reverse('experiments:experiment_edit', args=[trial.pk]))
        self.assertEqual((trial.code, trial.name, trial.status, trial.is_template, trial.site, trial.species,
                          trial.hypothesis, trial.primary_endpoint, trial.starts_on, trial.duration_days, trial.notes,
                          trial.allocation_method, trial.created_by, trial.version),
                         (f'E-{self.today.year}-001', 'Diet trial', 'draft', False, self.bergen, self.salmon,
                          'More protein grows salmon faster', 'bfcr', self.day(7), 56, 'Hall A', '', self.user, 1))
        member = Member.objects.get()
        self.assertEqual((member.experiment, member.user, member.role, member.created_by),
                         (trial, self.user, 'lead', self.user))
        created, team = AuditLog.objects.filter(entity_id=str(trial.pk)).order_by('created_at')
        self.assertEqual((created.action, created.entity_type, created.entity_label),
                         ('create', 'experiment', f'{trial.code} · Diet trial'))
        self.assertEqual(created.changes, {
            'Name': [None, 'Diet trial'], 'Species': [None, 'Atlantic salmon (SAL)'], 'Site': [None, 'Bergen (BG)'],
            'Hypothesis': [None, 'More protein grows salmon faster'],
            'Primary endpoint': [None, {'msgid': 'Biological FCR'}], 'Starts on': [None, self.day(7).isoformat()],
            'Duration (days)': [None, '56'], 'Notes': [None, 'Hall A']})
        self.assertEqual((team.action, team.changes), ('update', {'Team': [None, 'ali (Lead)']}))

    def test_the_numbers_count_on_never_repeat_and_follow_the_year_of_the_site(self):
        self.create(name='First')
        self.create(name='Second')
        first = Experiment.objects.get(name='First')
        self.assertEqual(sorted(Experiment.objects.values_list('code', flat=True)),
                         [f'E-{self.today.year}-001', f'E-{self.today.year}-002'])
        first.soft_delete(self.user)
        self.create(name='Third')
        self.assertEqual(Experiment.objects.get(name='Third').code, f'E-{self.today.year}-003')

    def test_the_same_form_sent_twice_creates_one_experiment(self):
        data = self.data()
        self.client.post(reverse('experiments:experiment_create'), data)
        second = self.client.post(reverse('experiments:experiment_create'), data)
        self.assertEqual(Experiment.objects.count(), 1)
        self.assertEqual(Member.objects.count(), 1)
        self.assertRedirects(second, reverse('experiments:experiment_edit', args=[Experiment.objects.get().pk]))

    def test_what_is_wrong_is_said_on_the_field_and_nothing_is_stored(self):
        cases = [({'name': ''}, 'name', 'This field is required.'),
                 ({'duration_days': '0'}, 'duration_days', 'Ensure this value is greater than or equal to 1.'),
                 ({'duration_days': '1096'}, 'duration_days', 'Ensure this value is less than or equal to 1095.'),
                 ({'duration_days': ''}, 'duration_days', 'This field is required.'),
                 ({'species': ''}, 'species', 'This field is required.'),
                 ({'site': ''}, 'site', 'This field is required.'),
                 ({'primary_endpoint': 'weight'}, 'primary_endpoint',
                  'Select a valid choice. weight is not one of the available choices.'),
                 ({'starts_on': 'soon'}, 'starts_on', 'Give the date as dd.mm.yyyy, e.g. 06.11.2026.')]
        for fields, field, message in cases:
            with self.subTest(field=field, value=fields[field]):
                response = self.create(**fields)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['form'].errors[field], [message])
        self.assertFalse(Experiment.objects.exists())

    def test_a_species_the_farm_does_not_grow_is_not_offered_or_accepted(self):
        retired = make_species('COD', 'Cod', 'Gadus morhua', status=Species.Status.INACTIVE)
        form = self.client.get(reverse('experiments:experiment_create')).context['form']
        self.assertEqual(list(form.fields['species'].queryset), [self.salmon, self.trout])    # by common name
        self.assertNotIn(retired, form.fields['species'].queryset)
        self.assertIn('species', self.create(species=str(retired.pk)).context['form'].errors)

    def test_a_draft_or_a_template_is_made_from_the_details_alone_without_a_start_day(self):
        self.create(starts_on='', hypothesis='', primary_endpoint='')
        trial = Experiment.objects.get()
        self.assertEqual((trial.starts_on, trial.hypothesis, trial.primary_endpoint), (None, '', ''))


class EditTests(PageTestCase):
    def setUp(self):
        super().setUp()
        self.create()
        self.trial = Experiment.objects.get()
        self.url = reverse('experiments:experiment_edit', args=[self.trial.pk])

    def post(self, **fields):
        data = {**self.data(), 'version': str(self.trial.version), **fields}
        data.pop('entry_key')
        return self.client.post(self.url, data)

    def test_the_form_shows_what_is_stored_and_fixes_the_species_and_the_site(self):
        form = self.client.get(self.url).context['form']
        self.assertEqual((form['name'].value(), form['hypothesis'].value(), form['duration_days'].value(),
                          form['version'].value()), ('Diet trial', 'More protein grows salmon faster', 56, 1))
        self.assertTrue(form.fields['species'].disabled and form.fields['site'].disabled)
        self.post(species=str(self.trout.pk), site=str(self.tromso.pk))              # posted, and ignored
        self.trial.refresh_from_db()
        self.assertEqual((self.trial.species, self.trial.site), (self.salmon, self.bergen))

    def test_an_edit_is_stored_logged_as_what_changed_and_counted(self):
        response = self.post(name='Protein trial', hypothesis='Fish meal beats soy', duration_days='70',
                             primary_endpoint='survival')
        self.assertRedirects(response, reverse('experiments:experiment_list'))
        self.trial.refresh_from_db()
        self.assertEqual((self.trial.name, self.trial.hypothesis, self.trial.duration_days,
                          self.trial.primary_endpoint, self.trial.version, self.trial.updated_by),
                         ('Protein trial', 'Fish meal beats soy', 70, 'survival', 2, self.user))
        entry = AuditLog.objects.filter(entity_id=str(self.trial.pk), action='update').latest('created_at')
        self.assertEqual(entry.changes, {
            'Name': ['Diet trial', 'Protein trial'],
            'Hypothesis': ['More protein grows salmon faster', 'Fish meal beats soy'],
            'Primary endpoint': [{'msgid': 'Biological FCR'}, {'msgid': 'Survival'}],
            'Duration (days)': ['56', '70']})
        before = AuditLog.objects.count()
        self.post(version='2', name='Protein trial', hypothesis='Fish meal beats soy', duration_days='70',
                  primary_endpoint='survival')                                     # nothing changed: nothing logged
        self.assertEqual(AuditLog.objects.count(), before)

    def test_a_stale_version_is_refused_and_nothing_is_changed(self):
        self.post(name='Mine')
        response = self.post(name='Theirs', version='1')
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.trial.refresh_from_db()
        self.assertEqual((self.trial.name, self.trial.version), ('Mine', 2))
        self.assertContains(self.client.get(self.url), 'Someone else changed this experiment')

    def test_a_started_experiment_fixes_its_design_fields_and_keeps_its_name_and_notes_editable(self):
        self.started(self.trial)
        form = self.client.get(self.url).context['form']
        for name in ('hypothesis', 'primary_endpoint', 'starts_on', 'duration_days', 'species', 'site'):
            self.assertTrue(form.fields[name].disabled, name)
        self.assertEqual(form.fields['hypothesis'].help_text,
                         'Fixed: the experiment has started. Copy it to change the design.')
        self.assertFalse(form.fields['name'].disabled or form.fields['notes'].disabled)
        self.post(name='Renamed', notes='Pump swapped', hypothesis='Another hypothesis', duration_days='99',
                  starts_on=self.day(30).isoformat(), primary_endpoint='efcr')
        self.trial.refresh_from_db()
        self.assertEqual((self.trial.name, self.trial.notes, self.trial.hypothesis, self.trial.duration_days,
                          self.trial.starts_on, self.trial.primary_endpoint),
                         ('Renamed', 'Pump swapped', 'More protein grows salmon faster', 56, self.today, 'bfcr'))

    def test_the_history_tab_lists_the_changes(self):
        self.post(name='Protein trial')
        page = self.client.get(self.url)
        self.assertContains(page, 'Protein trial')
        self.assertEqual(len(page.context['history']), 3)               # created, team, changed


class ReadTests(PageTestCase):
    def test_the_list_and_the_read_page_show_the_experiment_to_a_reader(self):
        self.create()
        trial = Experiment.objects.get()
        Experiment.objects.filter(pk=trial.pk).update(audience='open')      # its lead opened it: a reader reads it
        reader = person('reader', *READER)
        self.client.force_login(reader)
        listing = self.client.get(reverse('experiments:experiment_list'))
        self.assertContains(listing, 'Diet trial')
        self.assertContains(listing, trial.code)
        self.assertContains(listing, 'Biological FCR')
        self.assertNotContains(listing, reverse('experiments:experiment_create'))
        self.assertNotContains(listing, f'href="{reverse("experiments:experiment_edit", args=[trial.pk])}"')
        page = self.client.get(reverse('experiments:experiment_detail', args=[trial.pk]))
        for text in (trial.code, 'Bergen', 'Atlantic salmon', 'More protein grows salmon faster', 'Biological FCR',
                     'Hall A', '56'):
            self.assertContains(page, text)
        self.assertContains(self.client.get(reverse('experiments:experiment_detail', args=[trial.pk]), {'tab': 'team'}),
                            'ali (Lead)')
        self.assertNotContains(page, f'href="{reverse("experiments:experiment_edit", args=[trial.pk])}"')

    def test_a_researcher_sees_the_edit_and_delete_links_and_a_started_one_has_no_delete(self):
        self.create()
        trial = Experiment.objects.get()
        listing = self.client.get(reverse('experiments:experiment_list'))
        self.assertContains(listing, f'href="{reverse("experiments:experiment_edit", args=[trial.pk])}"')
        self.assertContains(listing, f'href="{reverse("experiments:experiment_delete", args=[trial.pk])}"')
        self.started(trial)
        listing = self.client.get(reverse('experiments:experiment_list'))
        self.assertNotContains(listing, reverse('experiments:experiment_delete', args=[trial.pk]))
        self.assertContains(listing, 'Running')


class TeamTests(PageTestCase):
    def setUp(self):
        super().setUp()
        self.create()
        self.trial = Experiment.objects.get()
        self.url = reverse('experiments:experiment_team', args=[self.trial.pk])
        self.kari = person('kari', *STUDENT, first_name='Kari', last_name='Nord')
        self.olav = person('olav', *READER, first_name='Olav', last_name='Berg')
        self.nobody = person('nobody', 'view_site')

    def post(self, rows):
        return self.client.post(self.url, rows_data('team', rows, record=self.trial))

    def test_the_team_is_saved_as_a_whole_with_one_lead_and_logged_on_the_experiment(self):
        response = self.post([{'user': self.user.pk, 'role': 'lead'}, {'user': self.kari.pk, 'role': 'student'},
                              {'user': self.olav.pk, 'role': 'advisor'}])
        self.assertRedirects(response, reverse('experiments:experiment_edit', args=[self.trial.pk]))
        self.assertEqual(sorted(Member.objects.values_list('user__username', 'role')),
                         [('ali', 'lead'), ('kari', 'student'), ('olav', 'advisor')])
        self.assertEqual(set(Member.objects.values_list('created_by__username', flat=True)), {'ali'})
        entry = AuditLog.objects.filter(entity_id=str(self.trial.pk), action='update').latest('created_at')
        self.assertEqual(entry.changes['Team'][0], 'ali (Lead)')
        self.assertEqual(sorted(entry.changes['Team'][1].split('; ')),
                         ['Kari Nord (Student)', 'Olav Berg (Advisor)', 'ali (Lead)'])
        self.post([{'user': self.kari.pk, 'role': 'lead'}])                      # the lead handed over, ali left
        self.assertEqual(list(Member.objects.values_list('user__username', 'role')), [('kari', 'lead')])

    def test_a_team_without_a_lead_or_with_two_or_with_a_person_twice_is_refused_and_nothing_changes(self):
        cases = [([], 'The team needs a lead.'),
                 ([{'user': self.user.pk, 'role': 'researcher'}], 'The team needs a lead.'),
                 ([{'user': self.user.pk, 'role': 'lead'}, {'user': self.kari.pk, 'role': 'lead'}],
                  'An experiment has one lead.'),
                 ([{'user': self.user.pk, 'role': 'lead'}, {'user': self.kari.pk, 'role': 'student'},
                   {'user': self.kari.pk, 'role': 'advisor'}], 'This person is in the list twice.')]
        for rows, message in cases:
            with self.subTest(message=message, rows=len(rows)):
                response = self.post(rows)
                self.assertEqual(response.status_code, 200)
                self.assertIn(message, str(response.context['team'].non_form_errors()))
        self.assertEqual(list(Member.objects.values_list('user__username', 'role')), [('ali', 'lead')])

    def test_only_people_who_can_read_experiments_are_offered_and_accepted(self):
        form = self.client.get(reverse('experiments:experiment_edit', args=[self.trial.pk])).context['team'].empty_form
        offered = set(form.fields['user'].queryset.values_list('username', flat=True))
        self.assertEqual(offered, {'ali', 'kari', 'olav'})
        response = self.post([{'user': self.user.pk, 'role': 'lead'}, {'user': self.nobody.pk, 'role': 'student'}])
        self.assertEqual(response.status_code, 200)
        self.assertIn('user', response.context['team'].forms[1].errors)
        self.assertEqual(Member.objects.count(), 1)

    def test_a_person_kept_from_before_stays_in_the_list_whatever_they_can_read_now(self):
        self.post([{'user': self.user.pk, 'role': 'lead'}, {'user': self.kari.pk, 'role': 'student'}])
        self.kari.groups.clear()
        form = self.client.get(reverse('experiments:experiment_edit', args=[self.trial.pk])).context['team'].forms[1]
        self.assertIn(self.kari, form.fields['user'].queryset)

    def test_the_team_tab_is_on_the_experiments_page_and_the_row_names_the_people(self):
        page = self.client.get(reverse('experiments:experiment_edit', args=[self.trial.pk]))
        self.assertContains(page, 'data-tab="team"')
        self.assertContains(page, reverse('experiments:experiment_team', args=[self.trial.pk]))
        self.assertContains(page, 'Save team')
        self.assertContains(page, f'name="version" value="{self.trial.version}"')     # the list's save is refused when stale
        stale = rows_data('team', [{'user': self.user.pk, 'role': 'lead'}, {'user': self.kari.pk, 'role': 'student'}],
                          record=self.trial)
        stale['version'] = str(self.trial.version - 1)
        self.client.post(self.url, stale)
        self.assertEqual(Member.objects.count(), 1)


class DeleteTests(PageTestCase):
    def design(self, trial):
        """A design of every part: a diet factor, two groups, replicates, a placement."""
        diet = self.factor(trial, 'Diet')
        high, _low = self.level(diet), self.level(diet)
        group = self.group(trial, 'A')
        self.group_level(group, high)
        replicate = self.replicate(group, 1)
        self.placement(replicate, self.t1)
        return diet, group, replicate

    def test_a_draft_is_deleted_with_its_design_logged_one_row_each_and_its_tank_is_free_again(self):
        self.create()
        trial = Experiment.objects.get()
        self.design(trial)
        page = self.client.get(reverse('experiments:experiment_delete', args=[trial.pk]))
        for text in ('Experiment factors', 'Experiment groups', 'Replicates', 'Experiment placements', 'Factor levels'):
            self.assertContains(page, text)
        delete_confirmed(self.client, reverse('experiments:experiment_delete', args=[trial.pk]))
        self.assertTrue(Experiment.all_objects.get(pk=trial.pk).is_deleted)
        self.assertEqual((Factor.objects.count(), Level.objects.count(), ExperimentGroup.objects.count(),
                          Replicate.objects.count(), ReplicateUnit.objects.count()), (0, 0, 0, 0, 0))
        deleted = sorted(AuditLog.objects.filter(action='delete').values_list('entity_type', flat=True))
        self.assertEqual(deleted, ['experiment', 'experiment factor', 'experiment group', 'experiment placement',
                                   'factor level', 'factor level', 'replicate'])
        other = self.experiment('Next')
        group = self.group(other, 'B')
        self.placement(self.replicate(group, 1), self.t1)                           # the tank is free: no clash

    def test_a_started_experiment_is_not_deleted_and_the_page_says_why(self):
        self.create()
        trial = self.started(Experiment.objects.get())
        page = self.client.get(reverse('experiments:experiment_delete', args=[trial.pk]))
        self.assertContains(page, 'It has started: it is kept as a record. Close it instead.')
        delete_confirmed(self.client, reverse('experiments:experiment_delete', args=[trial.pk]))
        self.assertFalse(Experiment.all_objects.get(pk=trial.pk).is_deleted)
        self.assertFalse(AuditLog.objects.filter(action='delete').exists())

    def test_what_an_experiment_holds_cannot_be_deleted_while_it_does(self):
        trial = self.experiment()
        diet, group, replicate = self.design(trial)
        protocol = Level.objects.filter(factor=diet).first().protocol
        self.assertEqual(softdelete.plan_delete(protocol).blockers, ['1 factor level still belongs to it.'])
        self.assertEqual(softdelete.plan_delete(self.t1).blockers, ['1 experiment placement still belongs to it.'])
        self.assertEqual(softdelete.plan_delete(self.hall).blockers, ['1 experiment placement still belongs to it.'])
        self.assertIn('1 experiment still belongs to it.', softdelete.plan_delete(self.bergen).blockers)
        self.assertIn('1 experiment still belongs to it.', softdelete.plan_delete(self.salmon).blockers)
        self.client.force_login(get_user_model().objects.create_superuser('root', 'root@example.com', 'x'))
        for url in (reverse('farm:tank_delete', args=[self.t1.pk]), reverse('farm:site_delete', args=[self.bergen.pk])):
            self.assertContains(self.client.get(url), 'still belongs to it.')

    def test_a_restored_draft_comes_back_with_its_design(self):
        # What its delete took along comes back with it (core.softdelete.restore, F-067).
        trial = self.experiment()
        self.design(trial)
        softdelete.execute(softdelete.plan_delete(trial), self.user)
        softdelete.restore(Experiment.all_objects.get(pk=trial.pk), self.user)
        self.assertEqual(Experiment.objects.get(pk=trial.pk).status, 'draft')
        self.assertEqual((Factor.objects.count(), ExperimentGroup.objects.count(), ReplicateUnit.objects.count()),
                         (1, 1, 1))
        self.assertEqual(AuditLog.objects.filter(action='restore').count(),
                         AuditLog.objects.filter(action='delete').count())

    def test_a_copy_outlives_a_deleted_source_and_the_confirmation_says_it_stays(self):
        source = self.experiment('Template', is_template=True)
        copy = self.experiment('Copy', copied_from=source)
        plan = softdelete.plan_delete(source)
        self.assertEqual(dict(plan.kept), {Experiment: 1})
        self.assertContains(self.client.get(reverse('experiments:experiment_delete', args=[source.pk])),
                            'They stay as they are.')
        delete_confirmed(self.client, reverse('experiments:experiment_delete', args=[source.pk]))
        copy.refresh_from_db()
        self.assertEqual(copy.copied_from_id, source.pk)


class ListTests(PageTestCase):
    def test_views_filters_search_and_counts(self):
        mine = self.experiment('Mine trial', hypothesis='Soy meal')
        self.member(mine, self.user, 'lead')
        other = self.experiment('Other trial', site=self.tromso, species=self.trout)
        self.experiment('Template trial', is_template=True)
        group = self.group(mine, 'A')
        self.replicate(group, 1)
        self.replicate(group, 2)
        self.group(mine, 'B')
        self.started(other)
        url = reverse('experiments:experiment_list')

        def names(**params):
            return [experiment.name for experiment in self.client.get(url, params).context['objects']]
        self.assertEqual(sorted(names()), ['Mine trial', 'Other trial'])
        self.assertEqual(names(view='mine'), ['Mine trial'])
        self.assertEqual(names(view='templates'), ['Template trial'])
        self.assertEqual(names(status='running'), ['Other trial'])
        self.assertEqual(names(site=self.tromso.pk), ['Other trial'])
        self.assertEqual(names(species=self.salmon.pk), ['Mine trial'])
        self.assertEqual(names(q='soy'), ['Mine trial'])
        self.assertEqual(names(q=mine.code), ['Mine trial'])
        self.assertEqual(names(site='not-a-site'), names())                  # a stale value shows everything
        row = next(row for row in self.client.get(url).context['objects'] if row.pk == mine.pk)
        self.assertEqual((row.group_count, row.replicate_count), (2, 2))
        self.assertContains(self.client.get(url), 'Template')

    def test_an_empty_list_invites_the_first_experiment(self):
        page = self.client.get(reverse('experiments:experiment_list'))
        self.assertContains(page, 'No experiments yet')
        self.assertContains(page, reverse('experiments:experiment_create'))


class PermissionTests(PageTestCase):
    """Each role on every URL, and a signed-out visitor."""

    def setUp(self):
        super().setUp()
        self.trial = self.experiment()
        self.urls = {
            'list': ('get', reverse('experiments:experiment_list')),
            'detail': ('get', reverse('experiments:experiment_detail', args=[self.trial.pk])),
            'create': ('get', reverse('experiments:experiment_create')),
            'edit': ('get', reverse('experiments:experiment_edit', args=[self.trial.pk])),
            'delete': ('get', reverse('experiments:experiment_delete', args=[self.trial.pk])),
            'create post': ('post', reverse('experiments:experiment_create')),
            'edit post': ('post', reverse('experiments:experiment_edit', args=[self.trial.pk])),
            'team post': ('post', reverse('experiments:experiment_team', args=[self.trial.pk])),
            'delete post': ('confirmed', reverse('experiments:experiment_delete', args=[self.trial.pk])),
        }

    def statuses(self, user):
        self.client.force_login(user) if user else self.client.logout()
        return {name: (delete_confirmed(self.client, url) if method == 'confirmed' else
                       getattr(self.client, method)(url)).status_code for name, (method, url) in self.urls.items()}

    def test_what_each_role_may_do_on_each_page(self):
        read = {'list': 200, 'detail': 200}
        denied = {name: 403 for name in self.urls if name not in read}
        self.assertEqual(self.statuses(person('advisor', *READER)), {**read, **denied})
        self.assertEqual(self.statuses(person('technician', *READER)), {**read, **denied})
        student = self.statuses(person('student', *STUDENT))
        self.assertEqual({name: student[name] for name in ('list', 'detail', 'create', 'edit', 'create post',
                                                           'edit post')},
                         {'list': 200, 'detail': 200, 'create': 200, 'edit': 200, 'create post': 200,
                          'edit post': 200})
        self.assertEqual((student['delete'], student['delete post']), (403, 403))
        self.assertEqual(student['team post'], 403)          # the team is its lead's alone (review F3)
        researcher = self.statuses(person('researcher', *RESEARCHER))
        self.assertEqual({researcher[name] for name in ('list', 'detail', 'create', 'edit', 'delete')}, {200})
        self.assertEqual((researcher['team post'], researcher['delete post']), (403, 302))    # the team: its lead's
        self.assertTrue(Experiment.all_objects.filter(pk=self.trial.pk, is_deleted=True).exists())

    def test_signed_out_everything_asks_to_sign_in(self):
        self.assertEqual(set(self.statuses(None).values()), {302})

    def test_a_person_without_the_area_sees_neither_the_menu_entry_nor_the_pages(self):
        outsider = person('outsider', 'view_site')
        self.assertEqual(set(self.statuses(outsider).values()), {403})
        page = self.client.get(reverse('farm:site_list'))
        self.assertNotContains(page, reverse('experiments:experiment_list'))


class MenuAndAccessTests(PageTestCase):
    def test_the_menu_places_experiments_under_research_and_the_role_matrix_offers_the_area(self):
        place = navigation.place('experiments.view_experiment')
        self.assertEqual((str(place.entry.label), str(place.group.label), place.entry.icon),
                         ('Experiments', '', 'flask'))
        self.assertEqual(str(place.path), 'Production · Research')
        areas = {area.model: area for area in access.areas()}
        self.assertEqual(str(areas['experiments.Experiment'].label), 'Experiments')
        self.assertEqual(areas['experiments.Experiment'].actions, ('view', 'add', 'change', 'delete', 'oversee'))
        page = self.client.get(reverse('experiments:experiment_list'))
        self.assertEqual(page.context['workspace']['key'], 'production')
        current = [entry['label'] for section in page.context['rail_sections'] for group in section['groups']
                   for entry in group['entries'] if entry['current']]
        self.assertEqual([str(label) for label in current], ['Experiments'])

    def test_the_viewer_shows_the_tables_in_research_with_their_constraints_and_descriptions(self):
        sections = dict(database.sections())
        tables = {table.name: table for table in sections['Research']}
        self.assertEqual(set(tables), {'experiments', 'experiment_factors', 'experiment_levels', 'experiment_groups',
                                       'experiment_group_levels', 'experiment_replicates',
                                       'experiment_replicate_units', 'experiment_members', 'experiment_shares',
                                       'experiment_replicate_systems'})
        self.assertTrue(all(table.description for table in tables.values()))
        self.assertTrue(tables['experiments'].description.startswith('A trial of one species on one site'))
        constraints = {c.name for c in tables['experiment_replicate_units'].structure().constraints}
        self.assertTrue({'excl_replicate_units_unit', 'chk_experiment_placements_period'} <= constraints)
        constraints = {c.name for c in tables['experiment_group_levels'].structure().constraints}
        self.assertTrue({'fk_experiment_group_levels_group', 'fk_experiment_group_levels_factor',
                         'fk_experiment_group_levels_level'} <= constraints)

    def test_the_admin_lists_experiments_and_restores_only_the_experiment(self):
        from django.contrib import admin
        root = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(root)
        trial = self.experiment()
        trial.soft_delete(root)
        self.assertEqual(self.client.get(reverse('admin:experiments_experiment_changelist')).status_code, 200)
        registered = {model.__name__: model_admin for model, model_admin in admin.site._registry.items()
                      if model._meta.app_label == 'experiments'}
        self.assertEqual(set(registered), {'Experiment', 'Factor', 'Level', 'ExperimentGroup', 'Replicate',
                                           'ReplicateUnit', 'ReplicateSystem'})
        self.assertEqual(registered['Experiment'].actions, ['restore'])
        self.assertTrue(all(model_admin.actions == [] for name, model_admin in registered.items()
                            if name != 'Experiment'))


class LanguageTests(PageTestCase):
    def test_the_pages_speak_each_language(self):
        self.create()
        trial = Experiment.objects.get()
        for language, words in {'tr': ('Deneyler', 'Şablonlar', 'Yürütücü', 'Hipotez'),
                                'nb': ('Forsøk', 'Maler', 'Leder', 'Hypotese')}.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            for url in (reverse('experiments:experiment_list'), reverse('experiments:experiment_edit', args=[trial.pk]),
                        reverse('experiments:experiment_detail', args=[trial.pk]),
                        reverse('experiments:experiment_create')):
                page = self.client.get(url)
                self.assertEqual(page.status_code, 200, url)
                self.assertNotIn('%(', page.content.decode())
            self.assertContains(self.client.get(reverse('experiments:experiment_list')), words[0], msg_prefix=language)
            edit = self.client.get(reverse('experiments:experiment_edit', args=[trial.pk]))
            for word in words[2:]:
                self.assertContains(edit, word, msg_prefix=language)
        self.assertContains(self.client.get(reverse('experiments:experiment_list'), {'view': 'templates'}), 'Maler')

    def test_the_log_is_english_at_rest_whatever_the_language_of_the_change(self):
        Profile.objects.update_or_create(user=self.user, defaults={'language': 'tr'})
        self.create()
        created, team = AuditLog.objects.order_by('created_at')
        self.assertEqual(created.entity_type, 'experiment')
        self.assertEqual(created.changes['Primary endpoint'], [None, {'msgid': 'Biological FCR'}])
        self.assertEqual(team.changes, {'Team': [None, 'ali (Lead)']})
        self.assertIn('Biyolojik FCR', self.client.get(reverse('core:activity_log')).content.decode())

