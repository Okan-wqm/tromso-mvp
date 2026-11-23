"""The preflight report before confidentiality goes live (plan step 11): read from the stored rows, changing nothing."""
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone

from farm.models import System, Tank

from ..models import Experiment, ExperimentShare, Member
from . import ExperimentTestCase


class PreflightTests(ExperimentTestCase):
    audience = None

    def run_report(self, *args):
        out = StringIO()
        call_command('experiments_sealing_preflight', *args, stdout=out)
        return out.getvalue()

    def test_it_counts_the_audiences_and_names_what_the_owner_must_know(self):
        led = self.experiment('Led')
        Member.objects.create(experiment=led, user=self.user, role='lead')
        lonely = self.experiment('Lonely', audience='private')
        self.experiment('Open', audience='open')
        loop = System.objects.create(site=self.bergen, production_department=self.hall, name='Loop', code='L9')
        Tank.objects.filter(pk__in=[self.tanks[4].pk, self.tanks[5].pk]).update(system=loop)
        group = self.group(led)
        replicate = self.replicate(group)
        for tank in self.tanks[4:6]:
            self.placement(replicate, tank)
        Experiment.objects.filter(pk=led.pk).update(status='running', starts_on=self.today, approval_ref='FOTS 1',
                                                    approval_valid_until=self.today - timedelta(days=1))
        idle = get_user_model().objects.create_user('idle', 'idle@example.com', 'x', is_active=False)
        ExperimentShare.objects.create(experiment=led, user=idle, part='water', reason='Audit',
                                       valid_until=timezone.now() + timedelta(days=3))
        before = (Experiment.objects.count(), Member.objects.count(), ExperimentShare.objects.count())
        text = self.run_report('--announcement')
        self.assertIn('Audience: 1 open, 1 sealed, 1 private', text)
        self.assertIn(f'{lonely.code}: no live lead', text)
        self.assertNotIn(f'{led.code}: no live lead', text)
        self.assertIn(f'{led.code}: A R1 holds every tank of L9', text)
        self.assertIn(f'{led.code}: its approval FOTS 1 ended on', text)
        self.assertIn(f'{led.code}: a live share of water to the inactive account idle.', text)
        self.assertIn('Experiments are now confidential.', text)
        self.assertEqual((Experiment.objects.count(), Member.objects.count(), ExperimentShare.objects.count()), before)
