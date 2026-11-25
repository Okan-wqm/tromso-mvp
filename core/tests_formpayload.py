"""The form layer of the new pages (core/formpayload.py) against the old one, for the form of every tab.

What a form says and posts is characterised from the old renderer itself: each bound field drawn by the project's one field
template (registration/_field.html, through BoundField.as_field_group) is read back as its label, help, errors and every
control it posts (name, value, whether it is ticked or chosen, required, switched off, and the server's bounds). The
payload of the same bound field must say and post the same, control for control. Every tab's form is checked new and
empty, and sent empty (so the server's own refusals are on it): a widget the payload does not know, a value it cannot
carry, a control it would post differently or an error it would not show fails here."""
from html.parser import HTMLParser
from importlib import import_module

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from .crud import Resource
from .formpayload import UnknownWidget, field_payload, form_payload, kind_of, unshown_visible_fields

BOUNDS = ('min', 'max', 'step', 'maxlength', 'minlength')


class Drawn(HTMLParser):
    """What one field's old markup says (label, help, errors) and posts (its controls)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.controls, self.stack, self.texts = [], [], {'label': [], 'legend': [], 'help': [], 'error': []}
        self.select = None
        self.option = None
        self.group = ''                 # the <optgroup> an option is under: its heading
        self.textarea = None

    def _where(self):
        for tag, classes in reversed(self.stack):
            if 'errorlist' in classes:
                return 'error'
            if 'help' in classes.split():
                return 'help'
            if tag in ('label', 'legend') and 'sr-only' not in classes:
                return tag
        return None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.stack.append((tag, attrs.get('class') or ''))
        if tag == 'input':
            self.stack.pop()
            kind = attrs.get('type', 'text')
            ticks = kind in ('checkbox', 'radio')
            self.controls.append({'name': attrs.get('name'), 'value': attrs.get('value', 'on' if ticks else ''),
                                  'on': ('checked' in attrs) if ticks else True, 'type': kind,
                                  'required': 'required' in attrs, 'disabled': 'disabled' in attrs,
                                  'bounds': {name: attrs[name] for name in BOUNDS if name in attrs}})
        elif tag == 'select':
            self.select = {'name': attrs.get('name'), 'required': 'required' in attrs, 'disabled': 'disabled' in attrs,
                           'multiple': 'multiple' in attrs, 'options': []}
        elif tag == 'optgroup' and self.select is not None:
            self.group = attrs.get('label') or ''
        elif tag == 'option' and self.select is not None:
            self.option = {'value': attrs.get('value', ''), 'selected': 'selected' in attrs,
                           'disabled': 'disabled' in attrs, 'label': '', 'group': self.group}
        elif tag == 'textarea':
            self.textarea = {'name': attrs.get('name'), 'value': '', 'on': True, 'type': 'textarea',
                             'required': 'required' in attrs, 'disabled': 'disabled' in attrs,
                             'bounds': {name: attrs[name] for name in BOUNDS if name in attrs}}

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag != 'input' and self.stack:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag == 'optgroup':
            self.group = ''
        if tag == 'option' and self.option is not None:
            self.option['label'] = ' '.join(self.option['label'].split())
            self.select['options'].append(self.option)
            self.option = None
        elif tag == 'select' and self.select is not None:
            for option in self.select['options']:
                self.controls.append({'name': self.select['name'], 'value': option['value'], 'on': option['selected'],
                                      'type': 'option', 'label': option['label'], 'off': option['disabled'],
                                      'group': option['group'],
                                      'required': self.select['required'], 'disabled': self.select['disabled'],
                                      'bounds': {}})
            self.select = None
        elif tag == 'textarea' and self.textarea is not None:
            self.textarea['value'] = self.textarea['value'].removeprefix('\n')
            self.controls.append(self.textarea)
            self.textarea = None
        while self.stack:
            if self.stack.pop()[0] == tag:
                break

    def handle_data(self, data):
        if self.option is not None:
            self.option['label'] += data
        elif self.textarea is not None:
            self.textarea['value'] += data
        else:
            where = self._where()
            if where:
                self.texts[where].append(data)

    def said(self, where):
        return ' '.join(''.join(self.texts[where]).split())


def drawn(bound):
    parser = Drawn()
    parser.feed(str(bound.as_field_group()))
    parser.close()
    return parser


def posted(field):
    """The controls the island draws for a field payload, as the old markup's parser reads them."""
    widget, kind = field['widget'], field['widget']['kind']
    attrs = widget['attrs']
    base = {'required': 'required' in attrs, 'disabled': 'disabled' in attrs,
            'bounds': {name: str(attrs[name]) for name in BOUNDS if name in attrs}}
    if kind in ('select', 'multiselect'):
        return [{'name': widget['name'], 'value': option['value'], 'on': option['selected'], 'type': 'option',
                 'label': ' '.join(str(option['label']).split()), 'off': bool(option['attrs'].get('disabled')),
                 'group': str(group['label'] or ''),
                 **base, 'bounds': {}}
                for group in widget['groups'] for option in group['options']]
    if kind in ('checks', 'radio'):
        return [{'name': widget['name'], 'value': option['value'], 'on': option['selected'],
                 'type': 'checkbox' if kind == 'checks' else 'radio', **base,
                 'required': 'required' in option['attrs'], 'disabled': 'disabled' in option['attrs'], 'bounds': {}}
                for group in widget['groups'] for option in group['options']]
    if kind == 'matrix':
        return [{'name': widget['name'], 'value': cell['option']['value'], 'on': cell['option']['selected'],
                 'type': 'checkbox', **base, 'disabled': 'disabled' in cell['option']['attrs'], 'bounds': {}}
                for section in widget['sections'] for area in section['areas'] for cell in area['cells']
                if cell['option']]
    if kind == 'links':
        found = []
        for row in widget['rows']:
            found.append({'name': widget['name'], 'value': row['pk'], 'on': row['checked'], 'type': 'checkbox',
                          'required': False, 'disabled': False, 'bounds': {}})
            if widget['primary']:
                found.append({'name': f"{widget['name']}-primary", 'value': row['pk'], 'on': row['primary'],
                              'type': 'radio', 'required': False, 'disabled': False, 'bounds': {}})
            for detail in row['details']:
                found += posted(detail)
        return found
    if kind in ('checkbox', 'acknowledge'):
        return [{'name': widget['name'], 'value': 'on' if widget['value'] is None else str(widget['value']),
                 'on': 'checked' in attrs, 'type': 'checkbox', **base}]
    if kind == 'textarea':
        return [{'name': widget['name'], 'value': widget['value'] or '', 'on': True, 'type': 'textarea', **base}]
    if kind == 'output':
        return []
    if kind == 'file':
        found = [{'name': widget['name'], 'value': '', 'on': True, 'type': 'file', **base}]
        if widget['current'] and not field['required'] and widget['current']['clearName']:
            found.append({'name': widget['current']['clearName'], 'value': 'on', 'on': False, 'type': 'checkbox',
                          'required': False, 'disabled': base['disabled'], 'bounds': {}})
        return found
    if kind == 'designer':
        return [{'name': widget['name'], 'value': widget['value'] or '', 'on': True, 'type': 'textarea', **base}]
    if kind == 'unshown':
        return []
    if kind == 'hidden':
        values = widget['value'] if isinstance(widget['value'], list) else [widget['value']]
        return [{'name': widget['name'], 'value': '' if value is None else str(value), 'on': True, 'type': 'hidden',
                 **base} for value in values]
    input_type = {'day': 'text', 'moment': 'text', 'time': 'text'}.get(kind, kind)
    return [{'name': widget['name'], 'value': '' if widget['value'] is None else str(widget['value']), 'on': True,
             'type': attrs.get('type', input_type), **base}]


