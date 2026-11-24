"""The form layer of the new pages (`?ui=next`): a Django form as the JSON its page's island draws.

Nothing here decides anything about a form. The payload is what Django's own form renderer is handed for the old page
(BoundField, Widget.get_context: the field's label, help, required, errors, the widget's formatted value, its attributes
with the server's min/max/step and maxlength, its options with the selected ones), projected to JSON. So the server
stays the only validator (frontend decision 4): the island shows the errors of the payload, posts the same field names
to the same address, and the next answer is a payload again (with the errors) or the redirect of a save.

Every widget a form of the project uses has a `kind` the island knows how to draw (KINDS, most specific class first). A
widget of another class is refused (UnknownWidget), never drawn as a guess: core/tests_formpayload.py builds the form of
every tab (core.crud.Resource.registry) and fails on one, so a new widget cannot reach a new page undrawn.

A value the payload carries is a string, a number, a boolean, None, or a list or dict of those: a lazy translation is
said in the request's language, a model choice by its key; anything else is refused (UnsafeValue) instead of being
turned into a string nobody checked."""
from django import forms
from django.core.exceptions import NON_FIELD_ERRORS
from django.forms.models import ModelChoiceIteratorValue
from django.utils.functional import Promise
from django.utils.safestring import SafeData

from .widgets import DayInput, DependentSelect, MomentInput, Output


class UnknownWidget(TypeError):
    pass


class UnsafeValue(TypeError):
    pass


def _kinds():
    """(widget class, kind), most specific first. Imported late: the apps' widgets import core."""
    from experiments.forms import BookableSelect
    from farm.forms.stock import AcknowledgeInput, Unshown
    from knowledge.forms.document import DocumentFileInput
    from monitoring.forms import CardDesignerWidget

    from .forms import PermissionMatrix
    from .links import LinkListWidget
    return [
        (Unshown, 'unshown'),                    # carried, drawn by the page's own question (farm/_withdrawal_change.html)
        (forms.MultipleHiddenInput, 'hidden'),
        (forms.HiddenInput, 'hidden'),
        (AcknowledgeInput, 'acknowledge'),       # the box that goes on past handling warnings (its value: their fingerprint)
        (PermissionMatrix, 'matrix'),            # a role's rights, area by action
        (LinkListWidget, 'links'),               # a record's links with their details (core.links)
        (CardDesignerWidget, 'designer'),        # a card template's layout (frontend/designer.ts)
        (DocumentFileInput, 'file'),
        (forms.ClearableFileInput, 'file'),
        (forms.FileInput, 'file'),
        (Output, 'output'),                      # a value worked out, never typed
        (DayInput, 'day'),                       # dd.mm.yyyy (frontend/date-input.ts)
        (MomentInput, 'moment'),                 # dd.mm.yyyy HH:MM
        (forms.TimeInput, 'time'),
        (forms.CheckboxSelectMultiple, 'checks'),
        (forms.RadioSelect, 'radio'),
        (BookableSelect, 'multiselect'),
        (forms.SelectMultiple, 'multiselect'),
        (DependentSelect, 'select'),
        (forms.NullBooleanSelect, 'select'),
        (forms.Select, 'select'),
        (forms.CheckboxInput, 'checkbox'),
        (forms.Textarea, 'textarea'),
        (forms.PasswordInput, 'password'),
        (forms.EmailInput, 'email'),
        (forms.URLInput, 'url'),
        (forms.NumberInput, 'number'),
        (forms.DateTimeInput, 'moment'),         # a plain one is never given a form of the project (core/tests_date_inputs.py)
        (forms.DateInput, 'day'),
        (forms.TextInput, 'text'),
    ]


def kind_of(widget):
    for cls, kind in _kinds():
        if isinstance(widget, cls):
            return kind
    raise UnknownWidget(f'{type(widget).__module__}.{type(widget).__qualname__} has no kind in core.formpayload')


def plain(value):
    """`value` as JSON: lazy text said now, a model choice by its key; refused when it is anything else."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (str, Promise)):
        return str(value)
    if isinstance(value, ModelChoiceIteratorValue):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    raise UnsafeValue(f'{type(value).__qualname__} in a form payload')


def _attrs(attrs):
    """A widget's attributes as the old page writes them: a False or None one is not written, True is written bare."""
    return {name: plain(value) for name, value in attrs.items() if value is not False and value is not None}


def _option(option):
    """One choice, its value as the browser posts it (the old markup writes `value="{{ value }}"`: always text)."""
    value = option['value']
    return {'value': '' if value is None else str(plain(value)), 'label': plain(option['label']),
            'selected': bool(option['selected']), 'attrs': _attrs(option.get('attrs') or {})}


