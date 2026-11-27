"""An outside researcher (owner decision of 23.11.2026: no guest accounts): an ordinary account the platform admin makes,
with the Research collaborator role (experiments.roles: Experiments: read, nothing else). The experiment's lead adds
the person to its team, or shares a part of it with them, and they then read that experiment and its own pages and
nothing else of the farm: no farm page, no other sealed experiment. Taken off the team, they read nothing of it at once.
The lead may share with any active account that has a role."""
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core.codes import next_code
from farm.tests.helpers import rows_data

from .. import roles
from ..models import Experiment, ExperimentShare, Member
from . import world


class CollaboratorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        world.build_open(cls)
        world.build_sealed(cls)
        name, created = roles.create()
        cls.role = Group.objects.get(name=name)
        cls.visitor = get_user_model().objects.create_user('visitor', 'visitor@example.com', 'x')
        cls.visitor.groups.add(cls.role)
        # Another sealed experiment of the same lead, which the visitor is never given.
        cls.other = Experiment.objects.create(
            code=next_code(Experiment, f'E-{cls.today.year}-'), name='Other secret trial', site=cls.site,
            species=cls.salmon, duration_days=30)
        Member.objects.create(experiment=cls.other, user=cls.lead, role='lead')

    def page(self, name, *args, **query):
        self.client.force_login(self.visitor)
        return self.client.get(reverse(name, args=args), query)

    def team(self, rows):
        self.client.force_login(self.lead)
        return self.client.post(reverse('experiments:experiment_team', args=[self.experiment.pk]),
                                rows_data('team', rows, record=self.experiment))

    def lead_row(self):
        return {'user': self.lead.pk, 'role': 'lead'}

    def test_the_role_is_experiments_read_alone_named_in_each_language(self):
        self.assertEqual(sorted(f'{p.content_type.app_label}.{p.codename}' for p in self.role.permissions.all()),
                         ['experiments.view_experiment'])
        out = StringIO()
        call_command('experiments_roles', '--language', 'nb', stdout=out)
        self.assertIn('created', out.getvalue())
        self.assertTrue(Group.objects.filter(name='Forskningssamarbeidspartner').exists())
        call_command('experiments_roles', stdout=out)                 # the English one exists: kept as it is
        self.assertIn('exists, kept as it is', out.getvalue())

    def test_the_lead_adds_them_they_read_it_and_nothing_else_and_taken_off_they_read_nothing(self):
        detail = ('experiments:experiment_detail', self.experiment.pk)
        self.assertEqual(self.page(*detail).status_code, 404)
        self.assertNotIn('XQZ', world.page_text(self.page('experiments:experiment_list')))

        self.assertEqual(self.team([self.lead_row(), {'user': self.visitor.pk, 'role': 'researcher'}]).status_code, 302)
        self.assertContains(self.page(*detail), 'XQZ diet trial')
        self.assertEqual(self.page(*detail, tab='data').status_code, 200)
        listing = self.page('experiments:experiment_list')
        self.assertContains(listing, 'XQZ diet trial')
        self.assertNotContains(listing, 'Other secret trial')
        self.assertEqual(self.page('experiments:experiment_detail', self.other.pk).status_code, 404)
        for farm_page in ('farm:production_units', 'tasks:task_list', 'farm:feeding_records', 'sensors:channel_list'):
            with self.subTest(page=farm_page):
                self.assertEqual(self.page(farm_page).status_code, 403)
        self.assertNotIn('XQZ', world.page_text(self.page('home')))

        self.assertEqual(self.team([self.lead_row()]).status_code, 302)        # taken off the team
        self.assertFalse(Member.objects.filter(user=self.visitor).exists())
        self.assertEqual(self.page(*detail).status_code, 404)
        self.assertNotIn('XQZ', world.page_text(self.page('experiments:experiment_list')))

    def test_a_share_gives_them_its_parts_and_any_active_account_with_a_role_is_offered(self):
        get_user_model().objects.create_user('plain', 'plain@example.com', 'x')               # no role at all
        get_user_model().objects.create_user('gone', 'gone@example.com', 'x', is_active=False)
        self.client.force_login(self.lead)
        url = reverse('experiments:experiment_sharing', args=[self.experiment.pk])
        offered = set(self.client.get(url).context['form'].fields['person'].queryset.values_list('username', flat=True))
        self.assertTrue({'visitor', 'hr', 'student'} <= offered)
        self.assertFalse({'plain', 'gone', 'root'} & offered)
        until = (self.today + timedelta(days=5)).isoformat()
        self.client.post(url, {'person': str(self.visitor.pk), 'parts': ['results'], 'until': until, 'reason': 'Review'})
        self.client.post(url, {'person': str(self.hr.pk), 'parts': ['design'], 'until': until, 'reason': 'Review'})
        self.assertEqual(ExperimentShare.objects.count(), 2)
        self.assertContains(self.page('experiments:experiment_detail', self.experiment.pk, tab='overview'), 'XQZ group')
        self.client.force_login(self.hr)                   # shared, but no role of theirs reads experiments: refused
        self.assertEqual(self.client.get(reverse('experiments:experiment_detail', args=[self.experiment.pk])).status_code,
                         403)
