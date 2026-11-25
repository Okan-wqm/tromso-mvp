"""The props of the new look's record form and delete confirmation (islands `record-form` and `confirm-delete`,
frontend/islands/pages/RecordForm.tsx and ConfirmDelete.tsx), drawn behind `?ui=next` by the one CRUD layer
(core.crud.FormView.page, DeleteView.get): the form as core.formpayload gives it, and the page's own words, each the old
page's msgid (crud/form.html, crud/confirm_delete.html), so the new page says nothing the old one did not.

A form is drawn by the island only when the island can draw the whole page (`drawable`): its page is the shared
crud/form.html or a template of its own whose panels the tab words for the island (Resource.next_panels,
core/formpanels.py), the question a save may ask first is one the island draws, every other context of the page is drawn,
and every widget kind, the rows' too, is one the island draws. Any other form keeps its classic page in the new look too,
and says so to nobody: it is simply the old page. A request for a dialog (X-Modal) keeps the classic dialog: the island's
module would not run inside a fetched dialog."""
from django.utils import formats, timezone
from django.utils.html import strip_tags
from django.utils.translation import gettext as _

from .formpayload import UnknownWidget, form_payload, delete_payload, kind_of


def when(moment):
    """A moment as the activity log says it: dd.mm.yyyy HH:MM on the company's clock."""
    from .dates import company_zone
    return formats.date_format(timezone.localtime(moment, company_zone()), 'DATETIME_FORMAT')


def by(name):
    """'by <strong>name</strong>' of the activity log, as its words around the name: no markup crosses to an island."""
    before, _sep, after = _('by <strong>%(name)s</strong>').partition('<strong>%(name)s</strong>')
    return {'before': strip_tags(before).strip(), 'name': name, 'after': strip_tags(after).strip()}


# The widget kinds frontend/islands/pages/RecordForm.tsx draws.
DRAWN = {'hidden', 'unshown', 'text', 'email', 'url', 'number', 'password', 'textarea', 'day', 'moment', 'time',
         'select', 'multiselect', 'checks', 'radio', 'checkbox', 'file', 'output', 'matrix', 'links', 'acknowledge'}


# What the island draws of a page's own context besides the form: the tab to open after a draft refresh or a refused
# list, and the question a refused save asks (the guard's change, and the template the classic page asks it with).
DRAWN_EXTRAS = {'open_tab', 'withdrawal_change', 'question_template'}


def drawable(resource, form, extra=(), panels=()):
    """Whether the record-form island can draw this tab's form page, whole: its own template's panels worded (`panels`,
    Resource.next_panels: None for a template not ported), no question the page asks before a save but one the island
    draws (core.formpanels.QUESTIONS: the withdrawal guard's box and its text), no other context of the page's own
    (`extra`'s keys besides DRAWN_EXTRAS, the formsets of its row lists and the tab's `next_extras`), and every field's
    kind drawn, the rows' fields too. Anything else keeps the classic page; an unknown widget too, never a server error."""
    from django.forms import BaseForm, BaseFormSet

    from .formpanels import QUESTIONS
    if panels is None or resource.question_template and resource.question_template not in QUESTIONS:
        return False
    if set(extra) - DRAWN_EXTRAS - {rows.key for rows in resource.row_lists} - set(resource.next_extras):
        return False
    # the page's other forms too: a list's rows, a grid's, the fields of a form of its own (an experiment's pool)
    forms = [form, *(each for value in dict(extra).values() if isinstance(value, BaseFormSet)
                     for each in [*value.forms, value.empty_form]),
             *(value for value in dict(extra).values() if isinstance(value, BaseForm))]
    try:
        return all(kind_of(bound.field.widget) in DRAWN for each in forms for bound in each)
    except UnknownWidget:
        return False


