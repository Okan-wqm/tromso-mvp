"""Deleting a record follows the on_delete of the links that point at it (core.softdelete)."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import models
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog
from core.softdelete import plan_delete

from ..models import ProductionDepartment, Site
from .helpers import role

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
    """ProductionDepartment.site is SET_NULL, as in the source: the departments stay, without a site."""

    def test_plan_lists_the_departments_that_lose_their_site(self):
        plan = plan_delete(self.site)
        self.assertTrue(plan.can_delete)
        self.assertEqual(plan.cascade, [])
        (group,) = plan.detached_groups()
        self.assertEqual((group['label'], group['link'], set(group['records'])),
                         ('Production departments', 'site', {self.hall_a, self.hall_b}))

    def test_the_confirmation_shows_what_will_happen(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Production departments that lose their site')
        self.assertContains(response, 'Hall A (HA)')
        self.assertNotContains(response, 'deleted with it')
        self.assertNotContains(response, 'disabled')

    def test_delete_detaches_every_department_and_logs_each_record(self):
        self.client.post(self.url)
        self.assertFalse(Site.objects.exists())
        for hall in (self.hall_a, self.hall_b):
            hall.refresh_from_db()
            self.assertIsNone(hall.site)
            self.assertEqual((hall.version, hall.updated_by, hall.is_deleted), (2, self.user, False))
        self.assertEqual(sorted(self.log()), [
            ('delete', 'site', 'Bergen (BG)'),
            ('update', 'production department', 'Hall A (HA)'),
            ('update', 'production department', 'Hall B (HB)'),
        ])
        entry = AuditLog.objects.get(entity_label='Hall A (HA)')
        self.assertEqual(entry.changes, {'Site': ['Bergen (BG)', None]})

    def test_a_site_without_departments_deletes_plainly(self):
        ProductionDepartment.objects.all().delete()
        self.client.post(self.url)
        self.assertEqual(self.log(), [('delete', 'site', 'Bergen (BG)')])


class CascadeTests(DeletePlanTestCase):
    """A CASCADE link takes the records that point at it down with it."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(DEPARTMENT_SITE_LINK, 'on_delete', models.CASCADE)
        patcher.start()
        self.addCleanup(patcher.stop)

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
