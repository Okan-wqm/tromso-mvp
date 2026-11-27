"""Deleting a record follows the on_delete of the links that point at it (core.softdelete)."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import models
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog
from core.softdelete import execute, plan_delete, restore

from ..models import ProductionDepartment, Site, System
from .helpers import role
from core.testing import delete_confirmed

DEPARTMENT_SITE_LINK = ProductionDepartment._meta.get_field('site').remote_field


class DeletePlanTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        self.user.groups.add(role('Manager', 'view_site', 'delete_site', 'view_productiondepartment', 'view_auditlog'))
        self.client.force_login(self.user)
        self.site = Site.objects.create(name='Bergen', code='BG')
        self.hall_a = ProductionDepartment.objects.create(site=self.site, name='Hall A', code='HA')
        self.hall_b = ProductionDepartment.objects.create(site=self.site, name='Hall B', code='HB')
        self.url = reverse('farm:site_delete', args=[self.site.pk])

    def log(self):
        return list(AuditLog.objects.order_by('created_at').values_list('action', 'entity_type', 'entity_label'))


class SetNullTests(DeletePlanTestCase):
    """System.production_department is SET_NULL: a deleted department's systems stay, serving the whole site."""

    def setUp(self):
        super().setUp()
        self.user.groups.add(role('Departments', 'delete_productiondepartment'))
        self.ras = System.objects.create(site=self.site, production_department=self.hall_a, name='RAS 1', code='R1')
        self.loop = System.objects.create(site=self.site, production_department=self.hall_a, name='Loop', code='LP')
        self.url = reverse('farm:productiondepartment_delete', args=[self.hall_a.pk])

    def test_plan_lists_the_systems_that_lose_their_department(self):
        plan = plan_delete(self.hall_a)
        self.assertTrue(plan.can_delete)
        self.assertEqual(plan.cascade, [])
        (group,) = plan.detached_groups()
        self.assertEqual((group['label'], group['link'], set(group['records'])),
                         ('Systems', 'production department', {self.ras, self.loop}))

    def test_the_confirmation_shows_what_will_happen(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Systems that lose their production department')
        self.assertContains(response, 'RAS 1 (R1)')
        self.assertNotContains(response, 'deleted with it')
        self.assertNotContains(response, 'disabled')

    def test_delete_detaches_every_system_and_logs_each_record(self):
        self.client.post(self.url)
        self.assertFalse(ProductionDepartment.objects.filter(pk=self.hall_a.pk).exists())
        for system in (self.ras, self.loop):
            system.refresh_from_db()
            self.assertIsNone(system.production_department)
            self.assertEqual((system.version, system.updated_by, system.is_deleted), (2, self.user, False))
        self.assertEqual(sorted(self.log()), [
            ('delete', 'production department', 'Hall A (HA)'),
            ('update', 'system', 'Loop (LP)'),
            ('update', 'system', 'RAS 1 (R1)'),
        ])
        entry = AuditLog.objects.get(entity_label='RAS 1 (R1)')
        self.assertEqual(entry.changes, {'Production department': ['Hall A (HA)', None]})

    def test_a_record_nothing_points_at_deletes_plainly(self):
        delete_confirmed(self.client, reverse('farm:productiondepartment_delete', args=[self.hall_b.pk]))
        self.assertEqual(self.log(), [('delete', 'production department', 'Hall B (HB)')])


class CascadeTests(DeletePlanTestCase):
    """A CASCADE link takes the records that point at it down with it: a site's production departments (F-212)."""

    def test_plan_and_confirmation_list_the_records_deleted_with_it(self):
        plan = plan_delete(self.site)
        self.assertEqual(plan.detach, [])
        (group,) = plan.deleted_groups()
        self.assertEqual((group['label'], set(group['records'])), ('Production departments', {self.hall_a, self.hall_b}))
        self.assertContains(self.client.get(self.url), 'Production departments deleted with it')

    def test_delete_soft_deletes_the_whole_tree_and_logs_each_record(self):
        self.client.post(self.url)
        self.assertFalse(Site.objects.exists())
        self.assertFalse(ProductionDepartment.objects.exists())
        self.assertEqual({d.is_deleted for d in ProductionDepartment.all_objects.all()}, {True})
        log = self.log()
        self.assertEqual(sorted(log), [
            ('delete', 'production department', 'Hall A (HA)'),
            ('delete', 'production department', 'Hall B (HB)'),
            ('delete', 'site', 'Bergen (BG)'),
        ])
        self.assertEqual(log[-1], ('delete', 'site', 'Bergen (BG)'))   # the children go first


class ProtectTests(DeletePlanTestCase):
    """A PROTECT link, or a model's own condition, blocks the delete until it is dealt with."""

    def test_a_protecting_link_blocks_the_delete(self):
        with mock.patch.object(DEPARTMENT_SITE_LINK, 'on_delete', models.PROTECT):
            self.assertEqual(plan_delete(self.site).blockers, ['2 production departments still belong to it.'])
            self.assertContains(self.client.get(self.url), 'cannot be deleted yet')
            self.assertContains(self.client.get(self.url), 'disabled')
            response = self.client.post(self.url, follow=True)
        self.assertContains(response, 'cannot be deleted: 2 production departments still belong to it.')
        self.assertTrue(Site.objects.exists())
        self.assertEqual(self.log(), [])

    def test_a_single_blocker_is_worded_in_the_singular(self):
        self.hall_b.soft_delete(self.user)
        with mock.patch.object(DEPARTMENT_SITE_LINK, 'on_delete', models.PROTECT):
            self.assertEqual(plan_delete(self.site).blockers, ['1 production department still belongs to it.'])

    def test_a_model_can_block_with_its_own_condition(self):
        with mock.patch.object(Site, 'delete_blockers', return_value=['Fish are still in tank 3.']):
            self.client.post(self.url)
            self.assertTrue(Site.objects.exists())
            self.assertContains(self.client.get(self.url), 'Fish are still in tank 3.')

    def test_only_live_records_count(self):
        self.hall_a.soft_delete(self.user)
        self.hall_b.soft_delete(self.user)
        with mock.patch.object(DEPARTMENT_SITE_LINK, 'on_delete', models.PROTECT):
            self.assertTrue(plan_delete(self.site).can_delete)


class StalePlanTests(DeletePlanTestCase):
    """The plan is read before the delete runs; what changed meanwhile wins (cross review F2): the delete locks the
    records it takes along and takes only those still under what it deletes and still live."""

    def setUp(self):
        super().setUp()
        self.ras = System.objects.create(site=self.site, name='RAS 1', code='R1')
        self.loop = System.objects.create(site=self.site, name='Loop', code='LP', parent=self.ras)
        self.other = System.objects.create(site=self.site, name='RAS 2', code='R2')

    def test_a_child_moved_meanwhile_stays_live_under_its_new_parent(self):
        plan = plan_delete(self.ras)
        System.objects.filter(pk=self.loop.pk).update(parent=self.other)
        execute(plan, self.user)
        self.assertFalse(System.all_objects.get(pk=self.loop.pk).is_deleted)
        self.assertTrue(System.all_objects.get(pk=self.ras.pk).is_deleted)

    def test_a_child_deleted_on_its_own_meanwhile_keeps_its_own_moment(self):
        plan = plan_delete(self.ras)
        self.loop.soft_delete(self.user)
        own = System.all_objects.get(pk=self.loop.pk).deleted_at
        execute(plan, self.user)
        self.assertEqual(System.all_objects.get(pk=self.loop.pk).deleted_at, own)
        restore(System.all_objects.get(pk=self.ras.pk), self.user)
        self.assertTrue(System.all_objects.get(pk=self.loop.pk).is_deleted)

    def test_the_records_it_takes_along_are_locked(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as queries:
            execute(plan_delete(self.ras), self.user)
        self.assertTrue(any('"systems"' in query['sql'] and 'FOR UPDATE' in query['sql']
                            for query in queries.captured_queries))