def record_form_props(request, form, *, action, name, obj, list_url, delete_url, history, history_url, open_tab='',
                      panels=(), question=None):
    """Everything the record-form island draws: the form, its submit and cancel, the question a refused save asks
    (core.formpanels.question), the panels the tab's own template adds (core.formpanels), the History tab, the delete
    link."""
    from django.middleware.csrf import get_token

    return {
        'form': form_payload(form, action=action),
        'csrfToken': get_token(request),
        'submit': (_('Save %(name)s') % {'name': name}) if obj is not None else (_('Create %(name)s') % {'name': name}),
        'cancel': {'href': list_url, 'label': _('Cancel')},
        'optional': _('optional'),
        'tabsLabel': _('%(kind)s form sections') % {'kind': str(name)[:1].upper() + str(name)[1:]},
        'hasErrors': _('(has errors)'),
        'openTab': open_tab or None,     # the tab of the field whose change asked for a draft refresh, or of a refused list
        'question': question,
        'panels': list(panels),
        'delete': {'href': delete_url, 'label': _('Delete %(name)s') % {'name': name}} if delete_url else None,
        'history': None if obj is None else {
            'label': _('History'),
            'intro': _('The latest changes to this %(name)s.') % {'name': name},
            'link': {'href': history_url, 'label': _('See all in the activity log')},
            'empty': _('No changes recorded yet.'), 'critical': _('Critical'), 'empty_value': _('empty'),
            'entries': [{'key': str(entry.pk), 'action': str(entry.get_action_display()),
                         'critical': entry.severity == 'critical', 'by': by(entry.user_name), 'when': when(entry.created_at),
                         'changes': [{'label': str(label), 'old': None if entry.action in ('create', 'void', 'invite', 'password')
                                      else (str(old) if old else None), 'new': str(new) if new else None}
                                     for label, old, new in entry.shown_changes()]}
                        for entry in history]},
    }


def confirm_delete_props(request, obj, plan, *, name, action, cancel):
    from django.middleware.csrf import get_token
    return {**delete_payload(obj, plan, name, action=action, cancel=cancel), 'csrfToken': get_token(request)}


def dialog_props(request, form, *, action, submit, cancel, intro=(), fieldsets=None, leave_out=(), question=None,
                 danger=False, grid=None):
    """The record-form island's props of a dialog that is not a tab's form (a feeding, a treatment, a void: the classic
    dialog opened as a page in the new look): the form as core.formpayload gives it, posted to `action`, `submit` its
    button's word (the dialog's heading: Record feeding, Void), `cancel` the way back, `intro` the blocks the dialog says
    before its fields (core.formpanels.blocks_of over the classic partial), the withdrawal guard's `question`, `danger`
    for a submit that undoes (Void). `fieldsets`: (legend, [field names]) as the classic template groups them, the fields
    no group names last; `leave_out`: the fields the classic dialog does not show now (a box not asked for yet), never
    sent; `grid`: the dialog's rows posted with its form (core.formpanels.grid: a transfer's units)."""
    props = record_form_props(request, form, action=action, name='', obj=None, list_url=cancel, delete_url='',
                              history=(), history_url='', question=question)
    gone = set(leave_out)
    for tab in props['form']['tabs']:
        fields = [field for fieldset in tab['fieldsets'] for field in fieldset['fields'] if field['name'] not in gone]
        if fieldsets:
            by_name = {field['name']: field for field in fields}
            grouped = [{'label': str(legend), 'help': None, 'fields': [by_name.pop(name) for name in names if name in by_name]}
                       for legend, names in fieldsets]
            left = [field for field in fields if field['name'] in by_name]
            tab['fieldsets'] = [each for each in grouped if each['fields']] + (
                [{'label': '', 'help': None, 'fields': left}] if left else [])
        else:
            for fieldset in tab['fieldsets']:
                fieldset['fields'] = [field for field in fieldset['fields'] if field['name'] not in gone]
    props.update(submit=str(submit), tabsLabel=str(submit), intro=[block for block in intro if block], danger=bool(danger),
                 grid=grid)
    return props
