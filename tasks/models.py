"""Operations › Tasks: the farm's jobs and the recurring tasks that plan them (tasks analysis §3).

A task is one job at one place (a whole site, a production department, a system, a unit or a piece of
equipment: exactly one, a database check), for one or more people who can sign in, due on a day (and
perhaps a time) on the clock of the place's site. Whether it is overdue is worked out when it is read,
never stored (the source stored OVERDUE and flipped it on the server's clock, TSK-09). Every link is a
foreign key chosen from a list: the source kept the place as free text and the assignee as a loose id
with a copied name (TSK-01, TSK-02, TSK-12).

A recurring task (`TaskSeries`) is a rule anchored to its first day: every N days, every N weeks on
chosen weekdays, or every N months on a day of the month. Its tasks are real rows, made ahead up to
TASK_HORIZON_DAYS and, after a gap, back at most TASK_BACKFILL_DAYS (tasks/services.py, `materialise`);
one row per recurring task and day, a unique key. A planned task nobody has touched (open, never edited,
no tick, no note) is only the rule's projection: changing, pausing or deleting the recurring task replaces
or removes those from today on, and keeps every other one.

The writers: the pages through core.crud for creating, editing and deleting, and tasks/services.py for
everything else (start, complete, cancel, reopen, a tick, a note, the planned tasks)."""
from calendar import monthrange
from datetime import timedelta
from functools import reduce
from operator import or_

from django.conf import settings
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Exists, F, OuterRef, Q
from django.db.models.functions import Coalesce
from django.utils.translation import gettext_lazy as _, pgettext_lazy

from core.fields import ChoiceArrayField
from core.models import AuditedModel
from farm.models import Batch, Equipment, ProductionDepartment, Site, System, Tank
from farm.stock.dates import site_today

from . import places

# ---- the place --------------------------------------------------------------------------------------
# The five links of a place, broadest first (tasks.places.KINDS); a task and a recurring task have exactly one.
PLACES = tuple(field for _model, field, _label in places.KINDS.values())
ONE_PLACE = _('Choose one place: a whole site, a production department, a system, a unit or equipment.')
# The site of a place, read through its links: a production department may have none.
SITE_OF_PLACE = Coalesce('site_id', 'production_department__site_id', 'system__site_id',
                         'unit__production_department__site_id', 'equipment__production_department__site_id')


def one_place():
    """The database check that exactly one of the five links is set."""
    return reduce(or_, (Q(**{f'{name}__isnull': name != chosen for name in PLACES}) for chosen in PLACES))


def place_link(model, label, related_name, on_delete):
    return models.ForeignKey(model, null=True, blank=True, on_delete=on_delete, related_name=related_name,
                             verbose_name=label)


class AtPlace:
    """What a task and a recurring task share about their place."""

    @property
    def place_field(self):
        """The name of the link that is set ('unit'); None before a place is chosen."""
        return next((name for name in PLACES if getattr(self, f'{name}_id')), None)

    @property
    def place(self):
        field = self.place_field
        return getattr(self, field) if field else None

    def set_place(self, place):
        """Points at `place` (a site, production department, system, unit or equipment) and nothing else."""
        chosen = places.field_of(place)
        for name in PLACES:
            setattr(self, name, place if name == chosen else None)

    @property
    def place_site(self):
        """The site of the place (tasks.places.site_of); None for a production department without one."""
        return places.site_of(self.place)

    def clean_place(self, errors):
        if sum(bool(getattr(self, f'{name}_id')) for name in PLACES) != 1:
            errors[NON_FIELD_ERRORS] = ONE_PLACE