def with_initial(field):
    """posted(field) and the hidden copy of its first value, when it has one (show_hidden_initial)."""
    initial = field['initial']
    return posted(field) + [{'name': initial['name'], 'value': value, 'on': True, 'type': 'hidden', 'required': False,
                             'disabled': False, 'bounds': {}} for value in (initial['values'] if initial else [])]


def normalised(controls):
    """Controls compared on what is posted and how. A control without a name posts nothing (the card designer's own
    pickers): left out."""
    controls = [c for c in controls if c['name']]
    return sorted(
        (c['name'] or '', c['value'],
         bool(c['on']), c['type'] if c['type'] in ('option', 'checkbox', 'radio', 'file', 'hidden', 'textarea')
         else 'input', c['required'], c['disabled'], tuple(sorted(c['bounds'].items())),
         c.get('label', ''), bool(c.get('off')), c.get('group', ''))
        for c in controls)


class FormPayloadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        import_module(settings.ROOT_URLCONF)
        cls.user = get_user_model().objects.create_superuser('payload', 'payload@example.com', 'x')

    def request(self):
        request = RequestFactory().get('/')
        request.user = self.user
        request.session = {}
        return request

    def forms(self):
        """(tab name, form) for every tab with a form: new and empty, and sent empty."""
        for resource in Resource.registry:
            if resource.form_class is None or not resource.allows('add'):
                continue
            yield f'{resource.__name__} new', resource.form(self.request())
            sent = resource.form(self.request(), {}, {})
            sent.is_valid()
            yield f'{resource.__name__} sent empty', sent

    def check_form(self, name, form):
        """Holds the form's payload to the old field template, field by field; the number of fields checked."""
        checked = 0
        with self.subTest(form=name):
            payload = form_payload(form, action='/here/')
            fields = {field['name']: field for tab in payload['tabs'] for fieldset in tab['fieldsets']
                      for field in fieldset['fields']}
            for bound in form:
                if bound.is_hidden or bound.name in unshown_visible_fields(form):
                    continue
                self.check_field(fields[bound.html_name], bound)
                checked += 1
            hidden = {each['name'] for each in payload['hidden']}
            self.assertEqual(hidden, {bound.html_name for bound in form.hidden_fields()
                                      if bound.html_name not in fields}, name)
            self.assertEqual(payload['errors'], [str(error) for error in form.non_field_errors()], name)
        return checked

    def check_field(self, field, bound):
        old = drawn(bound)
        self.assertEqual(normalised(with_initial(field)), normalised(old.controls), bound.html_name)
        label = old.said('legend') if bound.use_fieldset else old.said('label')
        self.assertIn(' '.join(str(field['label']).split()), label, bound.html_name)
        if field['help']:
            words = field['help'].get('text') or ''.join(each.get('text') or each.get('label') for each in field['help']['segments'])
            self.assertEqual(' '.join(words.split()), old.said('help'), bound.html_name)
        # one <li> per error, no space between them in the old markup: compared without whitespace
        self.assertEqual(''.join(''.join(field['errors']).split()), ''.join(old.said('error').split()), bound.html_name)

    def test_every_tab_form_has_a_payload_that_says_and_posts_what_its_old_page_does(self):
        checked = sum(self.check_form(name, form) for name, form in self.forms())
        self.assertGreater(checked, 300)

    def test_editing_a_record_its_rows_and_the_handling_acknowledgement_too(self):
        """The test world's records (no development data): every tab with a record is edited, its row lists' rows and
        empty row are held field by field, and the handling acknowledgement (a stock form's, not a tab's)."""
        from decimal import Decimal as D

        from django import forms
        from django.contrib.auth.models import Group, Permission

        from farm.forms.stock import handling_ack_field
        from farm.models import ProductionDepartment, Site, System
        from farm.tests.helpers import make_species
        from farm.tests.test_stock import make_unit
        from hr.tests.helpers_people import employee
        site = Site.objects.create(name='Test Site North', code='TSN', altitude=D(0), timezone='UTC')
        hall = ProductionDepartment.objects.create(site=site, name='Test Hall A', code='THA')
        loop = System.objects.create(name='Test Loop 1', code='TL1', site=site, production_department=hall)
        make_unit('TT-01', hall, system=loop)
        make_species()
        person = get_user_model().objects.create_user('test.person', 'test.person@example.com', first_name='Test')
        role = Group.objects.create(name='Test role')
        role.permissions.set(Permission.objects.filter(codename__in=['view_site', 'add_site']))
        person.groups.add(role)
        employee('E-9001', last='Person', first='Test')
        edited, rows = [], 0
        for resource in Resource.registry:
            if resource.form_class is None or not resource.allows('change'):
                continue
            record = resource.queryset().order_by('pk').first()
            if record is None:
                continue
            self.check_form(f'{resource.__name__} edit', resource.form(self.request(), instance=record))
            edited.append(resource.__name__)
            for key, formset in resource.edit_extras(self.request(), record).items():
                if isinstance(formset, forms.BaseFormSet):
                    for index, row in enumerate([*formset.forms, formset.empty_form]):
                        rows += self.check_form(f'{resource.__name__} rows {key} {index}', row)
        for name in ('SiteResource', 'ProductionDepartmentResource', 'SpeciesResource', 'UserResource', 'RoleResource'):
            self.assertIn(name, edited)

        class Acknowledged(forms.Form):
            go_on = handling_ack_field('harvest')
        acknowledged = Acknowledged()
        acknowledged.fields['go_on'].widget.fingerprint = 'f00d'
        self.assertEqual(self.check_form('handling acknowledgement', acknowledged), 1)
        self.assertEqual(kind_of(acknowledged.fields['go_on'].widget), 'acknowledge')
        self.assertGreater(rows, 0)

    def test_a_form_sent_empty_carries_the_servers_refusals_on_the_fields_and_its_tabs(self):
        for name, form in self.forms():
            if not form.is_bound or form.is_valid():
                continue
            with self.subTest(form=name):
                payload = form_payload(form, action='/here/')
                said = {field['name']: field['errors'] for tab in payload['tabs'] for fieldset in tab['fieldsets']
                        for field in fieldset['fields']}
                for field_name, errors in form.errors.items():
                    if field_name in form.fields and not form[field_name].is_hidden \
                            and field_name not in unshown_visible_fields(form):
                        self.assertEqual(said[form[field_name].html_name], [str(error) for error in errors])
                for tab in payload['tabs']:
                    with_errors = any(field['errors'] for fieldset in tab['fieldsets'] for field in fieldset['fields'])
                    if with_errors:
                        self.assertTrue(tab['hasErrors'], tab['key'])

    def test_a_widget_without_a_kind_is_refused_not_guessed(self):
        from django import forms

        class Slider(forms.Widget):
            pass

        with self.assertRaises(UnknownWidget):
            kind_of(Slider())

    def test_a_value_the_payload_cannot_carry_is_refused(self):
        from .formpayload import UnsafeValue, plain

        with self.assertRaises(UnsafeValue):
            plain({'when': object()})

    def test_markup_built_by_code_is_carried_as_markup_and_plain_text_as_text(self):
        from django import forms
        from django.utils.html import format_html

        class Helped(forms.Form):
            plain = forms.CharField(help_text='<b>not markup</b>')
            built = forms.CharField(help_text=format_html('<a href="{}">{}</a>', '/x/', 'see'))

        form = Helped()
        self.assertEqual(field_payload(form['plain'])['help'], {'text': '<b>not markup</b>'})
        self.assertEqual(field_payload(form['built'])['help'], {'segments': [{'href': '/x/', 'label': 'see'}]})

    def test_built_markup_keeps_only_links_to_the_applications_own_pages(self):
        from django import forms
        from django.utils.html import format_html

        class Helped(forms.Form):
            mixed = forms.CharField(help_text=format_html('See <a href="{}">{}</a> or <a href="{}">{}</a>, <b>{}</b>.',
                                                          '/reports/', 'the reports', 'https://evil.example/', 'elsewhere', 'now'))
        self.assertEqual(field_payload(Helped()['mixed'])['help'], {'segments': [
            {'text': 'See '}, {'href': '/reports/', 'label': 'the reports'}, {'text': ' or '}, {'text': 'elsewhere, now.'}]})

    def test_a_link_is_the_applications_own_only_as_a_plain_path(self):
        """Review F9: a browser reads "/<backslash>evil.example" and "/<TAB>/evil.example" as "//evil.example": refused, as any address
        that is not a plain path of this application."""
        from .formpayload import own_path
        for href in ('/reports/', '/', '/hr/team/?q=a&page=2', '/knowledge/library/12/view/#page-3'):
            self.assertTrue(own_path(href), href)
        for href in ('//evil.example', '/\\evil.example', '/\t/evil.example', '/x/\\y', 'https://evil.example/',
                     'javascript:alert(1)', 'reports/', '/x//y', ' /x/', '/x/\n'):
            self.assertFalse(own_path(href), repr(href))
