"""Copying an experiment into a new draft or a template: what is copied (the design, the same protocol rows) and what never
is (tanks, allocation, seed, team), the number, the lead, the log, a form sent twice, and the dialog."""
import uuid
from datetime import timedelta

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.urls import reverse

from core.models import AuditLog
from farm.models import FeedingProtocol

from .. import design, services
from ..models import Experiment, Factor, Level, ReplicateUnit
from .test_pages import STUDENT, PageTestCase, person
from .test_start import StartTestCase


def shape(experiment):
    """The design of an experiment as comparable data: factors, groups with their levels and replicate numbers."""
    loaded = design.load(experiment)
    return ([(f.name, f.kind, f.unit, f.position) for f in loaded.factors],
            [(g.name, g.role, g.position, [r.number for r in loaded.replicates.get(g.pk, [])],
              [(f.name, services._level_text(loaded.level_of(g, f)), getattr(loaded.level_of(g, f), 'protocol_id', None))
               for f in loaded.factors]) for g in loaded.groups])


class CopyTests(StartTestCase):
    def copy(self, source=None, name='Repeat', starts_on=None, as_template=False, token=None):
        return services.copy(self.user, source or self.trial, name, starts_on, as_template, token)

    def test_a_started_experiment_is_copied_into_a_draft_with_its_design_and_nothing_placed(self):
        self.start()
        self.trial.refresh_from_db()
        new = self.copy(starts_on=self.today + timedelta(days=30))
        self.assertEqual((new.status, new.is_template, new.name, new.starts_on, new.copied_from, new.version),
                         ('draft', False, 'Repeat', self.today + timedelta(days=30), self.trial, 1))
        self.assertNotEqual(new.code, self.trial.code)
        self.assertRegex(new.code, r'^E-\d{4}-00\d$')
        for field in ('site', 'species', 'hypothesis', 'primary_endpoint', 'duration_days', 'notes'):
            self.assertEqual(getattr(new, field), getattr(self.trial, field), field)
        self.assertEqual(shape(new), shape(self.trial))
        # the same protocol rows: the diet repeats identically, since an assigned protocol is frozen
        self.assertEqual({level.protocol_id for level in Level.objects.filter(factor__experiment=new)},
                         {self.low.pk, self.high.pk})
        self.assertEqual((ReplicateUnit.objects.filter(replicate__group__experiment=new).count(),
                          new.allocation_method, new.allocation_seed, new.allocation_note, new.members.count()),
                         (0, '', None, '', 0))
        self.assertEqual(design.load(new).placements, {})
        self.assertEqual([finding.code for finding in design.problems(new) if finding.level == 'error'],
                         ['no_lead', 'no_allocation', 'slot_without_tank', 'slot_without_tank', 'slot_without_tank',
                          'slot_without_tank'])

    def test_the_source_is_left_as_it_was_and_the_copy_shares_no_row_with_it(self):
        before = shape(self.trial), ReplicateUnit.objects.count(), Level.objects.count()
        new = self.copy()
        self.assertEqual(shape(self.trial), before[0])
        self.assertEqual(ReplicateUnit.objects.count(), before[1])
        self.assertEqual(Level.objects.count(), before[2] * 2)
        self.assertFalse({row.pk for row in Factor.objects.filter(experiment=new)}
                         & {row.pk for row in Factor.objects.filter(experiment=self.trial)})
        # changing the copy's design leaves the source's
        loaded = design.load(new)
        services.save_design(self.user, new, [services.FactorRow(f.name, f.kind, f.unit, f.pk) for f in loaded.factors],
                             [services.GroupRow(g.name, g.role, 5, [services.Cell(protocol=self.high)], g.pk)
                              for g in loaded.groups], new.version)
        self.assertEqual(shape(self.trial)[1][0][3], [1, 2])

    def test_a_template_is_a_design_without_a_day_0_and_copied_into_an_experiment_it_is_not_one(self):
        template = self.copy(name='Standard feed trial', starts_on=self.today, as_template=True)
        self.assertEqual((template.is_template, template.starts_on, template.status, template.copied_from),
                         (True, None, 'draft', self.trial))
        self.assertEqual(shape(template), shape(self.trial))
        experiment = self.copy(source=template, name='From the template', starts_on=self.today)
        self.assertEqual((experiment.is_template, experiment.starts_on, experiment.copied_from),
                         (False, self.today, template))
        self.assertEqual(shape(experiment), shape(self.trial))

    def test_the_numbers_go_on_and_a_copy_is_logged_as_created_with_its_design_and_its_source(self):
        new = self.copy()
        entry = AuditLog.objects.get(entity_id=str(new.pk), action='create')
        self.assertEqual((entry.entity_type, entry.entity_label), ('experiment', f'{new.code} · Repeat'))
        self.assertEqual(entry.changes['Copied from'], [None, str(self.trial)])
        self.assertEqual(entry.changes['Name'], [None, 'Repeat'])
        self.assertTrue(entry.changes['Design'][1].startswith('Factors: Diet (diet)\nControl (control group): Diet = '))
        second = self.copy(name='Another')
        self.assertEqual(int(second.code[-3:]), int(new.code[-3:]) + 1)

    def test_the_name_is_needed_a_form_sent_twice_makes_one_copy_and_a_deleted_source_is_refused(self):
        with self.assertRaises(ValidationError) as caught:
            self.copy(name='  ')
        self.assertEqual(caught.exception.message_dict[NON_FIELD_ERRORS], ['The copy needs a name.'])
        with self.assertRaises(ValidationError) as caught:
            self.copy(name='x' * 151)
        self.assertEqual(caught.exception.message_dict[NON_FIELD_ERRORS], ['The name of the copy is too long.'])
        token = uuid.uuid4()
        first = self.copy(token=token)
        again = self.copy(token=token)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(Experiment.objects.filter(name='Repeat').count(), 1)
        gone = self.experiment('Gone')
        gone.soft_delete(self.user)
        with self.assertRaises(ValidationError):
            self.copy(source=gone)

    def test_a_level_whose_protocol_was_retired_is_copied_and_the_design_of_the_copy_says_so(self):
        FeedingProtocol.objects.filter(pk=self.high.pk).update(status='retired')
        new = self.copy()
        self.assertIn('protocol_not_active', {finding.code for finding in design.problems(new)})

    def test_an_experiment_with_no_design_is_copied_empty(self):
        empty = self.experiment('Empty')
        new = self.copy(source=empty, name='Empty copy')
        self.assertEqual((shape(new), Factor.objects.filter(experiment=new).count()), (([], []), 0))


