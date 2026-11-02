"""The shared form parts: fields described by a schema (core.schema), a form rendered again from a
draft (core.crud.TabbedForm), fields a form drops for one record, a value shown but not typed
(core.widgets.Output), filters over fixed choices, and the log of a field that went away."""
import datetime
from decimal import Decimal
from importlib import import_module

from django import forms
from django.conf import settings
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.management import call_command
from django.http import QueryDict
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import translation

from farm.models import Site

from . import audit, navigation
from .crud import Fieldset, Resource, TabbedForm, filter_by, tab_fields
from .forms import RoleForm
from .schema import Schema
from .widgets import Output


def setUpModule():
    call_command('compile_catalogs', verbosity=0)


SCHEMA = {
    'groups': [{'name': 'performance', 'label': 'Performance'}],
    'fields': [
        {'name': 'flowRate', 'label': 'Flow rate', 'type': 'number', 'unit': 'm³/h', 'required': True, 'min': 0,
         'max': 500, 'group': 'performance'},
        {'name': 'lamps', 'label': 'Number of lamps', 'type': 'number', 'integer': True, 'min': 1},
        {'name': 'phase', 'label': 'Phase', 'type': 'select',
         'options': [{'value': 'single', 'label': 'Single-phase'}, {'value': 'three', 'label': 'Three-phase'}]},
        {'name': 'parameters', 'label': 'Measured parameters', 'type': 'multiselect',
         'options': [{'value': 'temperature', 'label': 'Temperature'}, {'value': 'ph', 'label': 'pH'}]},
        {'name': 'autoFilling', 'label': 'Automatic filling', 'type': 'boolean'},
        {'name': 'calibrated', 'label': 'Last calibration', 'type': 'date'},
        {'name': 'note', 'label': 'Custom field 1', 'type': 'text', 'defaultValue': 'x'},
    ],
}


class SchemaFormTests(SimpleTestCase):
    def setUp(self):
        self.schema = Schema(SCHEMA)

    def test_each_type_gets_its_form_field(self):
        fields = self.schema.form_fields()
        self.assertEqual([type(field).__name__ for field in fields.values()], [
            'DecimalField', 'IntegerField', 'ChoiceField', 'MultipleChoiceField', 'BooleanField', 'DateField',
            'CharField'])
        self.assertEqual(fields['flowRate'].label, 'Flow rate (m³/h)')
        self.assertTrue(fields['flowRate'].required)
        self.assertEqual(fields['flowRate'].help_text, 'From 0 to 500.')
        self.assertEqual(fields['lamps'].help_text, 'At least 1.')
        self.assertEqual(list(fields['phase'].choices)[1:], [('single', 'Single-phase'), ('three', 'Three-phase')])

    def test_texts_are_shown_in_the_active_language(self):
        schema = Schema({'fields': [{'name': 'size', 'label': 'Name', 'type': 'number', 'unit': 'm', 'min': 0,
                                     'max': 500}]})
        with translation.override('nb'):
            field = schema.form_fields()['size']
        self.assertEqual((field.label, field.help_text), ('Navn (m)', 'Fra 0 til 500.'))

    def test_groups_come_first_then_the_fields_of_no_group(self):
        self.assertEqual(self.schema.fieldsets(), [
            ('Performance', '', ['flowRate']),
            ('', '', ['lamps', 'phase', 'parameters', 'autoFilling', 'calibrated', 'note'])])

    def test_a_new_record_starts_from_the_defaults(self):
        self.assertEqual(self.schema.initial()['note'], 'x')
        self.assertEqual(self.schema.initial({'flowRate': 3})['note'], None)

    def test_stored_values_leave_out_empty_ones_and_keep_json_types(self):
        stored = self.schema.to_json({
            'flowRate': Decimal('12.50'), 'lamps': 4, 'phase': '', 'parameters': ['ph', 'temperature'],
            'autoFilling': False, 'calibrated': datetime.date(2026, 3, 1), 'note': ''})
        self.assertEqual(stored, {'flowRate': 12.5, 'lamps': 4, 'parameters': ['temperature', 'ph'],
                                  'calibrated': '2026-03-01'})
        self.schema.check(stored)

    def test_stored_values_are_checked_as_the_form_would(self):
        for stored, words in [
            ([], 'set of named values'),
            ({'flowRate': 1, 'colour': 'red'}, '“colour” is not one of the specifications'),
            ({'flowRate': 501}, 'less than or equal to 500'),
            ({'flowRate': 1, 'lamps': 1.5}, 'whole number'),
            ({'flowRate': 1, 'phase': 'two'}, 'Select a valid choice'),
            ({'flowRate': 1, 'parameters': ['ph', 'temperature']}, 'not in the form it is saved in'),
            ({'flowRate': 1, 'autoFilling': False}, 'not in the form it is saved in'),
            ({'flowRate': 1, 'calibrated': '2026-3-1'}, 'not in the form it is saved in'),
            ({'flowRate': 1, 'calibrated': 'soon'}, 'Enter a valid date'),
            ({'flowRate': '1'}, 'not in the form it is saved in'),
        ]:
            with self.subTest(stored=stored), self.assertRaisesMessage(ValidationError, words):
                self.schema.check(stored)

    def test_the_log_stores_choices_as_msgids_and_numbers_with_their_unit(self):
        with audit.source_language():
            logged = self.schema.logged({'flowRate': 12.5, 'phase': 'three', 'autoFilling': True,
                                         'parameters': ['temperature', 'ph']})
        self.assertEqual(logged['Flow rate'], '12.5 m³/h')
        self.assertEqual(logged['Phase'], audit.message('Three-phase'))
        self.assertEqual(logged['Automatic filling'], audit.message('Yes'))
        self.assertEqual(logged['Measured parameters'], 'Temperature, pH')
        self.assertIsNone(logged['Number of lamps'])

    def test_a_mistake_in_a_schema_is_a_configuration_error(self):
        for fields, words in [
            ([{'name': 'a', 'type': 'text'}], 'has no name or label'),
            ([{'name': 'a', 'label': 'A', 'type': 'text'}, {'name': 'a', 'label': 'B', 'type': 'text'}], 'twice'),
            ([{'name': 'a', 'label': 'A', 'type': 'select'}], 'has no options'),
            ([{'name': 'a', 'label': 'A', 'type': 'text', 'group': 'x'}], "unknown group 'x'"),
        ]:
            with self.subTest(fields=fields), self.assertRaisesMessage(ImproperlyConfigured, words):
                Schema({'fields': fields})