# ---- the choices ------------------------------------------------------------------------------------
class Category(models.TextChoices):
    FEEDING = 'feeding', pgettext_lazy('task category', 'Feeding')
    CLEANING = 'cleaning', pgettext_lazy('task category', 'Cleaning')
    MAINTENANCE = 'maintenance', pgettext_lazy('task category', 'Maintenance')
    HEALTH = 'health', pgettext_lazy('task category', 'Fish health')
    WATER_QUALITY = 'water_quality', pgettext_lazy('task category', 'Water quality')
    HARVEST = 'harvest', pgettext_lazy('task category', 'Harvest')
    TRANSPORT = 'transport', pgettext_lazy('task category', 'Transport')
    ADMINISTRATION = 'administration', pgettext_lazy('task category', 'Administration')
    OTHER = 'other', pgettext_lazy('task category', 'Other')


class Priority(models.TextChoices):
    """Most urgent first: the order lists sort by (RANK)."""
    URGENT = 'urgent', _('Urgent')
    HIGH = 'high', _('High')
    MEDIUM = 'medium', _('Medium')
    LOW = 'low', _('Low')


PRIORITY_RANK = {value: rank for rank, value in enumerate(Priority.values)}


class Status(models.TextChoices):
    """Whether a task is overdue is not a status: it is read from its due date and time (`overdue`)."""
    OPEN = 'open', pgettext_lazy('task status', 'Open')
    IN_PROGRESS = 'in_progress', _('In progress')
    DONE = 'done', pgettext_lazy('task status', 'Done')
    CANCELLED = 'cancelled', pgettext_lazy('task status', 'Cancelled')


# The statuses of a task still to be done: they can be overdue, started, ticked and completed.
OPEN_STATUSES = (Status.OPEN, Status.IN_PROGRESS)
CLOSED_STATUSES = (Status.DONE, Status.CANCELLED)


class Frequency(models.TextChoices):
    DAILY = 'daily', _('Daily')
    WEEKLY = 'weekly', _('Weekly')
    MONTHLY = 'monthly', _('Monthly')


class Weekday(models.IntegerChoices):
    """Python's weekday numbers, Monday 0."""
    MONDAY = 0, _('Monday')
    TUESDAY = 1, _('Tuesday')
    WEDNESDAY = 2, _('Wednesday')
    THURSDAY = 3, _('Thursday')
    FRIDAY = 4, _('Friday')
    SATURDAY = 5, _('Saturday')
    SUNDAY = 6, _('Sunday')


MAX_INTERVAL = 52
MAX_CHECKLIST = 30
TITLE = r'\S'      # a title, a checklist line, a note or a reason with something in it besides spaces


class TaskQuerySet(models.QuerySet):
    def with_site(self):
        """Each task with `site_key`, the pk of its place's site (None: a production department without one)."""
        return self.annotate(site_key=SITE_OF_PLACE)


