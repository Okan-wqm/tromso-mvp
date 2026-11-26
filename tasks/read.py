"""Reading the tasks for the pages, the overview and later the assistants. What is overdue, due today and done
today is worked out on read, each task on the clock of its place's site (farm.models.site.zone_of): a task is
overdue while it is open or in progress and its due date has passed, or it is due today and its due time has
passed. Nothing about it is stored (the source stored OVERDUE on the server's clock, TSK-09), so moving a due
date or completing a task needs no second write.

The page's views (Today, Open, Completed) are each a query of their own, filtered and paged on the server
(the source filtered the first 50 tasks in the browser, TSK-04)."""
from dataclasses import dataclass
from functools import reduce
from operator import or_

from django.db.models import BooleanField, Case, Count, F, IntegerField, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce

from core import people
from farm.clocks import clocks

from .models import CLOSED_STATUSES, OPEN_STATUSES, PRIORITY_RANK, Status, Task, TaskChecklistItem, TaskSeries

TODAY, OPEN, COMPLETED = 'today', 'open', 'completed'
VIEWS = (TODAY, OPEN, COMPLETED)


def _any(conditions):
    return reduce(or_, conditions, Q(pk__in=[]))


def overdue(now):
    """Open or in progress, and past the due date, or due today with the due time passed, on its site's clock
    (`now`: the clocks). Use on a queryset `with_site()`."""
    return Q(status__in=OPEN_STATUSES) & _any(
        clock.on() & (Q(due_date__lt=clock.today) | Q(due_date=clock.today, due_time__lt=clock.now)) for clock in now)


def due_today(now):
    """Open or in progress and due today on its site's clock, not yet overdue."""
    return Q(status__in=OPEN_STATUSES) & _any(clock.on() & Q(due_date=clock.today) for clock in now) & ~overdue(now)


def done_today(now):
    """Completed today on its site's clock."""
    return Q(status=Status.DONE) & _any(clock.on() & Q(completed_at__gte=clock.start) for clock in now)


def _count(rows):
    return Coalesce(Subquery(rows.annotate(n=Count('pk')).values('n')[:1], output_field=IntegerField()), Value(0))


def priority_rank():
    return Case(*(When(priority=value, then=Value(rank)) for value, rank in PRIORITY_RANK.items()),
                default=Value(len(PRIORITY_RANK)), output_field=IntegerField())


def annotated(tasks, now):
    """Tasks with `site_key`, `overdue` (a flag worked out in the query), their checklist's `lines` and
    `lines_done`, their place and their people."""
    ticked = TaskChecklistItem.objects.filter(task=OuterRef('pk'), done_at__isnull=False).values('task')
    every = TaskChecklistItem.objects.filter(task=OuterRef('pk')).values('task')
    return (tasks.with_site()
            .annotate(overdue=Case(When(overdue(now), then=Value(True)), default=Value(False),
                                   output_field=BooleanField()),
                      lines=_count(every), lines_done=_count(ticked))
            .select_related('site', 'production_department__site', 'system__site', 'unit__production_department__site',
                            'equipment__production_department__site', 'batch', 'series', 'started_by',
                            'completed_by', 'cancelled_by')
            .prefetch_related('assignees'))


def view(tasks, name, moment=None):
    """The tasks of one view, in its order:
    - Today: the overdue first, then the ones due today by time and priority, then the ones done today;
    - Open: every open one and in progress, by due date, time and priority;
    - Completed: done and cancelled, the latest first."""
    now = clocks(moment)
    tasks = annotated(tasks, now)
    if name == COMPLETED:
        closed = Coalesce('completed_at', 'cancelled_at')
        return tasks.filter(status__in=CLOSED_STATUSES).order_by(closed.desc(), 'title')
    order = [priority_rank(), 'title']
    if name == OPEN:
        return tasks.filter(status__in=OPEN_STATUSES).order_by('due_date', 'due_time', *order)
    late, today, finished = overdue(now), due_today(now), done_today(now)
    rank = Case(When(late, then=Value(0)), When(today, then=Value(1)), default=Value(2), output_field=IntegerField())
    return tasks.filter(late | today | finished).order_by(rank, 'due_date', 'due_time', *order)


def counts(tasks, moment=None):
    """How many tasks each view's tab counts: today's (overdue and due today), open, and of those overdue."""
    now = clocks(moment)
    tasks = tasks.with_site()
    late = overdue(now)
    return {
        TODAY: tasks.filter(late | due_today(now)).count(),
        OPEN: tasks.filter(status__in=OPEN_STATUSES).count(),
        'overdue': tasks.filter(late).count(),
    }


@dataclass(frozen=True)
class UnitTasks:
    """The open tasks of one unit: all of them, those overdue and those due today (not overdue yet), the Tasks
    page's own counts for that place."""
    open: int = 0
    overdue: int = 0
    due_today: int = 0


def per_unit(unit_ids, moment=None):
    """{unit id: UnitTasks} of the units that have an open or in-progress task, one grouped query: the filters of the
    views above (`overdue`, `due_today`) counted per unit, so a card says what the page would list."""
    now = clocks(moment)
    rows = (Task.objects.with_site().filter(unit_id__in=unit_ids, status__in=OPEN_STATUSES).order_by()
            .values('unit_id')
            .annotate(total=Count('pk'), late=Count('pk', filter=overdue(now)),
                      today=Count('pk', filter=due_today(now))))
    return {row['unit_id']: UnitTasks(row['total'], row['late'], row['today']) for row in rows}


# The places a recurring task's site is read through (TaskSeries.place_site), joined in one query.
SERIES_PLACES = ('site', 'production_department__site', 'system__site', 'unit__production_department__site',
                 'equipment__production_department__site')


def unplanned():
    """The active recurring tasks whose planned tasks do not reach their place's today: the task job (`manage.py
    generate_tasks`, run every hour by the server's jobs) has not made them, so today's tasks of each are missing from
    every count and list. Pages never make them (the data-layering audit, M-3: a read writes nothing, and the landing
    page must not fail on the planning): they say how many are behind, and the job makes them. A recurring task that
    starts after today is not behind, nor one planned up to its last day. Two queries at most, whatever the number of
    tasks."""
    from farm.stock.dates import site_today
    latest = max(clock.today for clock in clocks())
    candidates = (TaskSeries.objects.filter(is_active=True)
                  .filter(Q(generated_until__lt=latest) | Q(generated_until__isnull=True, starts_on__lte=latest))
                  .filter(Q(ends_on__isnull=True) | Q(generated_until__isnull=True) | Q(ends_on__gt=F('generated_until')))
                  .select_related(*SERIES_PLACES))

    def behind(series):
        # up to its place's today (the day tasks.services.materialise plans to), or its last day when that came first
        until = site_today(series.place_site)
        if series.ends_on is not None:
            until = min(until, series.ends_on)
        return series.generated_until < until if series.generated_until else series.starts_on <= until
    return [series for series in candidates if behind(series)]


def readers():
    """The people a task can be for: active users who can read Tasks (the platform admin among them). Someone
    who cannot read Tasks could never see a task given to them (the source mixed in workers without a login,
    TSK-02)."""
    return people.who_can('tasks', 'view_task')


person = people.person_name
