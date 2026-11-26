"""An experiment's care and biosecurity instructions (owner 2026-11-24): what everyone who works its tanks must do is
shown in full beside its tanks to everyone who works them, a holder of Oversee outside the team as well as the team,
while the design and the pathogen stay sealed; the lead changes them after the start too."""
from django.test import Client, TestCase
from django.urls import reverse

from core import sealing
from farm import placements

from ..models import Experiment
from . import world

CARE = 'Visor and gloves; disinfect boots; handle these tanks last'


class CareInstructionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        world.build_open(cls)
        world.build_sealed(cls)
        Experiment.objects.filter(pk=cls.experiment.pk).update(care_instructions=CARE)
        cls.keeper = world.person('keeper', *world.area_perms(exclude_apps=('reports', 'experiments')),
                                  'experiments.oversee_experiment')

    def test_a_started_experiment_still_takes_new_instructions(self):
        self.assertEqual(self.experiment.status, 'running')
        Experiment.objects.filter(pk=self.experiment.pk).update(care_instructions='Gloves')
        self.assertEqual(Experiment.objects.get(pk=self.experiment.pk).care_instructions, 'Gloves')

    def test_the_overseers_card_and_the_teams_chip_carry_them(self):
        tank = self.sealed_tanks[0]
        for user in (self.keeper, self.lead):
            with self.subTest(user=user.username), sealing.as_viewer(user):
                chips = placements.of([tank], user).get(tank.pk, [])
                self.assertEqual([chip.notice for chip in chips], [CARE])
                client = Client()
                client.force_login(user)
                self.assertContains(client.get(reverse('farm:production_units')), CARE)

    def test_the_overseer_reads_them_but_never_the_science(self):
        client = Client()
        client.force_login(self.keeper)
        for look in ('', 'next'):
            with self.subTest(look=look):
                page = client.get(reverse('farm:production_units') + (f'?ui={look}' if look else ''))
                self.assertContains(page, CARE)
                self.assertNotContains(page, world.SCIENCE)

    def test_the_lead_writes_them_on_the_approval_tab(self):
        from ..forms import APPROVAL_FIELDS
        self.assertIn('care_instructions', APPROVAL_FIELDS)
