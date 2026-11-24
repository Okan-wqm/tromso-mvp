"""The two tabs of Operations › Tasks, declared on core.crud: the tasks (a list with three views and a drawer,
create, edit, delete) and the recurring tasks. Their list pages make the recurring tasks' planned tasks first
(tasks.services.materialise_due), then read."""
import uuid
from datetime import timedelta
from urllib.parse import urlencode

from django.urls import reverse
from django.utils import formats
from django.utils.html import strip_tags
from django.utils.translation import gettext, gettext_lazy as _, ngettext_lazy

from core import listprops as L
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
    saved = ngettext_lazy('%(count)d line saved.', '%(count)d lines saved.', 'count')

    @classmethod
    def describe(cls, row):
        return services.checklist_text(row)


class SeriesChecklist(RowList):
    """A recurring task's checklist, copied to the tasks it plans: saving it plans them again from today."""

    key, tab, label = 'checklist', 'checklist', _('Checklist')
    formset = SeriesChecklistLines
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
    # The new look: the same context drawn by the server (its views, filters, rows and drawer as the classic page's)
    list_template_next = 'tasks/task_list_next.html'
    form_template = 'tasks/task_form.html'
    icon = 'list-checks'
    row_lists = (TaskChecklist,)
    page_size = 50

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

    # The new look (core/listprops.py): the classic list's words (tasks/series_list.html), its rows as the island's.
    search_placeholder = _('Search recurring tasks')
    empty_text = _('A job that comes back: every day, on chosen weekdays, or on a day of the month.')

    @classmethod
    def list_filters(cls, view, context):
        return [L.choice('state', _('Status'), context['state'], [('', _('Active and paused')), ('active', _('Active')),
                                                                 ('paused', _('Paused'))])]

    @classmethod
    def list_rows(cls, view, objects, context):
        from .templatetags.tasks import people, place_context, place_label, rule_text
        day = lambda value: formats.date_format(value, 'DATE_FORMAT')     # noqa: E731
        rows = []
        for series in objects:
            place, names = series.place, people(series.assignees.all())
            span = [gettext('from %(first)s') % {'first': day(series.starts_on)}]
            if series.ends_on:
                span.append(gettext('until %(last)s') % {'last': day(series.ends_on)})
            actions = []
            if context.get('can_delete'):
                actions.append(L.link(view.url('delete', series.pk), gettext('Delete %(name)s') % {'name': series.title},
                                      'trash', danger=True))
            rows.append(L.row(series.pk, {
                'title': L.title(view, context, series, series.title,
                                 sub=[f'{series.get_category_display()} · {series.get_priority_display()}']),
                'repeats': L.cell(rule_text(series), sub=[' · '.join(span)]),
                'place': L.cell(place_label(place), sub=[place_context(place)]),
                'assignees': L.cell(names) if names else L.cell(chip=L.chip('warning', gettext('Nobody'))),
                'next': L.cell(day(series.next_on) if series.next_on else '—'),
                'status': L.cell(chip=L.chip('ok', gettext('Active')) if series.is_active
                                 else L.chip('neutral', gettext('Paused'))),
            }, actions))
        # the classic page's note, its link to the Tasks page in the tabs above
        notice = strip_tags(gettext(
            'A recurring task plans its tasks up to two weeks ahead; they are on the <a href="%(url)s">Tasks</a> page. '
            'Changing or pausing it plans the tasks from today on that nobody has touched again; the others stay as they '
            'are.') % {'url': context['tasks_url']})
        return {'tabs': task_tabs(view.request, current=None), 'notices': [L.notice('plan', 'neutral', notice)],
                'columns': [L.column('title', _('Recurring task')), L.column('repeats', _('Repeats')),
                            L.column('place', _('Location')), L.column('assignees', _('Assignees')),
                            L.column('next', _('Next')), L.column('status', _('Status'))],
                'rows': rows}


def task_tabs(request, current):
    """The link tabs of Operations › Tasks on the recurring tasks' page in the new look: Today, Open and Completed (the
    Tasks page's views, for a person who may read tasks) and Recurring tasks; `current` is the view shown (None: the
    recurring tasks)."""
    base, items = reverse('tasks:task_list'), []
    if request.user.has_perm('tasks.view_task'):
        items = [(base if key == read.TODAY else f'{base}?view={key}', label, None, key == current)
                 for key, label in ((read.TODAY, _('Today')), (read.OPEN, _('Open')), (read.COMPLETED, _('Completed')))]
    items.append((reverse('tasks:taskseries_list'), _('Recurring tasks'), None, current is None))
    return L.tabs(_('Tasks'), items)
