"""The two tabs of Operations › Tasks, declared on core.crud: the tasks (a list with three views and a drawer,
create, edit, delete) and the recurring tasks. Their list pages make the recurring tasks' planned tasks first
(tasks.services.materialise_due), then read."""
import uuid
from datetime import timedelta
from urllib.parse import urlencode

from django.urls import reverse
from django.utils.translation import gettext, gettext_lazy as _, ngettext_lazy

from core import formpanels
from core.crud import Resource, RowList
from core.dates import read_day
from core.widgets import NONE
from farm.clocks import clocks
from farm.stock.dates import site_today

from . import places, read, services
from .forms import SeriesChecklistLines, TaskChecklistLines, TaskForm, TaskSeriesForm
from .models import Category, Priority, Status, Task, TaskSeries

FILTERS = ('view', 'q', 'site', 'location', 'assignee', 'priority', 'category', 'from', 'to')
ME = 'me'


class TaskChecklist(RowList):
    """A task's checklist, saved as a whole list on its Checklist tab until a line is ticked."""

    key, tab, label = 'checklist', 'checklist', _('Checklist')
    formset = TaskChecklistLines
    # Its panel's words (its form template's).
    title = _('Checklist')
    help_text = _('The steps of the job, one per line, at most 30; each is ticked on the Tasks page with who and when. The '
                  'list can be changed until its first line is ticked. It is saved separately from the task.')
    empty_text = _('No lines yet. Use “Add line” to add one.')
    add_label, save_label = _('Add line'), _('Save checklist')
    pending_text = _('A checklist can be added once the task is created.')
    saved = ngettext_lazy('%(count)d line saved.', '%(count)d lines saved.', 'count')

    @classmethod
    def describe(cls, row):
        return services.checklist_text(row)


class SeriesChecklist(RowList):
    """A recurring task's checklist, copied to the tasks it plans: saving it plans them again from today."""

    key, tab, label = 'checklist', 'checklist', _('Checklist')
    formset = SeriesChecklistLines
    # Its panel's words (its form template's).
    title = _('Checklist')
    help_text = _('The steps of the job, one per line, at most 30, copied to every task it plans. Saving them gives the '
                  'tasks from today on that nobody has touched the new list. It is saved separately from the recurring '
                  'task.')
    empty_text = _('No lines yet. Use “Add line” to add one.')
    add_label, save_label = _('Add line'), _('Save checklist')
    pending_text = _('A checklist can be added once the recurring task is created.')
    saved = TaskChecklist.saved

    @classmethod
    def describe(cls, row):
        return row.text

    @classmethod
    def save(cls, user, obj, rows, entity_type):
        super().save(user, obj, rows, entity_type)
        services.replan(user, obj)


class TaskResource(Resource):
    model = Task
    form_class = TaskForm
    name, plural = _('task'), _('tasks')
    url_prefix = 'operations/tasks'
    search_fields = ['title', 'description']
    list_template = 'tasks/task_list.html'
    form_template = 'tasks/task_form.html'
    icon = 'list-checks'
    row_lists = (TaskChecklist,)
    page_size = 50
    next_extras = frozenset({'checklist_started', 'checklist_lines'})

    @classmethod
    def next_panels(cls, view, form, task, extra):
        """tasks/task_form.html in the new look: the checklist to edit, or, once a line is ticked, its lines as they are,
        each ticked one with who and when on the clock of the task's site."""
        if not extra.get('checklist_started'):
            return formpanels.row_list_panels(cls, view, task, extra)
        from .templatetags.tasks import person
        return [formpanels.panel('checklist', _('Checklist'), [
            formpanels.help_text(_('The checklist has been started: its lines can no longer be changed. Add a note '
                                   'instead.')),
            formpanels.checks(_('Checklist'), [
                (line.text, line.done_at is not None, f'{person(line.done_by)} · '
                 f'{formpanels.moment(line.done_at, task.place_site)}' if line.done_at else '')
                for line in extra.get('checklist_lines', ())])])]

    @classmethod
    def form(cls, request, *args, **kwargs):
        """A new task from a page that knows its place (`?place=unit:<id>`) starts at that place."""
        if request.method == 'GET' and 'instance' not in kwargs:
            kwargs['place'] = places.find(request.GET.get('place', ''))
        return super().form(request, *args, **kwargs)

    @classmethod
    def snapshot(cls, task):
        return services.snapshot(task)

    @classmethod
    def edit_extras(cls, request, task):
        extras = super().edit_extras(request, task)
        extras['checklist_started'] = task.checklist.filter(done_at__isnull=False).exists()
        extras['checklist_lines'] = list(task.checklist.select_related('done_by'))
        return extras

    @classmethod
    def filter_list(cls, request, objects):
        services.materialise_due()
        params = {key: request.GET.get(key, '').strip() for key in (*FILTERS, 'task')}
        chosen = params['view'] if params['view'] in read.VIEWS else read.TODAY
        live = places.live()
        site_options = [(str(site.pk), site.name) for site in live['site']]
        grouped, belongs = places.choices(live)
        if any(value is None for value in belongs.values()):
            site_options.append((NONE, gettext('Without a site')))
        people = read.readers()

        objects = objects.with_site()
        if params['site'] == NONE:
            objects = objects.filter(site_key__isnull=True)
        elif params['site'] in dict(site_options):
            objects = objects.filter(site_key=params['site'])
        else:
            params['site'] = ''
        place = places.find(params['location'], live)
        if place is not None:
            objects = objects.filter(**{places.field_of(place): place})
        else:
            params['location'] = ''
        if params['assignee'] == ME:
            objects = objects.filter(assignees=request.user)
        elif params['assignee'] in {str(pk) for pk in people.values_list('pk', flat=True)}:
            objects = objects.filter(assignees=params['assignee'])
        else:
            params['assignee'] = ''
        for key, choices in (('priority', Priority.values), ('category', Category.values)):
            if params[key] in choices:
                objects = objects.filter(**{key: params[key]})
            else:
                params[key] = ''
        for key, lookup in (('from', 'due_date__gte'), ('to', 'due_date__lte')):
            day = read_day(params[key], request)
            if day is not None:
                objects = objects.filter(**{lookup: day})
            else:
                params[key] = ''

        counts = read.counts(objects)
        shown = read.view(objects, chosen)
        params['view'] = chosen if chosen != read.TODAY else ''
        base = reverse(cls.url_name('list'))

        def query(**changes):
            merged = {**params, **changes}
            return urlencode({key: value for key, value in merged.items() if value and key in (*FILTERS, 'task')})

        def address(**changes):
            found = query(**changes)
            return base + (f'?{found}' if found else '')

        context = {
            'params': params, 'view': chosen, 'none_value': NONE, 'me_value': ME,
            'views': [{'key': key, 'label': label, 'count': counts.get(key), 'href': address(view=key if key !=
                       read.TODAY else '', task=''), 'current': key == chosen}
                      for key, label in ((read.TODAY, _('Today')), (read.OPEN, _('Open')),
                                         (read.COMPLETED, _('Completed')))],
            'overdue_count': counts['overdue'],
            'site_options': site_options, 'location_choices': grouped,
            'people': people, 'priorities': Priority.choices, 'categories': Category.choices,
            'filtered': any(params[key] for key in FILTERS if key not in ('view',)),
            'clear_url': address(**{key: '' for key in FILTERS if key != 'view'}, task=''),
            'hidden_for_search': [(key, params[key]) for key in FILTERS if key != 'q' and params[key]],
            'row_query': query(task=''),
            'series_url': reverse('tasks:taskseries_list') if request.user.has_perm('tasks.view_taskseries') else '',
        }
        drawer = None
        try:
            drawer_pk = uuid.UUID(params['task']) if params['task'] else None
        except ValueError:
            drawer_pk = None
        if drawer_pk is not None:
            drawer = read.annotated(Task.objects.filter(pk=drawer_pk), clocks()).first()
        if drawer is not None:
            context.update(drawer_context(request, drawer, address(task=str(drawer.pk)), address(task='')))
        return shown, context