def _initial(bound):
    """The hidden copy of a field's first value (`show_hidden_initial`: a field that says whether it was changed, a site's
    time zone), as BoundField.as_hidden(only_initial=True) writes it; None for a field without one."""
    if not bound.field.show_hidden_initial:
        return None
    hidden = bound.field.hidden_widget()
    if bound.form.is_bound and bound.html_initial_name in bound.form.data:
        value = bound.form._widget_data_value(hidden, bound.html_initial_name)
    else:
        value = bound.value()
    context = hidden.get_context(bound.html_initial_name, value, {})['widget']
    # One hidden input per value: a list field's copy (MultipleHiddenInput) writes one per chosen value, none for none.
    subwidgets = context.get('subwidgets')
    values = [sub['value'] for sub in subwidgets] if subwidgets is not None else [context.get('value')]
    return {'name': bound.html_initial_name, 'values': ['' if each is None else str(plain(each)) for each in values]}


def _text(value):
    """A help text or a label: {'text'} or, for markup a project's own code built (format_html, mark_safe), {'html'}."""
    if not value:
        return None
    return {'html': str(value)} if isinstance(value, SafeData) else {'text': str(value)}


def widget_payload(bound):
    """What the widget of a bound field is drawn from: its kind, name, id, formatted value, attributes and options."""
    widget = bound.field.widget
    kind = kind_of(widget)
    attrs = bound.build_widget_attrs({})
    if bound.auto_id and 'id' not in widget.attrs:
        attrs.setdefault('id', bound.auto_id)
    context = widget.get_context(bound.html_name, bound.value(), attrs)['widget']
    found = {'kind': kind, 'name': context['name'], 'value': plain(context.get('value')),
             'attrs': _attrs(context.get('attrs') or {})}
    if 'optgroups' in context:
        found['groups'] = [{'label': plain(label), 'options': [_option(option) for option in options]}
                           for label, options, _index in context['optgroups']]
    if kind == 'matrix':
        found['columns'] = plain(list(context['columns']))
        found['sections'] = [
            {'label': plain(group), 'areas': [
                {'label': plain(area['label']), 'notes': plain(list(area['notes'])),
                 'cells': [{'action': plain(label), 'option': _option(cell) if cell else None}
                           for label, cell in area['cells']]}
                for area in areas]}
            for group, areas in context['sections']]
    elif kind == 'links':
        found.update(columns=plain(list(context['columns'])), primary=bool(context['primary']),
                     dependsOn=plain(context['depends_on']), emptyText=plain(context['empty_text']),
                     rows=[{'pk': row['pk'], 'label': row['label'], 'group': row['group'], 'id': row['id'],
                            'checked': row['checked'], 'primary': row['primary'],
                            'details': [field_payload(detail) for detail in row['details']] if row['details'] else []}
                           for row in context['rows']])
    elif kind == 'designer':
        found.update(catalogue=plain(context['catalogue']), previewUrl=plain(context['preview_url']),
                     units=plain(context['units']))
    elif kind == 'file':
        found['current'] = (
            {'name': str(bound.value()).rsplit('/', 1)[-1],
             'clearName': plain(context.get('checkbox_name')), 'clearId': plain(context.get('checkbox_id')),
             'clearLabel': plain(getattr(widget, 'clear_checkbox_label', ''))}
            if context.get('is_initial') else None)
    return found


def field_payload(bound):
    """One field: what the old page's field template (registration/_field.html) says of it, and its widget."""
    return {
        'name': bound.html_name,
        'label': plain(bound.label),
        'help': _text(bound.help_text),
        'required': bool(bound.field.required),
        'disabled': bool(bound.field.disabled),
        'fieldset': bool(bound.use_fieldset),
        'errors': [str(error) for error in bound.errors],
        'widget': widget_payload(bound),
        'initial': _initial(bound),
    }


def _sections(form):
    """The form's inner tabs (TabbedForm.tab_list) or, for any other form, one tab of its visible fields."""
    if hasattr(form, 'tab_list'):
        return [{'key': tab['key'], 'label': plain(tab['label']), 'help': _text(tab['help']),
                 'hasErrors': bool(tab['has_errors']),
                 'fieldsets': [{'label': plain(fieldset['label']) or '', 'help': _text(fieldset['help']),
                                'fields': [field_payload(bound) for bound in fieldset['fields']]}
                               for fieldset in tab['fieldsets']]}
                for tab in form.tab_list()]
    fields = [field_payload(bound) for bound in form.visible_fields()]
    return [{'key': 'form', 'label': '', 'help': None, 'hasErrors': any(field['errors'] for field in fields),
             'fieldsets': [{'label': '', 'help': None, 'fields': fields}]}]


