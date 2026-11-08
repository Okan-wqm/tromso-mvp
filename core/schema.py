"""Fields described by data instead of code: a schema lists the values a record of a given kind has
besides its own columns. An equipment type's technical specifications are one: a pump has a flow
rate and a head, a heater a fuel type. The format is the source platform's:

    {"groups": [{"name": "performance", "label": "Performance", "description": "..."}],
     "fields": [{"name": "flowRate", "label": "Flow rate", "type": "number", "unit": "m³/h",
                 "required": true, "min": 0, "max": 1000, "integer": false, "group": "performance",
                 "options": [{"value": "three", "label": "Three-phase"}], "defaultValue": ...,
                 "placeholder": "...", "helpText": "..."}]}

"type" is one of text, textarea, number, select, multiselect, boolean and date; "integer" (a whole
number) is the one key the prototype adds. The texts (labels, descriptions, options, placeholders,
help) are English msgids, translated when shown: mark them for the catalogs where the schema is
written down (farm/equipment_types.py).

One `Schema` gives a form its fields and checks stored values with those very fields
(`SchemaValuesField`), so a stored value is valid exactly when the form would have stored it: the
rules are written once, in the schema."""
import datetime
from decimal import Decimal

from django import forms
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import models
from django.utils import formats
from django.utils.translation import gettext, gettext_lazy as _

from . import audit
from .widgets import DayInput

TYPES = ('text', 'textarea', 'number', 'select', 'multiselect', 'boolean', 'date')
TEXT_LENGTH = 255
TEXTAREA_LENGTH = 2000
# Numbers keep up to 4 decimals in 15 digits: as JSON numbers they read back exactly.
DIGITS, DECIMALS = 15, 4


