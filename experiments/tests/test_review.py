"""The independent security review of the confidentiality branch (F:\\dev\\balik-notes\\exp-access\\REVIEW.md), each
finding as a test: what the review found must stay closed.

F2 the database viewer's every table, a private experiment included; F3 the team is the lead's; F4 the unresolved old
courses as the person may see them; F5 the store's feed book the same for everyone; F6 a sealed tank's notifiable
disease still owed; F7 Oversee keeps the fish of a private experiment, never its science; F8 every read of the platform
admin logged, the change token, a results share, the search, the alarms and their fallback, the delete plan's words;
the lead's on-call number on the Oversee card."""
from datetime import timedelta
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core import audit, database, sealing
from core.models import AccessEvent, AuditLog
from core.softdelete import plan_delete
from farm import withdrawal_gate
from farm.models import FeedingRecord, HealthEvent, Site, Tank, Treatment

from farm.tests.helpers import role, rows_data

from .. import read, services
from ..models import Experiment, ExperimentShare, Factor, Member
from . import world
from .test_pages import RESEARCHER


class ReviewCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        world.build_open(cls)
        world.build_sealed(cls)
        cls.keeper = world.person('keeper', *world.area_perms(exclude_apps=('reports',)), 'experiments.oversee_experiment')

    def seen(self, user, model, **lookup):
        with sealing.as_viewer(user):
            return set(model.objects.filter(**lookup).values_list('pk', flat=True))

    def private(self):
        Experiment.objects.filter(pk=self.experiment.pk).update(audience='private')

    def events(self, **lookup):
        return AccessEvent.objects.filter(entity_type='experiment', entity_id=str(self.experiment.pk), **lookup)


class DatabaseViewerTests(ReviewCase):
    def test_no_table_shows_a_private_experiment_to_the_platform_admin(self):
        self.private()
        AuditLog.objects.create(user=self.lead, user_name='lead', action='update', entity_type='experiment',
                                entity_id=str(self.experiment.pk), entity_label='XQZ diet trial', changes={})
        self.client.force_login(self.boss)
        for _label, tables in database.sections():
            for table in tables:
                with self.subTest(table=table.name):
                    response = self.client.get(reverse('core:database_table', args=[table.name]))
                    self.assertEqual(response.status_code, 200)
                    self.assertNotContains(response, 'XQZ')
                    self.assertNotContains(response, str(self.experiment.pk))


class TeamTests(ReviewCase):
    def post(self, user, rows):
        self.client.force_login(user)
        return self.client.post(reverse('experiments:experiment_team', args=[self.experiment.pk]),
                                rows_data('team', rows, record=self.experiment))

    def test_only_the_lead_changes_the_team(self):
        Member.objects.create(experiment=self.experiment, user=self.researcher, role='researcher')
        rows = [{'user': self.researcher.pk, 'role': 'lead'}]
        self.assertEqual(self.post(self.researcher, rows).status_code, 403)
        self.assertEqual(Member.objects.get(experiment=self.experiment, role='lead').user, self.lead)
        self.assertEqual(self.post(self.lead, [{'user': self.lead.pk, 'role': 'lead'}]).status_code, 302)

    def test_the_platform_admin_takes_over_a_leadless_experiment_logged(self):
        with self.assertRaises(CommandError):                       # it has a lead
            call_command('experiments_take_lead', self.experiment.code, '--as', 'root', '--reason', 'Lead left',
                         stdout=StringIO())
        Member.objects.filter(experiment=self.experiment).delete()
        with self.assertRaises(CommandError):                       # not the platform admin
            call_command('experiments_take_lead', self.experiment.code, '--as', 'researcher', '--reason', 'x',
                         stdout=StringIO())
        call_command('experiments_take_lead', self.experiment.code, '--as', 'root', '--reason', 'Lead left',
                     stdout=StringIO())
        self.assertEqual(Member.objects.get(experiment=self.experiment, role='lead').user, self.boss)
        entry = AuditLog.objects.filter(entity_id=str(self.experiment.pk)).latest('created_at')
        self.assertIn('taken over: Lead left', entry.changes['Team'][1])


