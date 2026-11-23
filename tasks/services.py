"""The one write path of the tasks besides creating, editing and deleting them on their pages (core.crud):
starting, completing, cancelling and reopening a task, ticking a line of its checklist, adding a note, and the
recurring tasks' planned tasks. The pages call these functions; later the API and the assistants call the same
ones. Each runs in one transaction with the task (or the recurring task) locked, and logs what it changed in
English (core.audit), so a status changes only here, with who and when (the source's update could set a task
done without either, TSK-10).

Who may do what (owner decision 8: whoever created a task has no rights of their own):
- start, complete, tick: a person the task is for, or whoever may edit tasks;
- cancel, reopen: whoever may edit tasks;
- add a note: whoever may read tasks (the view checks it).

A refusal raises ValidationError (a dict: 'note', 'reason', 'body' or NON_FIELD_ERRORS) or PermissionDenied;
nothing is written."""
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import NON_FIELD_ERRORS, PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy

from core import audit
from core.models import AuditLog
from farm.clocks import clocks
from farm.stock.dates import site_today

from . import places, read
from .models import OPEN_STATUSES, Status, Task, TaskChecklistItem, TaskNote, TaskSeries

EDIT = 'tasks.change_task'
LOCATION = gettext_lazy('Location')
CHECKLIST = gettext_lazy('Checklist')
NOTE = gettext_lazy('Note')
# What the activity log keeps of a task, besides its place.
LOGGED = ['title', 'description', 'category', 'priority', 'status', 'due_date', 'due_time']
LOGGED_AFTER = ['batch', 'assignees', 'started_by', 'completed_by', 'completion_note', 'cancelled_by', 'cancel_reason']
# A person's free text on a task: the log says that it was given, replaced or cleared, never its words (it may name a
# person, and nobody can erase from the log; owner decision F-061, 2026-11-10). A task's note (`add_note`) is kept the
# same way. The words stay on the task, for who reads it: also after a reopening, which clears the completion note and
# the reason on the task and keeps each as a note (`reopen`).
PRIVATE = ('description', 'completion_note', 'cancel_reason')
SERIES_PRIVATE = ('description',)     # a recurring task's description is the same free text
SERIES_LOGGED = ['title', 'description', 'category', 'priority']
SERIES_LOGGED_AFTER = ['assignees', 'frequency', 'interval', 'weekdays', 'day_of_month', 'due_time', 'starts_on',
                       'ends_on', 'is_active']


# ---- the activity log --------------------------------------------------------------------------------
def place_text(place):
    """A place as the activity log keeps it, in English: "T-01 · Tank 1 (Unit)"."""
    if place is None:
        return None
    return f'{places.label(place)} ({audit.english(places.kind_label(place))})'


def snapshot(task):
    """What the activity log compares for a task; build it inside audit.source_language()."""
    values = audit.snapshot(task, LOGGED, private=PRIVATE)
    values[str(LOCATION)] = place_text(task.place)
    values.update(audit.snapshot(task, LOGGED_AFTER, private=PRIVATE))
    return values


def series_snapshot(series):
    """What the activity log compares for a recurring task; build it inside audit.source_language()."""
    values = audit.snapshot(series, SERIES_LOGGED, private=SERIES_PRIVATE)
    values[str(LOCATION)] = place_text(series.place)
    values.update(audit.snapshot(series, SERIES_LOGGED_AFTER))
    return values


def checklist_text(item):
    """A checklist line as the log keeps it: ☑ done, ☐ not."""
    return f'{"☑" if item.done_at else "☐"} {item.text}'


# ---- who may do what ---------------------------------------------------------------------------------
def is_for(user, task):
    return task.assignees.filter(pk=user.pk).exists()


def may_work_on(user, task):
    """Start, complete or tick: a person the task is for, or whoever may edit tasks."""
    return user.has_perm(EDIT) or is_for(user, task)


def _locked(task):
    return (Task.objects.select_for_update(of=('self',))
            .select_related('site', 'production_department', 'system', 'unit', 'equipment', 'batch')
            .get(pk=task.pk))


def _changed(user, task, before):
    """Saves a change of the task's own fields as an edit by `user` (a new version) and logs it."""
    task.version += 1
    task.updated_by = user
    task.save()
    with audit.source_language():
        audit.record_update(user, task, before, snapshot(task))
    return task


def _before(task):
    with audit.source_language():
        return snapshot(task)