class Schema:
    def __init__(self, data):
        self.groups = list(data.get('groups', []))
        self.entries = list(data.get('fields', []))
        self._check_format()

    def _check_format(self):
        """A schema is written by a developer; a mistake in it is a programming error, said plainly."""
        groups = {group.get('name') for group in self.groups}
        seen = set()
        for entry in self.entries:
            name = entry.get('name')
            problem = (
                'has no name or label' if not name or not entry.get('label') else
                'appears twice' if name in seen else
                f'has an unknown type {entry.get("type")!r}' if entry.get('type') not in TYPES else
                'has no options' if entry['type'] in ('select', 'multiselect') and not entry.get('options') else
                f'names an unknown group {entry["group"]!r}' if entry.get('group') and entry['group'] not in groups else
                ''
            )
            if problem:
                raise ImproperlyConfigured(f'Schema field {name!r} {problem}.')
            seen.add(name)

    # --- the form ---------------------------------------------------------------------------------
    def form_fields(self):
        """{name: form field} in the schema's order, with its texts in the active language."""
        return {entry['name']: self._form_field(entry) for entry in self.entries}

    def fieldsets(self):
        """[(label, description, [names])]: each group with its fields, then the fields of no group."""
        result = [(_shown(group.get('label')), _shown(group.get('description')),
                   [entry['name'] for entry in self.entries if entry.get('group') == group['name']])
                  for group in self.groups]
        loose = [entry['name'] for entry in self.entries if not entry.get('group')]
        return [fieldset for fieldset in result if fieldset[2]] + ([('', '', loose)] if loose else [])

    def initial(self, stored=None):
        """What the form starts from: the stored values, or for a new record the schema's defaults."""
        if stored is not None:
            return {entry['name']: stored.get(entry['name']) for entry in self.entries}
        return {entry['name']: entry.get('defaultValue') for entry in self.entries}

    def _form_field(self, entry):
        kind = entry['type']
        label = _shown(entry.get('label'))
        if entry.get('unit'):
            label = f'{label} ({entry["unit"]})'
        options = [(option['value'], _shown(option['label'])) for option in entry.get('options', [])]
        attrs = {'placeholder': _shown(entry['placeholder'])} if entry.get('placeholder') else {}
        common = {'label': label, 'required': bool(entry.get('required')),
                  'help_text': _shown(entry.get('helpText'))}
        if kind == 'number':
            bounds = {'min_value': entry.get('min'), 'max_value': entry.get('max')}
            common['help_text'] = ' '.join(filter(None, [common['help_text'], _bounds_text(entry)]))
            if entry.get('integer'):
                return forms.IntegerField(widget=forms.NumberInput(attrs=attrs), **bounds, **common)
            attrs['inputmode'] = 'decimal'
            # A text input read the way the language writes numbers (12,5 or 12.5), like every quantity.
            return forms.DecimalField(max_digits=DIGITS, decimal_places=DECIMALS, localize=True,
                                      widget=forms.TextInput(attrs=attrs), **bounds, **common)
        if kind == 'select':
            return forms.ChoiceField(choices=[('', '—'), *options], **common)
        if kind == 'multiselect':
            return forms.MultipleChoiceField(
                choices=options, widget=forms.CheckboxSelectMultiple(attrs={'class': 'choices'}), **common)
        if kind == 'boolean':
            return forms.BooleanField(**common)
        if kind == 'date':
            return forms.DateField(widget=DayInput(), **common)
        if kind == 'textarea':
            return forms.CharField(max_length=TEXTAREA_LENGTH, widget=forms.Textarea(attrs={'rows': 3, **attrs}),
                                   **common)
        return forms.CharField(max_length=TEXT_LENGTH, widget=forms.TextInput(attrs=attrs), **common)

    # --- stored values ------------------------------------------------------------------------------
    def to_json(self, cleaned):
        """The values to store from the form's cleaned values: empty ones are left out, numbers are
        JSON numbers, dates ISO text, a multiple choice in the order of its options."""
        stored = {}
        for entry in self.entries:
            value = self._json_value(entry, cleaned.get(entry['name']))
            if value is not None:
                stored[entry['name']] = value
        return stored

    @staticmethod
    def _json_value(entry, value):
        if value in (None, '', [], False):
            return None
        if isinstance(value, Decimal):
            return int(value) if value == value.to_integral_value() else float(value)
        if isinstance(value, datetime.date):
            return value.isoformat()
        if isinstance(value, list):
            order = [option['value'] for option in entry['options']]
            return sorted(value, key=order.index)
        return value

    def check(self, values):
        """Raises ValidationError when stored `values` are not what the form would have stored: a
        name the schema does not have, a value the form refuses, or one not stored as the form stores it."""
        if not isinstance(values, dict):
            raise ValidationError(_('The specifications must be a set of named values.'))
        errors = []
        fields = self.form_fields()
        for name in sorted(values.keys() - fields.keys()):
            errors.append(ValidationError(_('“%(name)s” is not one of the specifications of this type.'),
                                          params={'name': name}))
        for entry in self.entries:
            name, stored = entry['name'], values.get(entry['name'])
            field = fields[name]
            try:
                cleaned = field.clean(stored)
            except ValidationError as error:
                errors.extend(ValidationError('%(label)s: %(error)s', params={'label': field.label, 'error': message})
                              for message in error.messages)
                continue
            if self._json_value(entry, cleaned) != stored:
                errors.append(ValidationError(_('%(label)s: the stored value %(value)s is not in the form it is saved in.'),
                                              params={'label': field.label, 'value': repr(stored)}))
        if errors:
            raise ValidationError(errors)

    def logged(self, values):
        """{label: value} for the activity log, built in the source language (core.audit): a choice is
        stored as its msgid, a number with its unit, a person's text as written; empty ones are None."""
        logged = {}
        for entry in self.entries:
            value = values.get(entry['name'])
            options = {option['value']: option['label'] for option in entry.get('options', [])}
            if value is None:
                shown = None
            elif entry['type'] == 'select':
                shown = audit.message(options.get(value, value))
            elif entry['type'] == 'multiselect':
                shown = ', '.join(_shown(options.get(item, item)) for item in value)
            elif entry['type'] == 'boolean':
                shown = audit.message(_('Yes') if value else _('No'))
            elif entry['type'] == 'number':
                shown = f'{value} {entry["unit"]}' if entry.get('unit') else str(value)
            else:
                shown = value
            logged[_shown(entry.get('label'))] = shown
        return logged


def _shown(msgid):
    """A text of the schema (a msgid) in the active language; '' when the schema has none."""
    return gettext(msgid) if msgid else ''


def _bounds_text(entry):
    low, high = entry.get('min'), entry.get('max')
    shown = {'min': formats.localize(low), 'max': formats.localize(high)}
    if low is not None and high is not None:
        return gettext('From %(min)s to %(max)s.') % shown
    if low is not None:
        return gettext('At least %(min)s.') % shown
    if high is not None:
        return gettext('At most %(max)s.') % shown
    return ''


class SchemaValuesField(models.JSONField):
    """Values described by the schema of a linked record: an equipment's specifications, by its
    type. `schema_from` names the link; the linked record's `schema` property is the Schema. The
    values are checked against it whenever the record is validated (full_clean)."""

    # No values at all ({}) are checked too: the schema may require some.
    empty_values = [None]

    def __init__(self, *args, schema_from=None, **kwargs):
        self.schema_from = schema_from
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs['schema_from'] = self.schema_from
        return name, path, args, kwargs

    def validate(self, value, model_instance):
        super().validate(value, model_instance)
        source = getattr(model_instance, self.schema_from, None)
        if source is not None:
            source.schema.check(value)