def form_payload(form, *, action):
    """The whole form: where it posts, whether it carries files, its hidden fields (the record's version, a new form's
    entry key), the errors above it and its tabs. A hidden field is carried; a visible field no tab shows is left out, as
    the old page leaves it out (TabbedForm.tab_list; unshown_visible_fields names them for the tests)."""
    tabs = _sections(form)
    shown = {field['name'] for tab in tabs for fieldset in tab['fieldsets'] for field in fieldset['fields']}
    hidden = []
    for bound in form:
        if bound.html_name in shown:
            continue
        if bound.is_hidden:
            hidden.append({'name': bound.html_name, 'value': plain(widget_payload(bound)['value']),
                           'kind': kind_of(bound.field.widget)})
    return {
        'action': action,
        'multipart': bool(form.is_multipart()),
        'hidden': hidden,
        'errors': [str(error) for error in form.errors.get(NON_FIELD_ERRORS, [])],
        'tabs': tabs,
        'bound': bool(form.is_bound),
    }


def unshown_visible_fields(form):
    """The visible fields of a TabbedForm that no tab shows (the old page leaves them out without a word)."""
    if not hasattr(form, 'tab_list'):
        return []
    shown = {bound.name for tab in form.tab_list() for fieldset in tab['fieldsets'] for bound in fieldset['fields']}
    return [bound.name for bound in form if not bound.is_hidden and bound.name not in shown]


def formset_payload(formset):
    """A formset (a RowList's rows): its management form and each row's fields, by row."""
    return {
        'prefix': formset.prefix,
        'management': [{'name': bound.html_name, 'value': plain(widget_payload(bound)['value'])}
                       for bound in formset.management_form],
        'errors': [str(error) for error in formset.non_form_errors()],
        'rows': [{'fields': [field_payload(bound) for bound in row.visible_fields()],
                  'hidden': [{'name': bound.html_name, 'value': plain(widget_payload(bound)['value'])}
                             for bound in row.hidden_fields()],
                  'errors': [str(error) for error in row.non_field_errors()]}
                 for row in formset.forms],
        'empty': {'fields': [field_payload(bound) for bound in formset.empty_form.visible_fields()],
                  'hidden': [{'name': bound.html_name, 'value': plain(widget_payload(bound)['value'])}
                             for bound in formset.empty_form.hidden_fields()]},
    }


def delete_payload(obj, plan, name, *, action, cancel):
    """The delete confirmation (crud/confirm_delete.html) as the native dialog draws it: the question, what is in the way,
    what goes with the record, what loses its link, what is kept and what stays linked, and what deleting does. Every
    sentence is the old page's own msgid, said here in the request's language: the dialog adds no text of its own.
    `plan` is core.softdelete.plan_delete's (None for a record erased outright)."""
    from django.utils.translation import gettext as _

    def records(items):
        return [str(item) for item in items]

    found = {'action': action, 'cancel': cancel, 'object': str(obj),
             'question': _('Delete “%(object)s”?') % {'object': obj},
             'heading': _('Delete %(name)s') % {'name': name},
             'submit': _('Delete %(name)s') % {'name': name},
             'cancelLabel': _('Cancel'),
             'blocked': None, 'groups': [], 'canDelete': plan is None or plan.can_delete}
    if plan is None:
        found['outcome'] = _('This removes it permanently. The activity log keeps a record that it was deleted.')
        return found
    if plan.blockers:
        found['blocked'] = {'title': _('This %(name)s cannot be deleted yet.') % {'name': name},
                            'reasons': [str(blocker) for blocker in plan.blockers]}
    for group in plan.deleted_groups():
        found['groups'].append({'kind': 'deleted', 'count': len(group['records']), 'records': records(group['records']),
                                'title': _('%(label)s deleted with it') % {'label': group['label']}, 'note': None})
    for group in plan.detached_groups():
        found['groups'].append({'kind': 'detached', 'count': len(group['records']), 'records': records(group['records']),
                                'title': _('%(label)s that lose their %(link)s') % {'label': group['label'],
                                                                                     'link': group['link']},
                                'note': None})
    for group in plan.kept_groups():
        found['groups'].append({'kind': 'kept', 'count': group['count'], 'records': [],
                                'title': _('%(label)s kept with it') % {'label': group['label']},
                                'note': str(group['note'])})
    for group in plan.unlinked_groups():
        found['groups'].append({'kind': 'unlinked', 'count': len(group['records']), 'records': records(group['records']),
                                'title': _('%(label)s linked to it') % {'label': group['label']},
                                'note': _('They keep the link, but it does not count while this is deleted; restoring '
                                          'it brings the link back.')})
    found['outcome'] = _('It disappears from every list but is not erased: the record stays in the database, the '
                         'activity log keeps its history, and it can be restored from the admin.')
    return found
