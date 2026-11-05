"""Reference data › Card templates and Card template rules: every form field a column, create, read, edit, delete and
restore against the stored rows and the activity log, a built-in that cannot be changed but copied, the rules' one
scope, the menu, the role matrix, the database viewer, the languages, and that a template saved moves every wall's
token."""
import itertools
import json

from django.urls import reverse

from core import access, database, navigation, softdelete
from core.models import AuditLog, Profile

from .. import read
from ..cards import builtin
from ..forms import CardTemplateAssignmentForm, CardTemplateForm
from ..models import CardTemplate, CardTemplateAssignment
from . import MonitoringCase

DESIGNER = ('view_cardtemplate', 'add_cardtemplate', 'change_cardtemplate', 'delete_cardtemplate',
            'view_cardtemplateassignment', 'add_cardtemplateassignment', 'change_cardtemplateassignment',
            'delete_cardtemplateassignment', 'view_stockoperation', 'view_tank')
TEMPLATES, NEW_TEMPLATE = reverse('monitoring:cardtemplate_list'), reverse('monitoring:cardtemplate_create')
RULES, NEW_RULE = reverse('monitoring:cardtemplateassignment_list'), reverse('monitoring:cardtemplateassignment_create')
NUMBER = itertools.count(1)
LAYOUT = {'schema': 1, 'widgets': [
    {'id': 'w1', 'type': 'value', 'x': 0, 'y': 0, 'w': 3, 'h': 2, 'bind': {'parameter': 'oxygen_mg_l'}},
    {'id': 'w2', 'type': 'fish', 'x': 0, 'y': 2, 'w': 12, 'h': 5}]}


class PagesCase(MonitoringCase):
    def setUp(self):
        super().setUp()
        self.designer = self.as_person('designer', *DESIGNER)

    def edit(self, template):
        return reverse('monitoring:cardtemplate_edit', args=[template.pk])

    def posted(self, template, **changes):
        form = self.client.get(self.edit(template)).context['form']
        data = {name: ('' if form[name].value() is None else form[name].value()) for name in form.fields}
        data['layout'] = json.dumps(template.layout) if isinstance(data['layout'], (dict, list)) else data['layout']
        return {**data, **changes}

    def template(self, name=None, **fields):
        return CardTemplate.objects.create(name=name or f'T {next(NUMBER)}', layout=fields.pop('layout', LAYOUT),
                                           **fields)


class ColumnsTests(PagesCase):
    def test_every_form_field_is_a_column(self):
        for form, model in ((CardTemplateForm, CardTemplate), (CardTemplateAssignmentForm, CardTemplateAssignment)):
            columns = {field.name for field in model._meta.concrete_fields}
            for name in form.base_fields:
                with self.subTest(form=form.__name__, field=name):
                    self.assertIn(name, columns)
        self.assertEqual(set(CardTemplateForm.base_fields) - {'version'}, {'name', 'description', 'expanded', 'layout'})
        self.assertEqual(set(CardTemplateAssignmentForm.base_fields) - {'version'},
                         {'template', 'unit', 'system', 'system_type', 'species', 'kind'})


