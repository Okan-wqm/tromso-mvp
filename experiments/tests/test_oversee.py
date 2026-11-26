"""Oversee: the role matrix's column, offered by the Experiments area, that lets a person keep the fish of a sealed cell
alive (its stock, feeding, water, health, lice, tasks and alarms as farm facts) without ever reading the experiment's
design, results or team; the experiment is a card (a research trial, its lead, its approval, its days). The
platform admin gives and withholds it (owner amendment C1): the role form says which duties it may touch, as
information, never a block. The mirror of the route walk: missing a welfare fact fails as hard as a leak."""
from datetime import timedelta

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from core import access, sealing
from farm.models import FeedingRecord, HealthEvent, LiceCount, StockMovement, Tank, WaterMeasurement
from tasks.models import Task

from .. import read
from ..models import Experiment, Factor
from . import world


class OverseeCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        world.build_open(cls)
        world.build_sealed(cls)
        cls.keeper = world.person('keeper', *world.area_perms(exclude_apps=('reports',)), 'experiments.oversee_experiment')
        Experiment.objects.filter(pk=cls.experiment.pk).update(approval_ref='FOTS 30123',
                                                               approval_valid_until=cls.today + timedelta(days=90))

    def seen(self, user, model):
        with sealing.as_viewer(user):
            return set(model.objects.values_list('pk', flat=True))


class MatrixTests(OverseeCase):
    def test_the_column_is_offered_by_the_experiments_area_alone(self):
        self.assertIn('oversee', dict(access.ACTIONS))
        offering = [area.model for area in access.areas() if 'oversee' in area.actions]
        self.assertEqual(offering, ['experiments.Experiment'])
        self.assertTrue(Permission.objects.filter(codename='oversee_experiment').exists())

    def test_the_role_form_tells_which_duties_it_may_touch_and_never_blocks(self):
        self.client.force_login(self.boss)
        response = self.client.get(reverse('core:group_create'))
        self.assertContains(response, 'Oversee')
        self.assertContains(response, 'medicine withdrawal')


class FactsTests(OverseeCase):
    def test_an_overseer_sees_every_welfare_fact_of_a_sealed_tank(self):
        for model in (Tank, StockMovement, FeedingRecord, WaterMeasurement, LiceCount, HealthEvent, Task):
            with self.subTest(model=model.__name__):
                self.assertEqual(self.seen(self.keeper, model), self.seen(self.boss, model))

    def test_never_the_science(self):
        self.assertEqual(self.seen(self.keeper, Experiment), set())
        self.assertEqual(self.seen(self.keeper, Factor), set())
        self.client.force_login(self.keeper)
        response = self.client.get(reverse('experiments:experiment_detail', args=[self.experiment.pk]))
        self.assertEqual(response.status_code, 404)

    def test_the_card_names_the_trial_its_lead_approval_and_days_never_its_design(self):
        # The lead's phone (owner amendment C3) waits for the owner: HR keeps no contact detail on an employee.
        with sealing.as_viewer(self.keeper):
            chips = read.chips(self.sealed_tanks, self.keeper)
        chip = chips[self.sealed_tanks[0].pk][0]
        text = f'{chip.label} {chip.title}'
        self.assertIn('Research trial', text)
        for shown in ('lead', 'FOTS 30123'):
            self.assertIn(shown, text)
        for hidden in ('XQZ', self.experiment.code):
            self.assertNotIn(hidden, text)
        self.assertEqual(chip.url, '')

    def test_someone_without_oversee_gets_no_chip(self):
        with sealing.as_viewer(self.researcher):
            self.assertEqual(read.chips(self.sealed_tanks, self.researcher), {})

    def test_an_overseer_read_of_a_sealed_tank_is_logged_as_oversee(self):
        from core.models import AccessEvent
        self.client.force_login(self.keeper)
        self.client.get(reverse('farm:production_units') + f'?unit={self.sealed_tanks[0].pk}')
        self.assertTrue(AccessEvent.objects.filter(kind='oversee', user_name='keeper').exists())


class DefaultGrantTests(TestCase):
    def test_the_migration_gives_oversee_to_the_roles_that_care_for_the_fish(self):
        from importlib import import_module
        from django.apps import apps
        from django.contrib.auth.models import Group
        module = import_module('experiments.migrations.0005_oversee_defaults')
        keeper = Group.objects.create(name='Shift technician')
        keeper.permissions.set(Permission.objects.filter(codename='add_feedingrecord'))
        office = Group.objects.create(name='HR')
        office.permissions.set(Permission.objects.filter(codename='view_employee'))
        granted = module.grant(apps)
        self.assertEqual(granted, ['Shift technician'])
        self.assertTrue(keeper.permissions.filter(codename='oversee_experiment').exists())
        self.assertFalse(office.permissions.filter(codename='oversee_experiment').exists())
