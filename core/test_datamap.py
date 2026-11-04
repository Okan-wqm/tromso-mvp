"""The data map (core.datamap): every table has a screen that fills, changes, deletes and shows it, every user column is
on a form or says why not, and docs/data-map.md and .json are what the code says now. A table, a column or a form field
added without its declaration fails here, naming the model and where to declare it."""
from contextlib import ExitStack
from importlib import import_module
from unittest import mock

from django import forms
from django.conf import settings
from django.core.management import CommandError, call_command
from django.db import models
from django.test import SimpleTestCase
from django.test.utils import isolate_apps

from . import datamap
from .datamap import Screen, computed, gap, no


def messages(screens=None, **patched):
    """The problems of a map built with `screens` declared instead of the project's (None: the project's), and with
    the functions named in `patched` replaced."""
    with ExitStack() as stack:
        if screens is not None:
            stack.enter_context(mock.patch.object(datamap, 'declarations', return_value=screens))
        for name, replacement in patched.items():
            stack.enter_context(mock.patch.object(datamap, name, replacement))
        return datamap.build()[0].problems


class DataMapTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import_module(settings.ROOT_URLCONF)    # declares every tab
        cls.screens = datamap.declarations()

    def test_the_projects_apps_are_found_from_where_their_code_lives(self):
        found = {config.label for config in datamap.project_apps()}
        self.assertTrue({'core', 'farm', 'inventory', 'knowledge', 'messaging', 'reports', 'tasks'} <= found, found)
        self.assertFalse(found & {'auth', 'admin', 'contenttypes', 'sessions'}, found)

    def test_every_table_has_a_screen_path_and_every_column_a_reason(self):
        found = datamap.problems()
        self.assertEqual(found, [], 'The data map is incomplete (README, "Data map"):\n- ' + '\n- '.join(found))

    def test_every_table_of_the_project_is_on_the_map(self):
        built = datamap.build()[0]
        self.assertEqual({model._meta.label for model in datamap.project_models()}, set(built.tables))

    def test_the_committed_files_are_what_the_code_says_now(self):
        try:
            call_command('data_map', '--check', stdout=mock.MagicMock())
        except CommandError as error:
            self.fail(f'{error}')

    def test_a_stale_file_fails_the_check(self):
        with mock.patch.object(datamap.MARKDOWN.__class__, 'read_bytes', return_value=b'old'):
            with self.assertRaisesMessage(CommandError, 'out of date'):
                call_command('data_map', '--check', stdout=mock.MagicMock())

    def test_the_map_is_reproducible(self):
        first, second = datamap.build(), datamap.build()
        self.assertEqual(first[1:], second[1:])

    # -- the rules fail when they should -------------------------------------------------------------------------
    def test_a_table_without_a_declaration_names_the_model_and_where_to_declare_it(self):
        declared = {label: screen for label, screen in self.screens.items() if label != 'farm.Batch'}
        found = ' '.join(messages(declared))
        self.assertIn('farm.Batch has no create path', found)
        self.assertIn('farm/screens.py', found)
        self.assertIn("SCREENS['Batch']", found)

    def test_a_declaration_of_a_table_that_is_not_there_fails(self):
        found = messages({**self.screens, 'farm.Nothing': Screen()})
        self.assertTrue(any('farm.Nothing' in line and 'not a table' in line for line in found), found)

    def test_a_declared_view_that_no_route_answers_to_fails(self):
        def orphan(request):
            pass
        found = messages({**self.screens, 'farm.Batch': Screen(create=(orphan,), edit=no('x'), delete=no('x'),
                                                               read=no('x'))})
        self.assertTrue(any('farm.Batch' in line and 'no route' in line for line in found), found)

    def test_a_column_on_a_form_must_not_be_declared_away(self):
        found = messages({**self.screens, 'farm.Site': Screen(columns={'name': gap('no field')})})
        self.assertTrue(any('farm.Site.name' in line and 'stale' in line for line in found), found)

    def test_a_column_on_no_form_must_say_why(self):
        found = messages({**self.screens, 'farm.Site': Screen()})
        self.assertTrue(any(line.startswith('farm.Site:') and 'is_active' in line and 'nothing says why' in line
                            for line in found), found)

    def test_a_declared_reason_for_a_column_that_does_not_exist_fails(self):
        found = messages({**self.screens, 'farm.Site': Screen(columns={
            **self.screens['farm.Site'].columns, 'nothing': computed('x')})})
        self.assertTrue(any("'nothing'" in line and 'not a column' in line for line in found), found)

    @isolate_apps('core')
    def test_a_new_model_fails_until_it_is_declared(self):
        class Experiment(models.Model):
            name = models.CharField(max_length=20)

            class Meta:
                app_label = 'core'

        found = messages(project_models=lambda: [Experiment])
        text = ' '.join(found)
        self.assertIn('core.Experiment has no create path', text)
        self.assertIn('core.Experiment has no read path', text)
        self.assertIn('core/screens.py', text)
        self.assertIn("SCREENS['Experiment']", text)
        self.assertIn('core.Experiment: name is on no form', text)
        self.assertIn('database viewer does not show', text)    # its app must be in config/database.py

    @isolate_apps('core')
    def test_a_form_field_that_is_not_a_column_fails(self):
        class Experiment(models.Model):
            name = models.CharField(max_length=20)

            class Meta:
                app_label = 'core'

        class ExperimentForm(forms.ModelForm):
            extra = forms.CharField()

            class Meta:
                model = Experiment
                fields = ['name']

        found = messages(project_models=lambda: [Experiment])
        self.assertTrue(any("the field 'extra' of ExperimentForm is not a column" in line for line in found), found)
        declared = messages({'core.Experiment': Screen(extra_fields={'extra': 'only narrows another field'})},
                            project_models=lambda: [Experiment])
        self.assertFalse(any("'extra'" in line for line in declared), declared)

    @isolate_apps('core')
    def test_a_declared_table_passes_and_its_gaps_are_listed(self):
        class Experiment(models.Model):
            name = models.CharField(max_length=20)
            note = models.TextField()

            class Meta:
                app_label = 'core'

        class ExperimentForm(forms.ModelForm):
            class Meta:
                model = Experiment
                fields = ['name']

        screen = Screen(create=no('seeded'), edit=no('seeded'), delete=gap('nobody can remove one'),
                        read=gap('no page shows it'), columns={'note': gap('no field for it')})
        with mock.patch.object(datamap, 'declarations', return_value={'core.Experiment': screen}), \
                mock.patch.object(datamap, 'project_models', return_value=[Experiment]):
            built = datamap.build()[0]
        found = [problem for problem in built.problems if 'database viewer' not in problem]
        self.assertEqual(found, [])
        gaps = built.gaps()
        self.assertEqual([(g['what'], g['weight']) for g in gaps],
                         [('read', datamap.WEIGHT['read']), ('delete', datamap.WEIGHT['delete']),
                          ('column note', datamap.WEIGHT['column'])], 'heaviest first')

    def test_every_gap_names_its_table_and_says_why(self):
        # The gaps are declared in screens.py (gap(...)), never guessed: each names a table of the map and says why.
        built = datamap.build()[0]
        for item in built.gaps():
            self.assertIn(item['table'], built.tables, item)
            self.assertTrue(item['why'], item)

    def test_the_models_of_every_installed_project_app_are_covered_by_the_rule(self):
        # An app added to INSTALLED_APPS is picked up with no list to extend here.
        counted = {model._meta.app_label for model in datamap.project_models()}
        self.assertEqual(counted, {config.label for config in datamap.project_apps() if config.get_models()})