# ---- a task's status ---------------------------------------------------------------------------------
def start(user, task):
    """Open → in progress, with who and when."""
    with transaction.atomic():
        task = _locked(task)
        if not may_work_on(user, task):
            raise PermissionDenied
        if task.status != Status.OPEN:
            raise ValidationError({NON_FIELD_ERRORS: _('Only an open task can be started.')})
        before = _before(task)
        task.status, task.started_at, task.started_by = Status.IN_PROGRESS, timezone.now(), user
        return _changed(user, task, before)


def complete(user, task, note=''):
    """Open or in progress → done, with who, when and an optional note."""
    note = note.strip()
    with transaction.atomic():
        task = _locked(task)
        if not may_work_on(user, task):
            raise PermissionDenied
        if task.status not in OPEN_STATUSES:
            raise ValidationError({NON_FIELD_ERRORS: _('This task is already %(status)s.') % {
                'status': str(task.get_status_display()).lower()}})
        before = _before(task)
        task.status, task.completed_at, task.completed_by, task.completion_note = (
            Status.DONE, timezone.now(), user, note)
        return _changed(user, task, before)


def cancel(user, task, reason):
    """Open or in progress → cancelled, with who, when and why. Needs Edit on tasks."""
    reason = reason.strip()
    with transaction.atomic():
        task = _locked(task)
        if not user.has_perm(EDIT):
            raise PermissionDenied
        if task.status not in OPEN_STATUSES:
            raise ValidationError({NON_FIELD_ERRORS: _('This task is already %(status)s.') % {
                'status': str(task.get_status_display()).lower()}})
        if not reason:
            raise ValidationError({'reason': _('Say why it is cancelled.')})
        before = _before(task)
        task.status, task.cancelled_at, task.cancelled_by, task.cancel_reason = (
            Status.CANCELLED, timezone.now(), user, reason)
        return _changed(user, task, before)


def reopen(user, task):
    """Done or cancelled → open, the completion, the cancellation and the start cleared (the source left the
    completer on a reopened task until it fixed it, FARM-HIGH-056). Needs Edit on tasks. What the person wrote when
    they closed it (the completion note, the reason for cancelling) is not lost with the clearing: each is kept on the
    task as a note by its writer, marked as what it was (TaskNote.kind). The log has only their digests, so this is
    where the words live on; only the erasure procedure removes them (docs/erasure.md)."""
    with transaction.atomic():
        task = _locked(task)
        if not user.has_perm(EDIT):
            raise PermissionDenied
        if task.status in OPEN_STATUSES:
            raise ValidationError({NON_FIELD_ERRORS: _('This task is open already.')})
        before = _before(task)
        for kind, words, writer in ((TaskNote.Kind.COMPLETION_NOTE, task.completion_note, task.completed_by),
                                    (TaskNote.Kind.CANCEL_REASON, task.cancel_reason, task.cancelled_by)):
            if words.strip():
                TaskNote.objects.create(task=task, author=writer or user, body=words, kind=kind)
        task.status = Status.OPEN
        task.started_at = task.started_by = task.completed_at = task.completed_by = None
        task.cancelled_at = task.cancelled_by = None
        task.completion_note = task.cancel_reason = ''
        return _changed(user, task, before)


# ---- the checklist and notes ---------------------------------------------------------------------------
def tick(user, item, done):
    """Sets a line done or not done (an absolute set: sent twice, it changes nothing the second time), with who
    and when; refused on a task that is done or cancelled. Logged on the task."""
    with transaction.atomic():
        task = _locked(item.task)
        if not may_work_on(user, task):
            raise PermissionDenied
        if task.status not in OPEN_STATUSES:
            raise ValidationError({NON_FIELD_ERRORS: _('The task is %(status)s: its checklist can no longer be '
                                                       'ticked.') % {'status': str(task.get_status_display()).lower()}})
        item = TaskChecklistItem.objects.select_for_update().get(pk=item.pk, task=task)
        if bool(item.done_at) == bool(done):
            return item
        before = checklist_text(item)
        item.done_at, item.done_by = (timezone.now(), user) if done else (None, None)
        item.save(update_fields=['done_at', 'done_by'])
        with audit.source_language():
            audit.record(user, AuditLog.Action.UPDATE, task, {str(CHECKLIST): [before, checklist_text(item)]})
        return item