def drawer_context(request, task, here, close_url):
    """The drawer of the task picked (`?task=`): its details, checklist, notes and what the person may do."""
    user = request.user
    may_work = services.may_work_on(user, task)
    can_edit = user.has_perm(services.EDIT)
    is_open = task.status in (Status.OPEN, Status.IN_PROGRESS)
    query = urlencode({'next': here})
    action = lambda name: f"{reverse(f'tasks:task_{name}', args=[task.pk])}?{query}"   # noqa: E731
    return {
        'drawer': task, 'close_url': close_url, 'here': here,
        'drawer_place': task.place, 'drawer_lines': list(task.checklist.select_related('done_by')),
        'drawer_notes': list(task.notes.select_related('author')),
        'may_tick': may_work and is_open,
        'actions': {
            'start': action('start') if may_work and task.status == Status.OPEN else '',
            'complete': action('complete') if may_work and is_open else '',
            'cancel': action('cancel') if can_edit and is_open else '',
            'reopen': action('reopen') if can_edit and not is_open else '',
            'edit': reverse('tasks:task_edit', args=[task.pk]) if can_edit else '',
            'delete': reverse('tasks:task_delete', args=[task.pk]) if user.has_perm('tasks.delete_task') else '',
        },
        'note_url': action('note'),
        'is_for_me': services.is_for(user, task),
    }


class TaskSeriesResource(Resource):
    model = TaskSeries
    form_class = TaskSeriesForm
    name, plural = _('recurring task'), _('recurring tasks')
    url_prefix = 'operations/tasks/recurring'
    search_fields = ['title', 'description']
    list_template = 'tasks/series_list.html'
    form_template = 'tasks/series_form.html'
    icon = 'repeat'
    row_lists = (SeriesChecklist,)
    page_size = 50

    @classmethod
    def next_panels(cls, view, form, obj, extra):
        """tasks/series_form.html in the new look: its row lists."""
        return formpanels.row_list_panels(cls, view, obj, extra)

    @classmethod
    def queryset(cls):
        return super().queryset().select_related(
            'site', 'production_department__site', 'system__site', 'unit__production_department__site',
            'equipment__production_department__site').prefetch_related('assignees')

    @classmethod
    def snapshot(cls, series):
        return services.series_snapshot(series)

    @classmethod
    def after_save(cls, request, series, created):
        services.replan(request.user, series, created=created)

    @classmethod
    def filter_list(cls, request, objects):
        services.materialise_due()
        state = request.GET.get('state', '')
        if state == 'active':
            objects = objects.filter(is_active=True)
        elif state == 'paused':
            objects = objects.filter(is_active=False)
        else:
            state = ''
        objects = list(objects.order_by('title'))
        for series in objects:
            today = site_today(series.place_site)
            series.next_on = series.next_date(today - timedelta(days=1)) if series.is_active else None
        return objects, {'state': state, 'tasks_url': reverse('tasks:task_list')}