class TemplateRoundTripTests(PagesCase):
    def test_a_template_is_created_read_edited_deleted_and_restored_and_each_is_logged(self):
        response = self.client.post(NEW_TEMPLATE, {'name': 'Hall view', 'description': 'Oxygen first',
                                                   'expanded': str(builtin.DETAILED), 'layout': json.dumps(LAYOUT)})
        self.assertEqual(response.status_code, 302)
        template = CardTemplate.objects.get(name='Hall view')
        self.assertEqual((template.description, template.expanded_id, template.layout, template.schema_version,
                          template.is_builtin, template.created_by, template.version),
                         ('Oxygen first', builtin.DETAILED, LAYOUT, 1, False, self.designer, 1))
        created = AuditLog.objects.get(entity_type='card template', action='create')
        self.assertEqual(created.changes['Layout'][1], 'w1 value 3x2 at 0,0 binds oxygen_mg_l; w2 fish 12x5 at 0,2')
        # read: the list (built-ins first, a mark, how many rules and boards use each), the form filled from the row
        listing = self.client.get(TEMPLATES)
        self.assertEqual([each.pk for each in listing.context['objects']][:3],
                         [builtin.DETAILED, builtin.OPERATOR, builtin.SIMPLE])
        self.assertContains(listing, 'Hall view')
        self.assertEqual(next(each for each in listing.context['objects'] if each.pk == builtin.SIMPLE).rules, 1)
        form = self.client.get(self.edit(template)).context['form']
        self.assertEqual((form['name'].value(), str(form['expanded'].value())), ('Hall view', str(builtin.DETAILED)))
        # edit: the layout and an optional field cleared; the version moves; one entry with the widget lines
        moved = {'schema': 1, 'widgets': [{**LAYOUT['widgets'][0], 'x': 3}, LAYOUT['widgets'][1]]}
        response = self.client.post(self.edit(template), self.posted(template, description='', expanded='',
                                                                     layout=json.dumps(moved)))
        self.assertEqual(response.status_code, 302)
        template.refresh_from_db()
        self.assertEqual((template.description, template.expanded, template.layout, template.version),
                         ('', None, moved, 2))
        updated = AuditLog.objects.get(entity_type='card template', action='update')
        self.assertIn('at 3,0', updated.changes['Layout'][1])
        # delete, then restore: each logged
        self.client.post(reverse('monitoring:cardtemplate_delete', args=[template.pk]))
        self.assertTrue(CardTemplate.all_objects.get(pk=template.pk).is_deleted)
        softdelete.restore(CardTemplate.all_objects.get(pk=template.pk), self.designer)
        self.assertEqual(set(AuditLog.objects.filter(entity_id=str(template.pk)).values_list('action', flat=True)),
                         {'create', 'update', 'delete', 'restore'})

    def test_a_layout_the_validator_refuses_stores_nothing_and_names_the_widget(self):
        bad = {'schema': 1, 'widgets': [{**LAYOUT['widgets'][0], 'x': 11}]}
        response = self.client.post(NEW_TEMPLATE, {'name': 'Bad', 'layout': json.dumps(bad)})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Widget w1 lies outside the card')
        self.assertFalse(CardTemplate.objects.filter(name='Bad').exists())
        response = self.client.post(NEW_TEMPLATE, {'name': 'Garbage', 'layout': 'not json'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CardTemplate.objects.filter(name='Garbage').exists())

    def test_a_stale_version_is_refused(self):
        template = self.template('Wall view')
        stale = self.posted(template, name='Mine')
        self.client.post(self.edit(template), self.posted(template, name='Theirs'))
        response = self.client.post(self.edit(template), stale, follow=True)
        self.assertEqual(CardTemplate.objects.get(pk=template.pk).name, 'Theirs')
        self.assertContains(response, 'Someone else changed this card template')

    def test_the_names_rule_reaches_the_person(self):
        self.template('Hall view')
        response = self.client.post(NEW_TEMPLATE, {'name': 'HALL VIEW', 'layout': json.dumps(LAYOUT)})
        self.assertContains(response, 'Another card template already has this name.')


class BuiltinPagesTests(PagesCase):
    def test_a_built_in_cannot_be_changed_or_deleted_but_it_can_be_copied(self):
        simple = CardTemplate.objects.get(pk=builtin.SIMPLE)
        response = self.client.post(self.edit(simple), self.posted(simple, name='Mine'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'A built-in template cannot be changed; copy it to make one of your own.')
        self.assertEqual(CardTemplate.objects.get(pk=builtin.SIMPLE).name, 'Simple')
        confirm = self.client.get(reverse('monitoring:cardtemplate_delete', args=[simple.pk]))
        self.assertContains(confirm, 'A built-in template is never deleted')
        copied = self.client.post(reverse('monitoring:cardtemplate_copy', args=[simple.pk]))
        copy = CardTemplate.objects.get(name='Simple (copy)')
        self.assertRedirects(copied, self.edit(copy), fetch_redirect_response=False)
        self.assertEqual((copy.layout, copy.is_builtin, copy.expanded_id, copy.created_by),
                         (builtin.SIMPLE_LAYOUT, False, builtin.DETAILED, self.designer))
        self.client.post(reverse('monitoring:cardtemplate_copy', args=[simple.pk]))
        self.assertTrue(CardTemplate.objects.filter(name='Simple (copy 2)').exists())
        self.assertTrue(AuditLog.objects.filter(entity_id=str(copy.pk), action='create').exists())

    def test_copying_needs_the_add_right(self):
        self.as_person('looker', 'view_cardtemplate', 'view_stockoperation')
        self.assertEqual(self.client.post(reverse('monitoring:cardtemplate_copy', args=[builtin.SIMPLE])).status_code,
                         403)


class RulePagesTests(PagesCase):
    def test_a_rule_is_created_read_edited_and_deleted_against_the_rows(self):
        mine = self.template('Hall view')
        response = self.client.post(NEW_RULE, {'template': str(mine.pk), 'unit': str(self.t2.pk), 'system': '',
                                               'system_type': '', 'species': '', 'kind': ''})
        self.assertEqual(response.status_code, 302)
        rule = CardTemplateAssignment.objects.get(unit=self.t2)
        self.assertEqual((rule.template, rule.system, rule.system_type, rule.kind, rule.created_by),
                         (mine, None, None, None, self.designer))
        listing = self.client.get(RULES)
        self.assertEqual([each.pk for each in listing.context['objects']][-1], rule.pk)       # the global rule ranks last
        edit = reverse('monitoring:cardtemplateassignment_edit', args=[rule.pk])
        form = self.client.get(edit).context['form']
        data = {name: ('' if form[name].value() is None else form[name].value()) for name in form.fields}
        self.client.post(edit, {**data, 'unit': '', 'kind': 'tank'})
        rule.refresh_from_db()
        self.assertEqual((rule.unit, rule.kind, rule.version), (None, 'tank', 2))
        self.client.post(reverse('monitoring:cardtemplateassignment_delete', args=[rule.pk]))
        self.assertTrue(CardTemplateAssignment.all_objects.get(pk=rule.pk).is_deleted)
        self.assertEqual(AuditLog.objects.filter(entity_id=str(rule.pk)).count(), 3)

    def test_one_scope_per_rule_and_the_global_rule_stays_global(self):
        mine = self.template('Hall view')
        response = self.client.post(NEW_RULE, {'template': str(mine.pk), 'unit': str(self.t2.pk), 'kind': 'tank',
                                               'system': '', 'system_type': '', 'species': ''})
        self.assertContains(response, 'A rule is for one unit, system, system type, species or kind, or for every unit.')
        global_rule = CardTemplateAssignment.objects.get()
        edit = reverse('monitoring:cardtemplateassignment_edit', args=[global_rule.pk])
        form = self.client.get(edit).context['form']
        data = {name: ('' if form[name].value() is None else form[name].value()) for name in form.fields}
        response = self.client.post(edit, {**data, 'kind': 'pond'})
        self.assertContains(response, 'The global rule stays for every unit')
        response = self.client.post(edit, {**data, 'template': str(mine.pk)})
        self.assertEqual(response.status_code, 302)                       # its template may change
        self.assertEqual(CardTemplateAssignment.objects.get(pk=global_rule.pk).template, mine)
        self.assertContains(self.client.get(reverse('monitoring:cardtemplateassignment_delete',
                                                    args=[global_rule.pk])), 'The global rule is never deleted')


class PlacesTests(PagesCase):
    def test_the_menu_the_matrix_the_viewer_and_the_languages(self):
        for perm, label, icon in (('monitoring.view_cardtemplate', 'Card templates', 'layout-dashboard'),
                                  ('monitoring.view_cardtemplateassignment', 'Card template rules', 'list-checks')):
            place = navigation.place(perm)
            self.assertEqual((str(place.entry.label), str(place.group.label), place.entry.icon),
                             (label, 'Reference data', icon))
        areas = {area.model: area for area in access.areas()}
        for model in ('monitoring.CardTemplate', 'monitoring.CardTemplateAssignment'):
            self.assertEqual(areas[model].actions, ('view', 'add', 'change', 'delete'))
        tables = {table.name: table for _section, found in database.sections() for table in found}
        for name in ('monitor_card_templates', 'monitor_card_assignments'):
            self.assertTrue(tables[name].description, name)
        for language in ('tr', 'nb'):
            Profile.objects.update_or_create(user=self.designer, defaults={'language': language})
            for url in (TEMPLATES, RULES, NEW_TEMPLATE, NEW_RULE):
                self.assertEqual(self.client.get(url).status_code, 200, (language, url))

    def test_a_person_who_reads_cards_needs_no_template_right_and_cannot_open_the_designer(self):
        self.as_person('reader-only', 'view_stockoperation')
        self.assertEqual(self.client.get(reverse('monitoring:monitor')).status_code, 200)
        for url in (TEMPLATES, NEW_TEMPLATE, RULES):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_saving_a_template_moves_every_walls_token(self):
        template = self.template('Wall view')
        before = read.change_token(self.reader, '')
        self.client.post(self.edit(template), self.posted(template, name='Wall view 2'))
        self.assertNotEqual(read.change_token(self.reader, ''), before)