def add_note(user, task, body):
    """A note on the task, kept on it for good (never edited or removed: task notes are part of the work record). The
    activity log says that a note was added, by whom and when, with the keyed digest of its text and never the text
    (core.audit.private): the words are read on the task, and the log, which nobody can erase from, holds none."""
    body = body.strip()
    if not body:
        raise ValidationError({'body': _('Write the note first.')})
    if len(body) > TaskNote.MAX_LENGTH:
        raise ValidationError({'body': _('A note is at most %(count)d characters.') % {'count': TaskNote.MAX_LENGTH}})
    with transaction.atomic():
        task = _locked(task)
        note = TaskNote.objects.create(task=task, author=user, body=body)
        with audit.source_language():
            audit.record(user, AuditLog.Action.UPDATE, task, {str(NOTE): [None, audit.private(body)]})
        return note


# ---- recurring tasks -------------------------------------------------------------------------------------
def _locked_series(series):
    return (TaskSeries.objects.select_for_update(of=('self',))
            .select_related('site', 'production_department__site', 'system__site', 'unit__production_department__site',
                            'equipment__production_department__site')
            .filter(pk=series.pk).first())


def materialise(series):
    """Makes the tasks of an active recurring task from the day after the last one made (from its first day,
    the first time) up to TASK_HORIZON_DAYS after its site's today, but never more than TASK_BACKFILL_DAYS
    back: missed days after a gap are made and are overdue, which is the truth about them (owner decision 3).
    A day that has a task already, live or deleted, is skipped: a task deleted by a person stays deleted. Each
    task gets the recurring task's title, place, people who can still read tasks, due time and checklist; it is
    made by nobody (`created_by` empty: the recurring task made it) and logged as made by the system. One
    recurring task per transaction, locked, so two pages reading at once make each day once (and the unique key
    of a recurring task's day is the backstop). Returns the tasks made."""
    with transaction.atomic():
        series = _locked_series(series)
        if series is None or not series.is_active:
            return []
        today = site_today(series.place_site)
        last = today + timedelta(days=settings.TASK_HORIZON_DAYS)
        first = series.generated_until + timedelta(days=1) if series.generated_until else series.starts_on
        first = max(first, today - timedelta(days=settings.TASK_BACKFILL_DAYS))
        if first > last:
            return []
        days = list(series.dates(first, last))
        taken = set(Task.all_objects.filter(series=series, occurrence_date__in=days)
                    .values_list('occurrence_date', flat=True))
        people = list(read.readers().filter(pk__in=series.assignees.values('pk')))
        lines = list(series.checklist.values_list('text', flat=True))
        made = []
        for day in days:
            if day in taken:
                continue
            task = Task(title=series.title, description=series.description, category=series.category,
                        priority=series.priority, due_date=day, due_time=series.due_time, series=series,
                        occurrence_date=day)
            task.set_place(series.place)
            task.save()
            task.assignees.set(people)
            TaskChecklistItem.objects.bulk_create([TaskChecklistItem(task=task, text=text) for text in lines])
            with audit.source_language():
                audit.record_create(None, task, snapshot(task))
            made.append(task)
        series.generated_until = last
        series.save(update_fields=['generated_until'])
        return made


def materialise_due():
    """Makes the planned tasks of every active recurring task that is behind (called before the task pages and
    the overview read, and by `manage.py generate_tasks`)."""
    latest = max(clock.today for clock in clocks()) + timedelta(days=settings.TASK_HORIZON_DAYS)
    behind = TaskSeries.objects.filter(is_active=True).exclude(generated_until__gte=latest)
    return [task for series in behind for task in materialise(series)]


def withdraw(user, series):
    """Removes the tasks of a recurring task that are only its plan (Task.planned: untouched, due today or
    later) and logs each as deleted by `user`. They are its projection: no one did anything with them."""
    for task in Task.planned(Task.objects.filter(series=series)):
        with audit.source_language():
            audit.record_delete(user, task)
        task.delete()


def replan(user, series, created=False):
    """After a recurring task is created, changed (its checklist too) or paused or resumed: its planned tasks
    from today on follow the rule as it is now. A new one is planned from its first day (and back at most
    TASK_BACKFILL_DAYS); a changed one from today, so a change never makes tasks for days already past, and a
    resumed one does not make the days it was paused. Tasks someone touched stay as they are."""
    with transaction.atomic():
        series = _locked_series(series)
        if series is None:
            return
        if not created:
            withdraw(user, series)
            series.generated_until = site_today(series.place_site) - timedelta(days=1)
            series.save(update_fields=['generated_until'])
        materialise(series)