class CopyPageTests(PageTestCase):
    def setUp(self):
        super().setUp()
        self.create()
        self.trial = Experiment.objects.get()
        Experiment.objects.filter(pk=self.trial.pk).update(audience='open')   # the roles here; sealed: test_access
        low, high = self.protocol('Low protein'), self.protocol('High protein')
        services.save_design(self.user, self.trial, [services.FactorRow('Diet', 'diet')],
                             [services.GroupRow('Control', 'control', 2, [services.Cell(protocol=low)]),
                              services.GroupRow('High feed', 'test', 2, [services.Cell(protocol=high)])],
                             Experiment.objects.get().version)
        self.url = reverse('experiments:experiment_copy', args=[self.trial.pk])

    def post(self, **fields):
        return self.client.post(self.url, {'token': str(uuid.uuid4()), 'name': 'Repeat', 'kind': 'experiment',
                                           'starts_on': '', **fields})

    def test_the_dialog_offers_a_name_and_the_kind_and_the_templates_button_asks_for_a_template(self):
        page = self.client.get(self.url)
        self.assertEqual((page.context['form']['name'].value(), page.context['form']['kind'].value()),
                         (f'{self.trial.name} (copy)', 'experiment'))
        self.assertContains(page, 'It has no tanks, no allocation and no team but you')
        self.assertEqual(self.client.get(self.url + '?as=template').context['form']['kind'].value(), 'template')

    def test_a_copy_is_made_led_by_the_copier_logged_and_opened(self):
        response = self.post(starts_on=self.today.isoformat())
        new = Experiment.objects.get(name='Repeat')
        self.assertRedirects(response, reverse('experiments:experiment_edit', args=[new.pk]),
                             fetch_redirect_response=False)
        self.assertEqual((new.copied_from, new.starts_on, new.status), (self.trial, self.today, 'draft'))
        self.assertEqual([(m.user, m.role, m.created_by) for m in new.members.all()],
                         [(self.user, 'lead', self.user)])
        self.assertEqual(AuditLog.objects.get(entity_id=str(new.pk), changes__has_key='Team').changes,
                         {'Team': [None, 'ali (Lead)']})
        self.assertContains(self.client.get(reverse('experiments:experiment_edit', args=[new.pk])), 'High feed')

    def test_a_template_has_no_day_0_and_the_dialog_form_sent_twice_makes_one(self):
        data = {'token': str(uuid.uuid4()), 'name': 'Template', 'kind': 'template', 'starts_on': self.today.isoformat()}
        self.client.post(self.url, data)
        self.client.post(self.url, data)
        template = Experiment.objects.get(name='Template')
        self.assertEqual((template.is_template, template.starts_on, template.members.count()), (True, None, 1))
        self.assertEqual(Experiment.objects.filter(name='Template').count(), 1)
        self.assertEqual(self.client.get(reverse('experiments:experiment_list'), {'view': 'templates'}).context[
                             'objects'][0].pk, template.pk)

    def test_what_is_wrong_is_said_and_nothing_is_made(self):
        response = self.post(name='')
        self.assertEqual(response.status_code, 422)
        self.assertIn('name', response.context['form'].errors)
        response = self.post(kind='both')
        self.assertIn('kind', response.context['form'].errors)
        response = self.post(starts_on='soon')
        self.assertIn('starts_on', response.context['form'].errors)
        self.assertEqual(Experiment.objects.count(), 1)

    def test_who_may_copy_and_where_the_buttons_are(self):
        detail = reverse('experiments:experiment_detail', args=[self.trial.pk])
        self.assertContains(self.client.get(detail), f'href="{self.url}"')
        self.assertContains(self.client.get(detail), f'href="{self.url}?as=template"')
        self.assertContains(self.client.get(reverse('experiments:experiment_edit', args=[self.trial.pk])),
                            f'href="{self.url}?as=template"')
        self.client.force_login(person('reader', 'view_experiment'))
        self.assertNotContains(self.client.get(detail), f'href="{self.url}"')
        self.assertEqual(self.post().status_code, 403)
        self.client.force_login(person('student', *STUDENT))
        self.assertEqual(self.post().status_code, 302)               # Create may copy
        self.client.logout()
        self.assertIn('login', self.post()['Location'])
