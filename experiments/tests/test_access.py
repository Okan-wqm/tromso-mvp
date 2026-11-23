"""Who reads a sealed experiment, the positive controls and the mirror of the route walk: the team reads all of it, a
grantee exactly the parts of their live shares (and what those bring with them), an open experiment everyone who reads
experiments, a superuser all of it with each read logged as support; the lead alone shares, revokes and changes the
audience, each logged once; a revoked or expired grant reads nothing; the delete plan counts what the person may not
see without naming it."""
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core import sealing
from core.models import AccessEvent, AuditLog

from .. import services
from ..models import Experiment, ExperimentShare, Factor, Member, ReplicateUnit
from . import world


class AccessCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        world.build_open(cls)
        world.build_sealed(cls)

    def detail(self, user, tab=''):
        self.client.force_login(user)
        return self.client.get(reverse('experiments:experiment_detail', args=[self.experiment.pk])
                               + (f'?tab={tab}' if tab else ''))

    def give(self, part, **fields):
        values = {'experiment': self.experiment, 'user': self.researcher, 'part': part, 'reason': 'Review',
                  'valid_until': timezone.now() + timedelta(days=10), **fields}
        return ExperimentShare.objects.create(**values)

    def seen(self, user, model, **lookup):
        with sealing.as_viewer(user):
            return set(model.objects.filter(**lookup).values_list('pk', flat=True))


class TeamTests(AccessCase):
    def test_the_team_reads_everything_of_it(self):
        response = self.detail(self.lead)
        self.assertContains(response, 'XQZ diet trial')
        self.assertContains(self.detail(self.lead, 'data'), 'XQZ-1')
        self.assertEqual(self.seen(self.lead, Factor), {self.factor.pk})
        self.assertEqual(self.seen(self.lead, ReplicateUnit), {row.pk for row in self.placements})

    def test_an_outsider_reads_nothing_of_it(self):
        self.assertEqual(self.detail(self.researcher).status_code, 404)
        self.assertEqual(self.seen(self.researcher, Experiment), set())
        self.assertEqual(self.seen(self.researcher, Factor), set())

    def test_a_member_whose_window_ended_is_an_outsider(self):
        Member.objects.create(experiment=self.experiment, user=self.student, role='student',
                              valid_until=timezone.now() - timedelta(minutes=1),
                              valid_from=timezone.now() - timedelta(days=3))
        self.assertEqual(self.detail(self.student).status_code, 404)

    def test_an_open_experiment_is_read_by_everyone_who_reads_experiments(self):
        Experiment.objects.filter(pk=self.experiment.pk).update(audience='open')
        self.assertContains(self.detail(self.researcher), 'XQZ diet trial')
        self.assertEqual(self.detail(self.hr).status_code, 403)


class ShareTests(AccessCase):
    def test_a_water_grantee_reads_the_shell_and_the_water_never_the_design_or_results(self):
        self.give('water')
        response = self.detail(self.researcher)
        self.assertContains(response, 'XQZ diet trial')
        self.assertNotContains(response, 'XQZ more protein')                  # the hypothesis is design
        self.assertEqual(self.detail(self.researcher, 'overview').status_code, 200)
        self.assertNotContains(self.detail(self.researcher, 'overview'), 'XQZ group')
        self.assertEqual(self.seen(self.researcher, Factor), set())
        self.assertEqual(self.seen(self.researcher, ReplicateUnit), {row.pk for row in self.placements})

    def test_results_bring_the_design_and_the_systems(self):
        self.give('results')
        self.assertEqual(self.seen(self.researcher, Factor), {self.factor.pk})
        self.assertContains(self.detail(self.researcher, 'overview'), 'XQZ group')

    def test_a_share_to_a_role_reaches_its_holders(self):
        role = self.researcher.groups.first()
        self.give('design', user=None, group=role)
        self.assertEqual(self.seen(self.researcher, Factor), {self.factor.pk})

    def test_a_revoked_or_expired_share_reads_nothing(self):
        share = self.give('design')
        ExperimentShare.objects.filter(pk=share.pk).update(revoked_at=timezone.now(), revoked_by=self.lead)
        self.assertEqual(self.detail(self.researcher).status_code, 404)
        self.give('design', valid_from=timezone.now() - timedelta(days=3), valid_until=timezone.now() - timedelta(days=1))
        self.assertEqual(self.detail(self.researcher).status_code, 404)

    def test_a_grantee_never_edits(self):
        self.give('results')
        self.client.force_login(self.researcher)
        response = self.client.get(reverse('experiments:experiment_edit', args=[self.experiment.pk]))
        self.assertEqual(response.status_code, 403)


