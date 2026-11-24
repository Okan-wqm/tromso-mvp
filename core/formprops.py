"""The props of the new look's record form and delete confirmation (islands `record-form` and `confirm-delete`,
frontend/islands/pages/RecordForm.tsx and ConfirmDelete.tsx), drawn behind `?ui=next` by the one CRUD layer
(core.crud.FormView.page, DeleteView.get): the form as core.formpayload gives it, and the page's own words, each the old
page's msgid (crud/form.html, crud/confirm_delete.html), so the new page says nothing the old one did not.

A form is drawn by the island only when the island can draw every one of its fields (`drawable`): its page is the shared
crud/form.html (a tab with a template of its own adds panels the island does not have yet) and every widget kind is one
the island draws. Any other form keeps its classic page in the new look too, and says so to nobody: it is simply the old
page (the list in `classic_forms` is what remains to port). A request for a dialog (X-Modal) keeps the classic dialog:
the island's module would not run inside a fetched dialog."""
from django.utils import formats, timezone
from django.utils.html import strip_tags
from django.utils.translation import gettext as _

from .formpayload import form_payload, delete_payload, kind_of


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


def drawable(resource, form):
    """Whether the record-form island can draw this tab's form: the shared template, and every field's kind drawn."""
    return resource.form_template == 'crud/form.html' and all(kind_of(bound.field.widget) in DRAWN for bound in form)


def record_form_props(request, form, *, action, name, obj, list_url, delete_url, history, history_url):
    """Everything the record-form island draws: the form, its submit and cancel, the History tab, the delete link."""
    from django.middleware.csrf import get_token

    return {
        'form': form_payload(form, action=action),
        'csrfToken': get_token(request),
        'submit': (_('Save %(name)s') % {'name': name}) if obj is not None else (_('Create %(name)s') % {'name': name}),
        'cancel': {'href': list_url, 'label': _('Cancel')},
        'optional': _('optional'),
        'tabsLabel': _('%(kind)s form sections') % {'kind': str(name)[:1].upper() + str(name)[1:]},
        'hasErrors': _('(has errors)'),
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