class WithdrawalTests(ReviewCase):
    def test_the_unresolved_old_courses_are_the_persons_to_see(self):
        from core.models import PlatformSettings
        from farm.health import withdrawal
        with withdrawal_gate.opened('test fixture: an old course without a rule'):
            PlatformSettings.objects.update(unknown_withdrawal_days=1)
            Treatment.objects.filter(pk=self.treatment.pk).update(start_date=self.today - timedelta(days=12),
                                                                    end_date=self.today - timedelta(days=10))
        with sealing.system('the test'):
            everything = {batch.pk for batch, _held in withdrawal.unresolved()}
        self.assertIn(self.sealed_batch.pk, everything)
        with sealing.as_viewer(self.researcher):
            shown = [withdrawal.unresolved_text(batch, held) for batch, held in withdrawal.unresolved()]
        self.assertNotIn('XQZ', ' '.join(shown))


class StoreTests(ReviewCase):
    def test_the_feed_book_is_the_same_for_everyone(self):
        from inventory import read as store
        books = {}
        for user in (self.boss, self.lead, self.researcher, self.hr):
            with sealing.as_viewer(user):
                books[user.username] = store._feeding([self.feed.pk])
        self.assertEqual(sum(books['root'][self.feed.pk].values()), 4)          # the open 2.5 kg and X's 1.5 kg
        self.assertTrue(all(book == books['root'] for book in books.values()))


class DueListTests(ReviewCase):
    def test_a_sealed_tanks_notifiable_disease_is_owed_whoever_looks(self):
        from farm.health import diseases
        from reports import due
        Site.objects.filter(pk=self.site.pk).update(reports_from=self.today - timedelta(days=30))
        HealthEvent.objects.filter(pk=self.event.pk).update(diagnosis=diseases.NOTIFIABLE[0])
        with sealing.as_viewer(self.researcher):
            rows = due.due().rows
        self.assertIn(self.event.pk, {row.event.pk for row in rows if row.event is not None})


class OverseeTests(ReviewCase):
    def test_oversee_keeps_the_fish_of_a_private_experiment_never_its_science(self):
        self.private()
        self.assertTrue({tank.pk for tank in self.sealed_tanks} <= self.seen(self.keeper, Tank))
        self.assertIn(self.feeding.pk, self.seen(self.keeper, FeedingRecord))
        self.assertEqual(self.seen(self.keeper, Factor), set())
        self.assertEqual(self.seen(self.keeper, Experiment), set())

    def test_the_sharing_page_says_the_exception(self):
        self.client.force_login(self.lead)
        response = self.client.get(reverse('experiments:experiment_sharing', args=[self.experiment.pk]))
        self.assertContains(response, 'the people whose role holds Oversee')

    def test_the_card_has_the_leads_on_call_number_and_is_logged_against_the_experiment(self):
        Experiment.objects.filter(pk=self.experiment.pk).update(on_call_phone='+47 400 00 000')
        with sealing.as_viewer(self.keeper):
            chip = read.chips(self.sealed_tanks, self.keeper)[self.sealed_tanks[0].pk][0]
        self.assertIn('+47 400 00 000', chip.title)
        self.assertTrue(self.events(kind='oversee', user_name='keeper').exists())


class SupportReadTests(ReviewCase):
    def test_every_read_of_the_platform_admin_is_logged(self):
        AuditLog.objects.create(user=self.lead, user_name='lead', action='update', entity_type='experiment',
                                entity_id=str(self.experiment.pk), entity_label='XQZ diet trial', changes={})
        self.client.force_login(self.boss)
        for url in (reverse('experiments:experiment_list'), reverse('core:activity_log'),
                    reverse('core:database_table', args=['experiments']),
                    reverse('admin:experiments_experiment_changelist'),
                    reverse('admin:experiments_experiment_change', args=[self.experiment.pk])):
            with self.subTest(url=url):
                before = self.events(kind='support').count()
                self.assertEqual(self.client.get(url).status_code, 200)
                self.assertGreater(self.events(kind='support').count(), before)