class TaskManager(models.Manager.from_queryset(TaskQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


# ---- recurring tasks ---------------------------------------------------------------------------------
class TaskSeries(AtPlace, AuditedModel):
    """A recurring task: the rule that plans a task at one place for its people, every N days, every N
    weeks on chosen weekdays or every N months on a day of the month, from its first day (and up to its
    last, if it has one). The source's templates drifted ("now + interval"), knew no weekday and ran on UTC
    (TSK-06); here the dates are worked out from the first day on the site's own calendar (`dates`).

    Its links say what deleting its place does (core.softdelete): the recurring task goes with it, and so
    do the planned tasks nobody has touched; the others stay (Task.deleted_with)."""

    title = models.CharField(_('Title'), max_length=200)
    description = models.TextField(_('Description'), blank=True)
    category = models.CharField(_('Category'), max_length=20, choices=Category.choices, default=Category.OTHER)
    priority = models.CharField(_('Priority'), max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    site = place_link(Site, _('Site'), 'task_series', models.CASCADE)
    production_department = place_link(ProductionDepartment, _('Production department'), 'task_series',
                                       models.CASCADE)
    system = place_link(System, _('System'), 'task_series', models.CASCADE)
    unit = place_link(Tank, _('Unit'), 'task_series', models.CASCADE)
    equipment = place_link(Equipment, _('Equipment'), 'task_series', models.CASCADE)
    assignees = models.ManyToManyField(settings.AUTH_USER_MODEL, through='TaskSeriesAssignee',
                                       related_name='task_series', verbose_name=_('Assignees'))
    frequency = models.CharField(_('Repeats'), max_length=10, choices=Frequency.choices, default=Frequency.WEEKLY)
    interval = models.PositiveSmallIntegerField(
        _('Every'), default=1, validators=[MinValueValidator(1), MaxValueValidator(MAX_INTERVAL)])
    weekdays = ChoiceArrayField(models.PositiveSmallIntegerField(choices=Weekday.choices), blank=True, default=list,
                                verbose_name=_('On'))
    day_of_month = models.PositiveSmallIntegerField(
        _('Day of the month'), null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(31)])
    due_time = models.TimeField(_('Due time'), null=True, blank=True)
    starts_on = models.DateField(_('First day'))
    ends_on = models.DateField(_('Last day'), null=True, blank=True)
    is_active = models.BooleanField(_('Active'), default=True)
    # The last day its tasks were made up to (tasks.services.materialise); None before the first time.
    generated_until = models.DateField(null=True, blank=True, editable=False)

    class Meta:
        db_table = 'task_series'
        ordering = ['title']
        verbose_name = _('recurring task')
        verbose_name_plural = _('recurring tasks')
        constraints = [
            models.CheckConstraint(condition=one_place(), name='chk_task_series_one_place',
                                   violation_error_message=ONE_PLACE),
            models.CheckConstraint(condition=Q(title__regex=TITLE), name='chk_task_series_title'),
            models.CheckConstraint(condition=Q(category__in=Category.values), name='chk_task_series_category'),
            models.CheckConstraint(condition=Q(priority__in=Priority.values), name='chk_task_series_priority'),
            models.CheckConstraint(condition=Q(frequency__in=Frequency.values), name='chk_task_series_frequency'),
            models.CheckConstraint(condition=Q(interval__gte=1, interval__lte=MAX_INTERVAL),
                                   name='chk_task_series_interval'),
            models.CheckConstraint(condition=Q(weekdays__contained_by=Weekday.values), name='chk_task_series_weekdays'),
            models.CheckConstraint(
                condition=Q(frequency=Frequency.WEEKLY, weekdays__len__gt=0)
                | (~Q(frequency=Frequency.WEEKLY) & Q(weekdays=[])),
                name='chk_task_series_weekly', violation_error_message=_('A weekly task repeats on at least one '
                                                                         'weekday; the others on none.')),
            models.CheckConstraint(
                condition=Q(frequency=Frequency.MONTHLY, day_of_month__isnull=False, day_of_month__gte=1,
                            day_of_month__lte=31)
                | (~Q(frequency=Frequency.MONTHLY) & Q(day_of_month__isnull=True)),
                name='chk_task_series_monthly', violation_error_message=_('A monthly task repeats on a day of the '
                                                                          'month; the others on none.')),
            models.CheckConstraint(condition=Q(ends_on__isnull=True) | Q(ends_on__gte=F('starts_on')),
                                   name='chk_task_series_ends_after_start',
                                   violation_error_message=_('The last day cannot be before the first day.')),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        errors = {}
        self.clean_place(errors)
        if self.frequency == Frequency.WEEKLY and not self.weekdays:
            errors['weekdays'] = _('Tick at least one weekday.')
        if self.frequency == Frequency.MONTHLY and self.day_of_month is None:
            errors['day_of_month'] = _('Enter the day of the month.')
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            errors['ends_on'] = _('The last day cannot be before the first day.')
        if errors:
            raise ValidationError(errors)

    def dates(self, first, last):
        """The days of the rule from `first` to `last`, both included, in order: never before its first day
        nor after its last. Worked out from the first day, so nothing drifts: every N days from it; every N
        weeks, counted from the Monday of its week, on the ticked weekdays; every N months, counted from its
        month, on the day of the month or, in a shorter month, its last day (the 31st is 28 February)."""
        first = max(first, self.starts_on)
        if self.ends_on is not None:
            last = min(last, self.ends_on)
        if first > last:
            return
        step = self.interval
        if self.frequency == Frequency.DAILY:
            offset = -(-(first - self.starts_on).days // step) * step
            day = self.starts_on + timedelta(days=offset)
            while day <= last:
                yield day
                day += timedelta(days=step)
        elif self.frequency == Frequency.WEEKLY:
            monday = self.starts_on - timedelta(days=self.starts_on.weekday())
            week = -(-((first - monday).days // 7) // step) * step
            while (start := monday + timedelta(weeks=week)) <= last:
                for weekday in sorted(self.weekdays):
                    day = start + timedelta(days=weekday)
                    if first <= day <= last:
                        yield day
                week += step
        else:
            months = (first.year - self.starts_on.year) * 12 + first.month - self.starts_on.month
            index = -(-months // step) * step
            while True:
                year, month = divmod(self.starts_on.month - 1 + index, 12)
                year, month = self.starts_on.year + year, month + 1
                day = monthrange(year, month)[1]
                day = self.starts_on.replace(year=year, month=month, day=min(self.day_of_month, day))
                if day.replace(day=1) > last:
                    return
                if first <= day <= last:
                    yield day
                index += step

    def next_date(self, after):
        """The first day of the rule after `after`; None when it has ended. One period of the rule from its first
        possible day always holds the next one."""
        first = max(after + timedelta(days=1), self.starts_on)
        period = {Frequency.DAILY: 1, Frequency.WEEKLY: 7, Frequency.MONTHLY: 31}[self.frequency] * (self.interval + 1)
        return next(self.dates(first, first + timedelta(days=period)), None)


class TaskSeriesAssignee(models.Model):
    """Who a recurring task's tasks are for: a person who can sign in (plain rows of the recurring task)."""

    series = models.ForeignKey(TaskSeries, on_delete=models.CASCADE, related_name='assignee_links')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')

    class Meta:
        db_table = 'task_series_assignees'
        constraints = [models.UniqueConstraint(fields=['series', 'user'], name='uq_task_series_assignees')]


class TaskSeriesChecklistItem(models.Model):
    """A line of a recurring task's checklist, copied to every task it plans (core.crud.RowList rows, in the
    order they were saved)."""

    id = models.BigAutoField(primary_key=True)   # the order of the lines
    series = models.ForeignKey(TaskSeries, on_delete=models.CASCADE, related_name='checklist')
    text = models.CharField(_('Checklist item'), max_length=300)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')

    class Meta:
        db_table = 'task_series_checklist_items'
        ordering = ['id']
        constraints = [models.CheckConstraint(condition=Q(text__regex=TITLE), name='chk_task_series_checklist_text')]

    def __str__(self):
        return self.text


# ---- tasks ---------------------------------------------------------------------------------------------
class Task(AtPlace, AuditedModel):
    """A job at one place for one or more people, due on a day on the clock of the place's site: open, in
    progress (who started it and when), done (who completed it and when) or cancelled (who, when and why).
    Overdue is worked out on read (tasks/read.py), never stored (TSK-09).

    Its links say what deleting the other record does (core.softdelete): a task keeps its place, batch
    and recurring task (DO_NOTHING): it stays in the lists, shows them as deleted, and shows them again when
    they are restored (owner decision 7: an open task does not hold its place's delete back). A planned task
    of a recurring task that nobody has touched goes with the recurring task (`deleted_with`)."""

    title = models.CharField(_('Title'), max_length=200)
    description = models.TextField(_('Description'), blank=True)
    category = models.CharField(_('Category'), max_length=20, choices=Category.choices, default=Category.OTHER)
    priority = models.CharField(_('Priority'), max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(_('Status'), max_length=12, choices=Status.choices, default=Status.OPEN)
    due_date = models.DateField(_('Due date'))
    due_time = models.TimeField(_('Due time'), null=True, blank=True)
    site = place_link(Site, _('Site'), 'tasks', models.DO_NOTHING)
    production_department = place_link(ProductionDepartment, _('Production department'), 'tasks', models.DO_NOTHING)
    system = place_link(System, _('System'), 'tasks', models.DO_NOTHING)
    unit = place_link(Tank, _('Unit'), 'tasks', models.DO_NOTHING)
    equipment = place_link(Equipment, _('Equipment'), 'tasks', models.DO_NOTHING)
    batch = models.ForeignKey(Batch, null=True, blank=True, on_delete=models.DO_NOTHING, related_name='tasks',
                              verbose_name=_('Batch'))
    assignees = models.ManyToManyField(settings.AUTH_USER_MODEL, through='TaskAssignee', related_name='tasks',
                                       verbose_name=_('Assignees'))
    series = models.ForeignKey(TaskSeries, null=True, blank=True, on_delete=models.DO_NOTHING, related_name='tasks',
                               verbose_name=_('Recurring task'))
    # The day of the recurring task's rule this task is (it may be moved to another due date since).
    occurrence_date = models.DateField(_('Planned for'), null=True, blank=True, editable=False)
    started_at = models.DateTimeField(_('Started at'), null=True, blank=True, editable=False)
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name='+', editable=False, verbose_name=_('Started by'))
    completed_at = models.DateTimeField(_('Completed at'), null=True, blank=True, editable=False)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name='+', editable=False, verbose_name=_('Completed by'))
    completion_note = models.CharField(_('Completion note'), max_length=1000, blank=True, editable=False)
    cancelled_at = models.DateTimeField(_('Cancelled at'), null=True, blank=True, editable=False)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name='+', editable=False, verbose_name=_('Cancelled by'))
    cancel_reason = models.CharField(_('Reason for cancelling'), max_length=500, blank=True, editable=False)

    objects = TaskManager()
    all_objects = TaskQuerySet.as_manager()

    kept_note = _('They stay in the task lists, which show this as deleted, and show it again when it is restored.')

    class Meta:
        db_table = 'tasks'
        ordering = ['due_date', F('due_time').asc(nulls_last=True), 'title']
        verbose_name = _('task')
        verbose_name_plural = _('tasks')
        constraints = [
            models.CheckConstraint(condition=one_place(), name='chk_tasks_one_place', violation_error_message=ONE_PLACE),
            models.CheckConstraint(condition=Q(title__regex=TITLE), name='chk_tasks_title'),
            models.CheckConstraint(condition=Q(category__in=Category.values), name='chk_tasks_category'),
            models.CheckConstraint(condition=Q(priority__in=Priority.values), name='chk_tasks_priority'),
            models.CheckConstraint(condition=Q(status__in=Status.values), name='chk_tasks_status'),
            # In progress says who started it and when; an open task was not started (or was reopened).
            models.CheckConstraint(condition=Q(started_at__isnull=True, started_by__isnull=True)
                                   | Q(started_at__isnull=False, started_by__isnull=False), name='chk_tasks_started'),
            models.CheckConstraint(condition=~Q(status=Status.IN_PROGRESS) | Q(started_at__isnull=False),
                                   name='chk_tasks_in_progress_started'),
            models.CheckConstraint(condition=~Q(status=Status.OPEN) | Q(started_at__isnull=True),
                                   name='chk_tasks_open_not_started'),
            # Done exactly when someone completed it, at a time; a note only then.
            models.CheckConstraint(
                condition=Q(status=Status.DONE, completed_at__isnull=False, completed_by__isnull=False)
                | (~Q(status=Status.DONE) & Q(completed_at__isnull=True, completed_by__isnull=True, completion_note='')),
                name='chk_tasks_done'),
            # Cancelled exactly when someone cancelled it, at a time, with a reason.
            models.CheckConstraint(
                condition=Q(status=Status.CANCELLED, cancelled_at__isnull=False, cancelled_by__isnull=False,
                            cancel_reason__regex=TITLE)
                | (~Q(status=Status.CANCELLED) & Q(cancelled_at__isnull=True, cancelled_by__isnull=True,
                                                   cancel_reason='')),
                name='chk_tasks_cancelled'),
            # A recurring task's task says which day of its rule it is, and there is one per day.
            models.CheckConstraint(condition=Q(series__isnull=True, occurrence_date__isnull=True)
                                   | Q(series__isnull=False, occurrence_date__isnull=False), name='chk_tasks_occurrence'),
            models.UniqueConstraint(fields=['series', 'occurrence_date'], condition=Q(series__isnull=False),
                                    name='uq_tasks_series_occurrence'),
        ]
        indexes = [models.Index(fields=['status', 'due_date'], name='tasks_status_due_idx')]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        errors = {}
        self.clean_place(errors)
        if self.batch_id and self.equipment_id:
            errors['batch'] = _('A batch goes with a unit, a system, a production department or a site, not with '
                                'equipment.')
        if errors:
            raise ValidationError(errors)

    @property
    def is_open(self):
        return self.status in OPEN_STATUSES

    @classmethod
    def planned(cls, tasks):
        """The tasks of `tasks` that are only their recurring task's plan: untouched (open, never edited, no line
        ticked, no note) and due on their site's today or later. One rule for every place that asks (deleting,
        changing or pausing a recurring task)."""
        ticked = TaskChecklistItem.objects.filter(task=OuterRef('pk'), done_at__isnull=False)
        noted = TaskNote.objects.filter(task=OuterRef('pk'))
        candidates = list(tasks.filter(series__isnull=False, status=Status.OPEN, version=1)
                          .exclude(Exists(ticked)).exclude(Exists(noted)).with_site())
        sites = Site.all_objects.in_bulk({task.site_key for task in candidates if task.site_key})
        return [task for task in candidates if task.due_date >= site_today(sites.get(task.site_key))]

    @classmethod
    def deleted_with(cls, link, target):
        """A recurring task takes its planned tasks with it (`planned`); every other task stays."""
        if link != 'series':
            return cls.objects.none()
        return cls.planned(cls.objects.filter(series=target))


class TaskAssignee(models.Model):
    """Who a task is for: a person who can sign in (plain rows of the task). Users are deactivated, never
    deleted, so the link can protect them."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='assignee_links')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')

    class Meta:
        db_table = 'task_assignees'
        constraints = [models.UniqueConstraint(fields=['task', 'user'], name='uq_task_assignees')]


class TaskChecklistItem(models.Model):
    """A line of a task's checklist and whether it is done, by whom and when (plain rows of the task). The
    list is edited as a whole (core.crud.RowList) until the first line is ticked; a tick is its own logged
    write (tasks.services.tick)."""

    id = models.BigAutoField(primary_key=True)   # the order of the lines
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='checklist')
    text = models.CharField(_('Checklist item'), max_length=300)
    done_at = models.DateTimeField(null=True, blank=True, editable=False)
    done_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                related_name='+', editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')

    class Meta:
        db_table = 'task_checklist_items'
        ordering = ['id']
        constraints = [
            models.CheckConstraint(condition=Q(text__regex=TITLE), name='chk_task_checklist_text'),
            models.CheckConstraint(condition=Q(done_at__isnull=True, done_by__isnull=True)
                                   | Q(done_at__isnull=False, done_by__isnull=False), name='chk_task_checklist_done'),
        ]

    def __str__(self):
        return self.text


class TaskNote(models.Model):
    """A note on a task by a person who can read it: part of the task's record, never edited or removed
    (tasks.services.add_note is its only writer), and in the activity log."""

    MAX_LENGTH = 4000

    id = models.BigAutoField(primary_key=True)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='notes')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    body = models.CharField(_('Note'), max_length=MAX_LENGTH)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'task_notes'
        ordering = ['created_at', 'id']
        constraints = [models.CheckConstraint(condition=Q(body__regex=TITLE), name='chk_task_notes_body')]

    def __str__(self):
        return self.body