class LeadOnlyTests(AccessCase):
    def test_the_lead_shares_and_revokes_each_logged_once(self):
        until = timezone.now() + timedelta(days=5)
        shares = services.share(self.lead, self.experiment, self.researcher, ['water', 'design'], until, 'Audit')
        self.assertEqual(sorted(share.part for share in shares), ['design', 'water'])
        services.revoke(self.lead, shares[0])
        shares[0].refresh_from_db()
        self.assertEqual(shares[0].revoked_by, self.lead)
        entries = AuditLog.objects.filter(entity_id=str(self.experiment.pk)).order_by('created_at')
        self.assertEqual([list(entry.changes) for entry in entries], [['Shares'], ['Shares']])

    def test_no_one_but_the_lead_shares_or_changes_the_audience(self):
        until = timezone.now() + timedelta(days=5)
        with self.assertRaises(PermissionDenied):
            services.share(self.researcher, self.experiment, self.student, ['water'], until, 'Audit')
        with self.assertRaises(PermissionDenied):
            services.set_audience(self.researcher, self.experiment, 'open')
        services.set_audience(self.lead, self.experiment, 'open')
        self.experiment.refresh_from_db()
        self.assertEqual(self.experiment.audience, 'open')

    def test_a_share_needs_a_reason_and_an_end(self):
        with self.assertRaises(ValidationError):
            services.share(self.lead, self.experiment, self.researcher, ['water'], timezone.now() + timedelta(days=5), '')

    def test_the_lead_shares_from_the_sharing_tab(self):
        self.client.force_login(self.lead)
        url = reverse('experiments:experiment_sharing', args=[self.experiment.pk])
        self.assertContains(self.client.get(url), 'Sharing')
        response = self.client.post(url, {'person': str(self.researcher.pk), 'parts': ['water'],
                                          'until': (timezone.localdate() + timedelta(days=5)).isoformat(),
                                          'reason': 'Water audit'})
        self.assertEqual(response.status_code, 302)
        share = ExperimentShare.objects.get()
        self.assertEqual((share.user, share.part, share.reason, share.created_by),
                         (self.researcher, 'water', 'Water audit', self.lead))
        self.client.force_login(self.researcher)
        self.assertEqual(self.client.get(url).status_code, 403)


class SupportTests(AccessCase):
    def test_a_superuser_reads_it_and_each_read_is_logged_as_support_for_the_lead(self):
        self.assertContains(self.detail(self.boss), 'XQZ diet trial')
        event = AccessEvent.objects.get()
        self.assertEqual((event.kind, event.user_name, event.entity_type, event.entity_id),
                         ('support', 'root', 'experiment', str(self.experiment.pk)))
        self.client.force_login(self.lead)
        response = self.client.get(reverse('experiments:experiment_detail', args=[self.experiment.pk]) + '?tab=looked')
        self.assertContains(response, 'root')


class PrivateTests(AccessCase):
    """Owner amendment C4: the lead may keep the experiment from the platform admin too."""

    def setUp(self):
        Experiment.objects.filter(pk=self.experiment.pk).update(audience='private')
        self.experiment.refresh_from_db()

    def test_the_platform_admin_reads_nothing_of_a_private_experiment(self):
        from farm.models import FeedingRecord, Tank
        self.assertEqual(self.detail(self.boss).status_code, 404)
        self.assertEqual(self.seen(self.boss, Experiment), set())
        self.assertEqual(self.seen(self.boss, Factor), set())
        self.assertEqual(self.seen(self.boss, ReplicateUnit), set())
        self.assertFalse(self.seen(self.boss, Tank) & {tank.pk for tank in self.sealed_tanks})
        self.assertNotIn(self.feeding.pk, self.seen(self.boss, FeedingRecord))
        self.assertIn(self.open_tank.pk, self.seen(self.boss, Tank))
        self.assertFalse(AccessEvent.objects.exists())

    def test_nor_in_the_database_viewer(self):
        self.client.force_login(self.boss)
        for table in ('experiments', 'experiment_factors', 'tanks', 'systems', 'feeding_records'):
            with self.subTest(table=table):
                response = self.client.get(reverse('core:database_table', args=[table]))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'XQZ')

    def test_the_platform_admin_still_sees_that_its_tanks_are_booked_and_when(self):
        from .. import read
        with sealing.as_viewer(self.boss):
            days = read.booked([tank.pk for tank in self.sealed_tanks], self.today, self.today)
        self.assertEqual(set(days), {tank.pk for tank in self.sealed_tanks})

    def test_its_team_and_its_grantees_still_read_it(self):
        self.assertContains(self.detail(self.lead), 'XQZ diet trial')
        self.give('design')
        self.assertContains(self.detail(self.researcher), 'XQZ diet trial')

    def test_the_lead_sets_it_on_the_sharing_page_logged_once(self):
        Experiment.objects.filter(pk=self.experiment.pk).update(audience='sealed')
        self.client.force_login(self.lead)
        url = reverse('experiments:experiment_sharing', args=[self.experiment.pk])
        self.assertContains(self.client.get(url), 'not the platform admin')
        self.assertEqual(self.client.post(url, {'audience': 'private'}).status_code, 302)
        self.experiment.refresh_from_db()
        self.assertEqual(self.experiment.audience, 'private')
        entry = AuditLog.objects.get(entity_id=str(self.experiment.pk))
        self.assertEqual(list(entry.changes), ['Who may read it'])
        self.client.force_login(self.boss)
        self.assertEqual(self.client.get(url).status_code, 404)


class LegalFigureTests(AccessCase):
    """A figure the law or the fish depend on counts every unit, whoever asks (core.sealing.system): the medicine
    withdrawal holds the fish of a sealed tank for a person who may not see it as for the system."""

    def test_a_withdrawal_holds_the_sealed_fish_whoever_asks(self):
        from farm.health import withdrawal
        with sealing.system('the test'):
            expected = withdrawal.snapshot([self.sealed_batch.pk], self.today).held
        with sealing.as_viewer(self.researcher):
            seen = withdrawal.snapshot([self.sealed_batch.pk], self.today).held
        self.assertTrue(expected)
        self.assertEqual(seen, expected)


class DeletePlanTests(AccessCase):
    def test_the_plan_counts_what_the_person_may_not_see_without_naming_it(self):
        from core.softdelete import plan_delete
        with sealing.as_viewer(self.staff):
            plan = plan_delete(self.hall)
        self.assertGreater(plan.restricted, 0)
        self.assertNotIn('XQZ', ' '.join(str(record) for record in plan.cascade + [r for r, _l in plan.detach]))
