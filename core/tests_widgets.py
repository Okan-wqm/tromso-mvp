"""The shared choice widgets: a choice that belongs to another field's value (DependentSelect, LinkList), a choice
that belongs to none of its values ("Without a site") among them, and the browser code that keeps a chain of
such selects honest."""
from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase

from .crud import NONE as LIST_NONE
from .links import LinkList
from .widgets import NONE, DependentSelect, group_of


class GroupTests(SimpleTestCase):
    def test_a_choice_belongs_to_a_value_several_none_or_nothing(self):
        belongs = {'a': 'site-1', 'b': ['site-2', 'site-1'], 'c': None, 'd': []}
        self.assertEqual([group_of(belongs, key) for key in ('a', 'b', 'c', 'd', '')],
                         ['site-1', 'site-1 site-2', NONE, '', ''])

    def test_none_is_the_value_list_filters_use_for_without_one(self):
        self.assertEqual(NONE, LIST_NONE)


class DependentSelectTests(SimpleTestCase):
    def test_options_carry_their_group_and_one_without_a_parent_belongs_to_none(self):
        field = forms.ChoiceField(choices=[('', 'Select'), ('a', 'Hall A'), ('b', 'Old hall'), ('c', 'Spare')])
        DependentSelect.apply(field, 'site', {'a': 'site-1', 'b': None, 'c': []})
        html = field.widget.render('department', 'b')
        self.assertIn('data-depends-on="site"', html)
        self.assertIn('<option value="">Select</option>', html)
        self.assertIn('<option value="a" data-group="site-1">Hall A</option>', html)
        self.assertIn(f'<option value="b" selected data-group="{NONE}">Old hall</option>', html)
        self.assertIn('<option value="c">Spare</option>', html)

    def test_grouped_choices_keep_their_groups(self):
        field = forms.ChoiceField(choices=[('', 'Select'), ('Units', [('u1', 'T-01'), ('u2', 'T-09')])])
        DependentSelect.apply(field, 'site', {'u1': 'site-1', 'u2': None})
        html = field.widget.render('location', '')
        self.assertIn('<optgroup label="Units">', html)
        self.assertIn(f'<option value="u2" data-group="{NONE}">T-09</option>', html)


class LinkListTests(TestCase):
    def test_a_row_without_a_parent_belongs_to_none(self):
        hall, spare = Group.objects.create(name='Hall'), Group.objects.create(name='Spare')
        field = LinkList(through=Group.permissions.through, target='group', label='Groups')
        field.offer(Group.objects.order_by('name'), depends_on='site', belongs_to={str(hall.pk): None,
                                                                                    str(spare.pk): ['site-1']})
        html = field.widget.render('groups', [])
        self.assertIn(f'data-group="{NONE}"', html)
        self.assertIn('data-group="site-1"', html)


class BrowserCodeTests(SimpleTestCase):
    """The browser code is type-checked by core.test_catalogs.TypeScriptTests; these say what it must keep doing."""

    SOURCE = (Path(settings.BASE_DIR) / 'frontend' / 'components.ts').read_text(encoding='utf-8')

    def test_a_cleared_choice_tells_the_selects_that_depend_on_it(self):
        fit = self.SOURCE[self.SOURCE.index('const fitSelect'):self.SOURCE.index('const fitRows')]
        self.assertIn("select.value = '';", fit)
        self.assertIn("select.dispatchEvent(new Event('change', { bubbles: true }))", fit)

    def test_a_form_is_drawn_again_once_for_the_field_the_person_changed(self):
        refresh = self.SOURCE[self.SOURCE.index('function initRefresh'):self.SOURCE.index('// ---- link lists')]
        self.assertIn('event.isTrusted', refresh)
        self.assertIn('window.setTimeout', refresh)
