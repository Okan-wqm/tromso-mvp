"""What a person does to a task from its drawer on the Tasks page: start, complete, cancel, reopen, tick a line of
its checklist, add a note. Each is one call of tasks/services.py; completing and cancelling are dialogs (a note,
a reason), the others a button. Afterwards the person is back on the page they came from, with the drawer open
(`next`, a Tasks address only). The overview's tiles are here too."""
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext as _, gettext_lazy
from django.views.decorators.http import require_POST

from core import navigation
from core.crud import done, render_page

from . import read, services
from .forms import CancelForm, CompleteForm, NoteForm
from .models import TaskChecklistItem, Task

VIEW = 'tasks.view_task'


def _task(pk):
    return get_object_or_404(Task.objects.select_related(
        'site', 'production_department', 'system', 'unit', 'equipment'), pk=pk)


def _back(request, task):
    """The page to go back to: the `next` it was opened from, when that is a Tasks address; else the task's drawer."""
    base = reverse('tasks:task_list')
    wanted = request.POST.get('next') or request.GET.get('next') or ''
    if wanted.startswith(base) and '//' not in wanted and '\\' not in wanted:
        return wanted
    return f'{base}?task={task.pk}'


def _refused(request, error):
    messages.error(request, ' '.join(error.messages))


@require_POST
@permission_required(VIEW, raise_exception=True)
def start(request, pk):
    task = _task(pk)
    try:
        services.start(request.user, task)
    except ValidationError as error:
        _refused(request, error)
    else:
        messages.success(request, _('“%(task)s” is in progress.') % {'task': task})
    return done(request, _back(request, task))


@require_POST
@permission_required(VIEW, raise_exception=True)
def reopen(request, pk):
    task = _task(pk)
    try:
        services.reopen(request.user, task)
    except ValidationError as error:
        _refused(request, error)
    else:
        messages.success(request, _('“%(task)s” is open again.') % {'task': task})
    return done(request, _back(request, task))


@require_POST
@permission_required(VIEW, raise_exception=True)
def tick(request, pk, item):
    task = _task(pk)
    line = get_object_or_404(TaskChecklistItem, pk=item, task=task)
    try:
        services.tick(request.user, line, request.POST.get('done') == '1')
    except ValidationError as error:
        _refused(request, error)
    return done(request, _back(request, task))


@require_POST
@permission_required(VIEW, raise_exception=True)
def add_note(request, pk):
    task = _task(pk)
    form = NoteForm(request.POST)
    if form.is_valid():
        try:
            services.add_note(request.user, task, form.cleaned_data['body'])
        except ValidationError as error:
            _refused(request, error)
    else:
        messages.error(request, ' '.join(message for errors in form.errors.values() for message in errors))
    return done(request, _back(request, task))


def _dialog(request, task, form, *, heading, question, submit, danger, field):
    place = navigation.place(VIEW)
    return render_page(request, 'tasks/task_action.html', {
        'title': heading, 'eyebrow': f'{place.section.label} · {place.entry.label}', 'heading': heading,
        'task': task, 'form': form, 'question': question, 'submit': submit, 'danger': danger,
        'field': form[field], 'back_url': _back(request, task),
    })


def _action(request, pk, *, form_class, call, allowed, heading, question, submit, done_text, danger=False):
    task = _task(pk)
    if not allowed(request.user, task):
        raise PermissionDenied
    field = next(iter(form_class.base_fields))
    form = form_class(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            call(request.user, task, form.cleaned_data[field])
        except ValidationError as error:
            for key, found in (error.message_dict if hasattr(error, 'error_dict') else {None: error.messages}).items():
                form.add_error(key if key in form.fields else None, found)
        else:
            messages.success(request, done_text % {'task': task})
            return done(request, _back(request, task))
    return _dialog(request, task, form, heading=heading, question=question % {'task': task}, submit=submit,
                   danger=danger, field=field)


@permission_required(VIEW, raise_exception=True)
def complete(request, pk):
    return _action(request, pk, form_class=CompleteForm, call=services.complete, allowed=services.may_work_on,
                   heading=_('Complete task'), question=gettext_lazy('Mark “%(task)s” as done?'),
                   submit=_('Mark as done'), done_text=_('“%(task)s” is done.'))


@permission_required(VIEW, raise_exception=True)
def cancel(request, pk):
    return _action(request, pk, form_class=CancelForm, call=services.cancel,
                   allowed=lambda user, task: user.has_perm(services.EDIT),
                   heading=_('Cancel task'), question=gettext_lazy('Cancel “%(task)s”?'),
                   submit=_('Cancel task'), done_text=_('“%(task)s” is cancelled.'), danger=True)


# ---- the production overview -------------------------------------------------------------------------------
def overview_tiles(user):
    """The overview's task tiles: open tasks due today, and overdue ones, each a link to the Tasks page. A read: the
    planned tasks of the recurring ones are made by the task job, never here (`unplanned` says when it is behind)."""
    if not user.has_perm(VIEW):
        return []
    counts = read.counts(Task.objects.all())
    url = reverse('tasks:task_list')
    return [{'key': 'due_today', 'label': _('Tasks due today'), 'count': counts[read.TODAY] - counts['overdue'],
             'url': url},
            {'key': 'overdue', 'label': _('Overdue tasks'), 'count': counts['overdue'], 'url': url}]


def unplanned_count(user):
    """How many recurring tasks have their tasks not made up to today (read.unplanned), for a person who may read tasks;
    0 for anyone else. The pages say it beside the counts it makes incomplete."""
    return len(read.unplanned()) if user.has_perm(VIEW) else 0