class TokenTests(ReviewCase):
    def test_a_write_the_person_may_not_see_never_moves_their_token(self):
        with sealing.as_viewer(self.researcher):
            before = audit.revision()
        with sealing.as_viewer(self.lead):
            lead_before = audit.revision()
        audit.record(self.lead, AuditLog.Action.UPDATE, self.experiment, {'Notes': ['a', 'b']})
        with sealing.as_viewer(self.researcher):
            self.assertEqual(audit.revision(), before)
        with sealing.as_viewer(self.lead):
            self.assertNotEqual(audit.revision(), lead_before)


class ShareTests(ReviewCase):
    def give(self, part):
        return ExperimentShare.objects.create(experiment=self.experiment, user=self.researcher, part=part,
                                              reason='Review', valid_until=timezone.now() + timedelta(days=5))

    def test_a_results_share_reads_the_figures_the_team_reads(self):
        self.give('results')
        with sealing.as_viewer(self.lead):
            team = repr(read.overview(self.experiment, self.today))
        with sealing.as_viewer(self.researcher):
            grantee = repr(read.overview(self.experiment, self.today))
        self.assertEqual(team, grantee)

    def test_the_search_finds_by_the_hypothesis_only_who_may_read_the_design(self):
        self.give('water')
        self.client.force_login(self.researcher)
        url = reverse('experiments:experiment_list')
        self.assertContains(self.client.get(url, {'q': 'XQZ diet'}), 'XQZ diet trial')
        self.assertNotContains(self.client.get(url, {'q': 'more protein'}), 'XQZ diet trial')
        self.give('design')
        self.assertContains(self.client.get(url, {'q': 'more protein'}), 'XQZ diet trial')


class AlarmTests(ReviewCase):
    def rule(self, **fields):
        from alarms.models import RecipientRule
        return RecipientRule.objects.create(level=0, created_by=self.boss, **fields)

    def recipients(self):
        from alarms import routing
        router = routing.Router(timezone.now())
        router.prepare([self.alarm])
        return {user.username: rule for user, rule in router.recipients(self.alarm, 0)}

    def test_a_sealed_cells_alarm_reaches_only_who_may_see_it(self):
        self.rule(user=self.researcher)
        self.rule(user=self.lead)
        self.assertEqual(set(self.recipients()), {'lead'})

    def test_with_nobody_on_the_rules_who_may_see_it_the_keepers_are_told(self):
        self.rule(user=self.researcher)
        found = self.recipients()
        self.assertEqual(set(found), {'lead', 'keeper'})
        self.assertTrue(all(rule is None for rule in found.values()))


class DeletePlanTests(ReviewCase):
    def test_the_plan_never_says_how_many_records_the_person_may_not_see(self):
        with sealing.as_viewer(self.staff):
            plan = plan_delete(self.hall)
        self.assertFalse(plan.can_delete)
        restricted = [str(blocker) for blocker in plan.blockers if 'may not see' in str(blocker)]
        self.assertEqual(len(restricted), 1)
        self.assertFalse(any(character.isdigit() for character in restricted[0]))


class ResearcherRoleTests(ReviewCase):
    def test_a_member_with_change_rights_is_not_the_lead(self):
        member = world.person('member', *[f'experiments.{code}' for code in RESEARCHER if 'experiment' in code])
        member.groups.add(role('Extra', 'view_experiment'))
        Member.objects.create(experiment=self.experiment, user=member, role='researcher')
        self.client.force_login(member)
        response = self.client.post(reverse('experiments:experiment_team', args=[self.experiment.pk]),
                                    rows_data('team', [{'user': member.pk, 'role': 'lead'}], record=self.experiment))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(services.is_lead(self.lead, self.experiment))