class DraftTests(TestCase):
    """A form rendered again with what was entered (TabbedForm.refresh_on) starts from those values."""

    def test_a_draft_fills_the_fields_it_carries_and_validates_nothing(self):
        form = RoleForm(draft=QueryDict('_draft=1&name=Feeders'))
        self.assertFalse(form.is_bound)
        self.assertEqual((form['name'].value(), form['permissions'].value()), ('Feeders', []))
        self.assertEqual(form.errors, {})

    def test_without_a_draft_the_form_starts_from_the_record(self):
        self.assertEqual(RoleForm()['name'].value(), None)


class FilterByChoicesTests(TestCase):
    def test_a_filter_over_fixed_choices_keeps_only_known_values(self):
        Site.objects.create(name='A', code='A', status='active')
        Site.objects.create(name='B', code='B', status='closed')
        for query, expected in [('status=closed', ['B']), ('status=nonsense', ['A', 'B']), ('', ['A', 'B'])]:
            request = RequestFactory().get(f'/?{query}')
            objects, chosen = filter_by(request, Site.objects.order_by('name'), 'status', Site.Status.choices, 'status')
            self.assertEqual([site.name for site in objects], expected, query)
            self.assertEqual(chosen, 'closed' if expected == ['B'] else '')


class AuditDiffTests(SimpleTestCase):
    def test_a_label_that_goes_away_changes_to_nothing(self):
        before = {'Name': 'Pump', 'Flow rate': '120 m³/h', 'Head': None}
        after = {'Name': 'Pump', 'Heating capacity': '20 kW'}
        self.assertEqual(audit.diff(before, after), {'Heating capacity': [None, '20 kW'], 'Flow rate': ['120 m³/h', None]})

    def test_equal_snapshots_differ_in_nothing(self):
        self.assertEqual(audit.diff({'Name': 'A'}, {'Name': 'A'}), {})


class FormFieldsetTests(SimpleTestCase):
    def test_tab_fields_include_the_fields_inside_a_fieldset(self):
        tabs = [('a', 'A', ['x', Fieldset('Group', ['y', 'z'])]), ('b', 'B', [])]
        self.assertEqual(tab_fields(tabs), ['x', 'y', 'z'])


class GroupForm(TabbedForm):
    """A form that drops fields for one record, as a unit's form drops the measures its kind does not have."""
    tabs = [('one', 'One', ['name', Fieldset('Shown', ['note']), Fieldset('Dropped', ['extra'])]),
            ('two', 'Two', ['size'])]
    note = forms.CharField(required=False)
    extra = forms.CharField(required=False)
    size = forms.CharField(required=False, disabled=True, widget=Output)

    class Meta:
        model = Group
        fields = ['name']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        del self.fields['extra']
        self.initial['size'] = '12.5'


class DroppedFieldTests(TestCase):
    def test_the_tabs_show_the_fields_the_form_kept_and_no_empty_heading(self):
        form = GroupForm()
        one = form.tab_list()[0]
        self.assertEqual([(fieldset['label'], [field.name for field in fieldset['fields']])
                          for fieldset in one['fieldsets']], [('', ['name']), ('Shown', ['note'])])

    def test_the_tab_of_a_field(self):
        form = GroupForm()
        self.assertEqual((form.tab_of('note'), form.tab_of('size'), form.tab_of('nothing')), ('one', 'two', ''))

    def test_an_output_shows_a_value_nobody_types(self):
        form = GroupForm({'name': 'Feeders', 'size': '999'})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['size'], '12.5')    # a posted value is never read
        html = form['size'].as_widget()
        self.assertInHTML('<output class="output" id="id_size">12.5</output>', html)
        self.assertNotIn('disabled', html)
        empty = GroupForm()
        empty.initial['size'] = ''
        self.assertInHTML('<output class="output" id="id_size">–</output>', empty['size'].as_widget())


class TitleTests(TestCase):
    def test_a_pages_heading_is_what_the_menu_calls_it(self):
        import_module(settings.ROOT_URLCONF)    # declares every resource
        for tab in Resource.registry:
            place = navigation.place(tab.perm('view'))
            self.assertEqual(tab.title(), place.entry.label, tab.__name__)
        titles = {tab.__name__: str(tab.title()) for tab in Resource.registry}
        self.assertEqual(titles['SiteResource'], 'Sites')
