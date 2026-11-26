"""Confidential cells, the framework: who is looking (the viewer), the registry of sealed models, and the one predicate
made from it that every sealed model's managers apply.

A cell is a unit or a system booked to a confidential piece of work for a range of days (experiments: a sealed
experiment's placements and system bookings). A record on a cell, dated inside it, does not exist for someone the work's
owner has not granted: no page, list, count, export, choice or search shows it. This module knows nothing of experiments:
the provider that knows what a cell is and who is granted registers itself (experiments/sealing.py, `register_provider`),
and each app declares how its models are sealed (`declare`, from its AppConfig.ready).

The rule is applied in one place, the managers: a model declared with a filtering seal gets `SealedMixin` on its managers
(`objects` and `all_objects`), so every read through them is narrowed for the viewer of the moment. Django's base manager,
which following a link to one record uses (`movement.unit`), is not narrowed: a visible row never points at a sealed
record because a leaf is sealed by the same cell as its master (the tests prove it per link).

Fail closed: a read of a sealed model with no viewer and no `system(...)` raises `NoViewer`. A request gets its viewer
from `SealingMiddleware`; management commands (but runserver) and the test runner read as the system (`enter_process_system`);
a few named reads that must count everything (a legal figure, a fold, the delete plan, the booking check) run inside
`system(reason)`, and a test names every such call site."""
import contextvars
from datetime import date
from contextlib import contextmanager
from dataclasses import dataclass, field

from django.core import checks
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Exists, ExpressionWrapper, F, Func, OuterRef, Q, Value
from django.db.models.functions import Cast, Coalesce, Now


# The parts of a confidential piece of work a grant can open (experiments: the owner's five).
PARTS = ('design', 'results', 'systems', 'data', 'water')
# A seal's class: a farm fact (the fish, their feed, water, health; an `oversee` holder sees it) or science (the design
# and the results; only the team and the grantees).
FACT, SCIENCE = 'fact', 'science'
# A seal's mode: `row` filters the model's rows; `exempt` leaves them, with a written reason.
ROW, EXEMPT, ABOUT = 'row', 'exempt', 'about'
# The records a cell reaches. A model with a link to one of these, directly or through other models, must declare its seal.
KEYED = ('farm.Tank', 'farm.System', 'farm.Batch', 'farm.SamplingPoint', 'farm.Equipment', 'farm.StockOperation',
         'farm.HealthEvent', 'sensors.Binding', 'sensors.Channel', 'tasks.Task', 'reports.Report',
         'experiments.Experiment')


class NoViewer(RuntimeError):
    """A sealed model was read with nobody looking: no request's viewer, no `as_viewer`, no `system(...)`."""


@dataclass(frozen=True)
class Viewer:
    """Who is looking and what they are granted: the ids of the pieces of work they are in the team of (every part) and,
    per part, those they hold a live grant of. `oversee`: they see the farm facts of every cell (the role matrix's
    Oversee). A superuser (the platform admin) sees everything but `barred`: the work whose owner keeps it from the
    platform admin too (owner amendment C4); each read of science they are not granted is logged, `support`."""
    user_id: int | None = None
    username: str = ''
    is_super: bool = False
    oversee: bool = False
    team: frozenset = frozenset()
    granted: dict = field(default_factory=dict)
    barred: frozenset = frozenset()

    def sees(self, part):
        """The ids of the pieces of work whose `part` this viewer may read."""
        return self.team | self.granted.get(part, frozenset())

    @property
    def any_grant(self):
        """The viewer reads some confidential work (their pages are not to be cached)."""
        return bool(self.team) or any(self.granted.values())

    def everything(self):
        """The ids of every piece of work this viewer reads some part of."""
        return self.team.union(*self.granted.values())


NOBODY = Viewer()


@dataclass(frozen=True)
class Who:
    """Who is looking, known without a query: what the seal's predicate needs (the person's id and whether they are the
    platform admin). What they are granted is read inside the same SQL statement as the rows (the provider's
    subqueries), so narrowing a read costs no query of its own; the full Viewer is loaded only where Python decides
    (an experiment's own pages, the read log)."""
    user_id: int | None = None
    username: str = ''
    is_super: bool = False


def who_of(user):
    if user is None or not user.is_authenticated:
        return Who()
    return Who(user_id=user.pk, username=user.get_username(), is_super=user.is_superuser)


class _System:
    """Reading as the system: every row, for a named reason."""

    def __init__(self, reason):
        self.reason = reason


class _Lazy:
    """A request's viewer: who it is (no query), and what they are granted, loaded when Python first asks (`viewer()`)
    and kept for the rest of the request. `read` says that a sealed model was read for them."""

    def __init__(self, user):
        self.user = user
        self.light = None
        self.read = False
        self.memo = {}

    def get(self):
        return memo(('viewer',), lambda: load(self.user))

    def who(self):
        if self.light is None:
            self.light = who_of(self.user)
        self.read = True
        return self.light


_current = contextvars.ContextVar('sealing_current', default=None)
_process_reason = None


def process_reason(argv):
    """Why a process started with `argv` reads as the system: a management command but runserver (whose requests each
    have their viewer); None for runserver or no command."""
    if len(argv) < 2 or argv[1] == 'runserver':
        return None
    return f'command {argv[1]}'


def enter_process_system(reason):
    """The whole process reads as the system unless a viewer is set (manage.py's commands but runserver, the test
    runner)."""
    global _process_reason
    _process_reason = reason


def leave_process_system():
    global _process_reason
    _process_reason = None


@contextmanager
def system(reason):
    """Reads inside this block see every row: for a figure that must count everything (a legal report, a fold whose
    total a partial read would make wrong), the delete plan and the booking check. Every call site is named in
    core/tests_sealing.py."""
    token = _current.set(_System(reason))
    try:
        yield
    finally:
        _current.reset(token)


def reads_as_system(reason):
    """A decorator: the function, or every method of the class, reads as the system for `reason`. For the computation
    of a fact that must count every unit whoever asks (the medicine withdrawal's reader: fish held by a course in a
    sealed tank are held wherever they went), never for what is printed: what a page shows of the fact is read as its
    person. Each use is named among the system's readers (core/tests_sealing.py)."""
    import functools
    import inspect

    def wrapped(function):
        @functools.wraps(function)
        def inner(*args, **kwargs):
            with system(reason):
                return function(*args, **kwargs)
        return inner

    def decorate(target):
        if inspect.isfunction(target):
            return wrapped(target)
        for attribute, member in list(vars(target).items()):
            if inspect.isfunction(member):
                setattr(target, attribute, wrapped(member))
            elif isinstance(member, (staticmethod, classmethod)):
                setattr(target, attribute, type(member)(wrapped(member.__func__)))
            elif isinstance(member, property):
                setattr(target, attribute, property(*(wrapped(part) if part else None
                                                    for part in (member.fget, member.fset, member.fdel))))
        return target
    return decorate


@contextmanager
def as_viewer(user):
    """Reads inside this block are narrowed for `user` (a request does this in SealingMiddleware)."""
    token = _current.set(_Lazy(user))
    try:
        yield
    finally:
        _current.reset(token)


def capture():
    """The current reading context, to carry into a generator that runs after the request (a streamed export)."""
    return _current.get()


@contextmanager
def restore(captured):
    token = _current.set(captured)
    try:
        yield
    finally:
        _current.reset(token)


def viewer():
    """The viewer of the moment; None when reading as the system. Raises NoViewer when nobody is looking."""
    current = _current.get()
    if isinstance(current, _Lazy):
        return current.get()
    if isinstance(current, _System):
        return None
    if _process_reason is not None:
        return None
    raise NoViewer('A sealed model was read outside a request, `as_viewer` or `system(...)`.')


def who():
    """Who is looking, for the seal's predicate (no query); None when reading as the system. Raises NoViewer when nobody
    is looking."""
    current = _current.get()
    if isinstance(current, _Lazy):
        return current.who()
    if isinstance(current, _System):
        return None
    if _process_reason is not None:
        return None
    raise NoViewer('A sealed model was read outside a request, `as_viewer` or `system(...)`.')


class Viewing(models.Expression):
    """Who is looking, read when the SQL is compiled, never when the queryset is built (review F1): a queryset made at
    import or at class level (a form's choices) carries the seal, and each evaluation reads its own request's person.
    `looking`: someone is looking (false for the system); `super`: the platform admin; `user`: the person's id (NULL for
    an anonymous visitor). With nobody looking, compiling raises NoViewer: the read fails, it never shows everything."""

    contains_aggregate = False

    def __init__(self, what):
        super().__init__(output_field=models.IntegerField() if what == 'user' else models.BooleanField())
        self.what = what

    def __repr__(self):
        return f'Viewing({self.what!r})'

    def get_group_by_cols(self):
        return []

    def as_sql(self, compiler, connection):
        current = who()
        if self.what == 'user':
            return '%s', [None if current is None else current.user_id]
        flag = current is not None if self.what == 'looking' else (current is not None and current.is_super)
        return ('TRUE' if flag else 'FALSE'), []


class Sealed(models.ExpressionWrapper):
    """The seal's condition, decided when the SQL is compiled, never when the queryset is built (review F1), from the
    person's Reach (read once per request, `reach()`): FALSE for the system (a command, a named system read) and for a
    person from whom nothing is hidden, FALSE for a farm fact (`fact`) when they hold Oversee; the condition itself
    otherwise, with the hidden work's ids written in (HiddenWork). Its subqueries are compiled only then, so a read
    costs what an unsealed one does wherever no confidential work is hidden from the person (the farm's every day)."""

    def __init__(self, condition, fact=False):
        super().__init__(condition, output_field=models.BooleanField())
        self.fact = fact

    def as_sql(self, compiler, connection):
        if who() is None:
            return 'FALSE', []
        found = _reach_of_person()
        if found is not None and (not any(found.hidden.values()) or (self.fact and found.oversee)):
            return 'FALSE', []
        return super().as_sql(compiler, connection)


class HiddenWork(models.Expression):
    """The ids of the work whose `part` the person looking may not read, as the right-hand side of an `__in`: written in
    from their Reach when the SQL is compiled (literal ids; an empty set when none), or, with no Reach to read (a
    provider without one), the provider's own subquery, read in the statement."""

    contains_aggregate = False

    def __init__(self, part, subquery):
        super().__init__(output_field=subquery.model._meta.pk)
        self.part, self.subquery = part, subquery

    def __repr__(self):
        return f'HiddenWork({self.part!r})'

    def get_group_by_cols(self):
        return []

    def as_sql(self, compiler, connection):
        found = _reach_of_person()
        if found is None:
            sql, params = self.subquery.query.get_compiler(connection=connection).as_sql()
            return f'({sql})', params
        key = self.output_field
        ids = sorted(found.hidden.get(self.part, ()))
        if not ids:
            return f'(SELECT NULL::{key.db_type(connection)} WHERE FALSE)', []
        return '(' + ', '.join(['%s'] * len(ids)) + ')', [key.get_db_prep_value(key.to_python(each), connection)
                                                          for each in ids]


def _reach_of_person():
    """The Reach of the person looking, or None when the provider reads none (the condition is then compiled whole)."""
    if _provider is None or not hasattr(_provider, 'reach'):
        return None
    return _reach()


@dataclass(frozen=True)
class Reach:
    """What the change token needs of the person looking (core.audit.revision, monitoring's change_token), read in one
    statement: `hidden`, per part, the ids of the work whose part they may not read; `oversee`, they hold Oversee;
    `digest`, a short text that changes when what they read changes (a grant, a share's end, a team, an audience) and
    names nothing they may not read ('' when they read no confidential work)."""
    hidden: dict = field(default_factory=dict)
    oversee: bool = False
    digest: str = ''


SEES_ALL = Reach()


def reach():
    """The Reach of the person looking, once per request (`memo`); SEES_ALL for the system, which hides nothing. The
    seal reads the same one (`_reach`), so the change token's read of it costs no statement of its own."""
    return _reach()


def _reach():
    current = _current.get()
    if isinstance(current, _Lazy):
        # Reading what the person may read is reading the seal: the answer is made for them alone (no-store), whether
        # something turns out hidden or not, so its headers never tell which (run 45704864961).
        current.who()
    elif who() is None:
        return SEES_ALL
    if _provider is None or not hasattr(_provider, 'reach'):
        return SEES_ALL
    return memo(('reach',), lambda: _provider.reach(current.user))


def reach_key():
    """A short name for what the person looking may read of the sealed records: '' when nothing is hidden from them
    (the system's reading, and every person's on a farm with no confidential work), else a digest of the work hidden
    from them per part and of Oversee. Two people with the same key read the same rows of every sealed model, so a value
    computed from sealed records may be kept for one key and served to the other (review L3); never across keys."""
    import hashlib
    found = reach()
    if not any(found.hidden.values()):
        return ''
    text = ';'.join(f'{part}:{",".join(sorted(ids))}' for part, ids in sorted(found.hidden.items()) if ids)
    return hashlib.sha256(f'{text}|{found.oversee}'.encode()).hexdigest()[:16]


def forget():
    """What has been read of the person looking (their Reach, their Viewer, the memo) is read again on the next ask:
    called after any statement that writes a table that says who reads what (the provider's `grant_tables`, seen by the
    connections' execute wrapper whatever wrote it: a save, a queryset update, a bulk create, SQL of its own), so a read
    after it in the same request or `as_viewer` block is narrowed by what holds now. It forgets for every reading in the
    process, not only the one of the moment: a grant written inside `system(...)` or a `reads_as_system` function is
    seen by the request around it too (landing review S1)."""
    global _generation
    _generation += 1
    current = _current.get()
    if isinstance(current, _Lazy):
        current.memo.clear()


# How many times a grant has been written in this process (`forget`): a value kept before the last one is read again.
_generation = 0


def _kept_while():
    """When a value read now may be used again: until the next grant write (`_generation`), and, when read inside a
    transaction block, only while that block is open (the savepoints open now): a block rolled back may have written a
    grant the value saw, and Django says nothing of a rollback (landing review S2). One read outside a block holds until
    the next grant write."""
    from django.db import connection
    return _generation, tuple(connection.savepoint_ids) if connection.in_atomic_block else None


def _still_good(kept):
    from django.db import connection
    generation, block = kept
    if generation != _generation:
        return False
    if block is None:
        return True
    return connection.in_atomic_block and tuple(connection.savepoint_ids[:len(block)]) == block


def memo(key, compute):
    """`compute()`, kept for the rest of the request (or `as_viewer` block) under `key`: for a page that asks the
    same question of the seal for many rows (which unit codes the person may see), once."""
    current = _current.get()
    if not isinstance(current, _Lazy):
        return compute()
    kept = current.memo.get(key)
    if kept is None or not _still_good(kept[1]):
        when = _kept_while()
        kept = current.memo[key] = (compute(), when)
    return kept[0]


def system_reason():
    """Why the system is reading now ('' when someone is looking)."""
    current = _current.get()
    if isinstance(current, _System):
        return current.reason
    if current is None and _process_reason is not None:
        return _process_reason
    return ''


# ---- the provider -----------------------------------------------------------------------------------------------
_provider = None


def register_provider(provider):
    """The app that knows what a cell is (experiments) gives: `load(user) -> Viewer` (for Python's decisions),
    `cells()` (a queryset of the sealed cells: unit, system, from_on, until_on, work id), `hidden_work(part)` (a
    queryset of the ids of the work whoever is looking may not read for that part, built with Viewing so it is read
    when the statement runs) and `oversees()` (a queryset that has a row when whoever is looking holds Oversee)."""
    global _provider, _grant_tables
    _provider = provider
    _grant_tables = tuple(f'"{table}"' for table in getattr(provider, 'grant_tables', ()))
    from django.db import connections
    from django.db.backends.signals import connection_created
    connection_created.connect(_watch_grant_writes, dispatch_uid='core.sealing.watch_grant_writes')
    for connection in connections.all(initialized_only=True):
        _watch_grant_writes(connection=connection)


_grant_tables = ()
_WRITES = ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')


def _forget_after_grant_writes(execute, sql, params, many, context):
    """An execute wrapper: after a statement that writes one of the grant tables, `forget()`."""
    try:
        return execute(sql, params, many, context)
    finally:
        if (_grant_tables and isinstance(sql, str) and sql.lstrip()[:8].upper().startswith(_WRITES)
                and any(table in sql for table in _grant_tables)):
            forget()


def _watch_grant_writes(sender=None, connection=None, **kwargs):
    if _forget_after_grant_writes not in connection.execute_wrappers:
        connection.execute_wrappers.append(_forget_after_grant_writes)


def provider():
    return _provider


def work_ids(queryset):
    """The ids of the confidential work the rows of `queryset` belong to (a model sealed with `work`: the experiments
    and their own records), or [] for any other model."""
    seal = seal_of(queryset.model)
    if seal is None or seal.work is None:
        return []
    path = f'{seal.work}__pk' if seal.work else 'pk'
    return list(queryset.order_by().values_list(path, flat=True).distinct())


def note_reads(ids, route, part=''):
    """The read log of confidential work the person looking has just been shown (the provider's note_reads), from a
    place that knows only record ids: the activity log, the database viewer."""
    if _provider is not None and hasattr(_provider, 'note_reads'):
        _provider.note_reads(ids, route, part)


def load(user):
    """The viewer for `user`: nobody for an anonymous visitor."""
    if user is None or not user.is_authenticated:
        return NOBODY
    if _provider is None:
        return Viewer(user_id=user.pk, username=user.get_username(), is_super=user.is_superuser)
    return _provider.load(user)


# ---- the registry -----------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Seal:
    """How one model is sealed.

    - `unit`, `system`: the path from the model to the unit (a Tank) or the system its row lies on ('pk' for the unit or
      system itself; a many-to-many link such as a treatment's units is allowed);
    - `day`: the path to the row's day (a date or a moment), or two paths (first, last) for a row that spans days; none
      for a master record (a unit, a system), sealed while today is inside a cell;
    - `work`: the path to the confidential work's id, for the work's own records (an experiment's factors); '' for the
      work itself;
    - `via`: the links to parent rows the row is sealed with (an escape record with its stock operation): it is hidden
      when the parent named is hidden;
    - `any_of`: (model label, link) of child rows: the row is shown when one of its children is (a batch is shown while
      one of its movements is), and hidden when it has children and none is shown;
    - `hidden_with`: (model label, link) of child rows: the row is hidden while one of its children is (a sensor channel
      with a binding on a sealed cell: the conservative rule, its readings are one series);
    - `mode`: ROW filters the rows; EXEMPT does not, and `reason` says why; ABOUT is a row that names another record by
      its entity type and id (the activity log, the read log, the form keys): it is hidden when the record it names is,
      by `rows(queryset)` (core.audit.sealed_out), wherever it is read through narrow (the database viewer)."""
    model: type
    part: str = 'data'
    cls: str = FACT
    unit: object = ''
    system: object = ''
    day: object = None
    work: str | None = None
    via: tuple = ()
    any_of: tuple = ()
    hidden_with: tuple = ()
    mode: str = ROW
    reason: str = ''
    rows: object = None
    # The parts the activity log's entries about a record of the model may hold beyond `part` (an experiment's entries
    # hold its design and its places, review L6): such an entry is shown only to whoever reads every one of them.
    log_parts: tuple = ()

    @property
    def filters(self):
        return self.mode == ROW


_registry = {}


def declare(model, **options):
    """Declares how `model` is sealed (from the app's AppConfig.ready)."""
    seal = Seal(model, **options)
    if seal.mode == ROW and not (seal.unit or seal.system or seal.work is not None or seal.via or seal.any_of
                                 or seal.hidden_with):
        raise ValueError(f'{model._meta.label}: a filtering seal names a unit, a system, a work, a parent or children.')
    if seal.mode == ABOUT and seal.rows is None:
        raise ValueError(f'{model._meta.label}: a row about other records says how it is narrowed.')
    if seal.mode == EXEMPT and not seal.reason:
        raise ValueError(f'{model._meta.label}: an exempt model says why.')
    _registry[model._meta.label] = seal
    _depths.clear()
    return seal


def registry():
    return list(_registry.values())


def seal_of(model):
    return _registry.get(model._meta.concrete_model._meta.label)


def _links(model):
    for item in model._meta.get_fields():
        if (item.many_to_one or item.many_to_many or item.one_to_one) and item.concrete and item.related_model:
            yield item.related_model


def reaches_keyed(model, keyed=KEYED):
    """Whether `model` is keyed or links to a keyed record, directly or through other models."""
    seen, frontier = set(), [model]
    while frontier:
        current = frontier.pop()
        label = current._meta.label
        if label in seen:
            continue
        seen.add(label)
        if label in keyed:
            return True
        frontier.extend(related for related in _links(current) if related._meta.label not in seen)
    return False


def undeclared(model_list):
    """The labels of the models that reach a keyed record and declare no seal."""
    return [model._meta.label for model in model_list
            if not model._meta.abstract and not model._meta.proxy and reaches_keyed(model) and seal_of(model) is None]


@checks.register()
def check_registry(app_configs=None, models=None, **kwargs):
    """E101: a model reaching a unit, a system or another keyed record without a seal. E102: a filtering seal whose
    model has a manager without SealedMixin."""
    from django.apps import apps
    # Many-to-many tables Django makes on its own count too (a treatment's units: review T4, L8).
    model_list = models if models is not None else apps.get_models(include_auto_created=True)
    errors = [checks.Error(f'{label} reaches a unit, a system or another sealed record and declares no seal.',
                           hint='Declare it with core.sealing.declare(...) in its app\'s ready(), or exempt it with a '
                                'reason.', id='core.E101')
              for label in undeclared(model_list)]
    for seal in registry():
        # A many-to-many table Django makes is read through its two ends' sealed managers, or narrowed (the database
        # viewer, `narrow`): it has no manager of its own to seal.
        if seal.filters and not seal.model._meta.auto_created:
            for manager in seal.model._meta.managers:
                if not isinstance(manager, SealedMixin):
                    errors.append(checks.Error(f'{seal.model._meta.label}.{manager.name} reads past the seal.',
                                               hint='Give the manager core.sealing.SealedMixin.', id='core.E102'))
    return errors


# ---- the predicate ----------------------------------------------------------------------------------------------
def _field_path(model, path):
    """The fields a path walks ('point__unit' on a water sample: point, unit)."""
    found, current = [], model
    for name in path.split('__'):
        item = current._meta.get_field(name)
        found.append(item)
        current = item.related_model
    return found


def _correlated(model, path, target):
    """(inner lookup from a cell's `target` (unit or system), outer reference) so that a cell row matches the outer
    row's record at `path` with no join added to the outer query: 'unit' -> ('unit', OuterRef('unit')); 'point__unit'
    on a water sample -> ('unit__<points>', OuterRef('point')); 'units' (many-to-many) -> ('unit__<treatments>',
    OuterRef('pk'))."""
    if path == 'pk':
        return target, OuterRef('pk')
    fields = _field_path(model, path)
    first = fields[0]
    rest = fields[1:] if not first.many_to_many else fields
    inner = [target] + [item.related_query_name() for item in reversed(rest)]
    lookup = '__'.join(inner)
    return lookup, OuterRef(first.name if not first.many_to_many else 'pk')


def _day_filter(model, day):
    """The conditions on a cell's days for the outer row's `day`."""
    if day is None:
        today = _today()
        return Q(from_on__lte=today, until_on__gte=today)
    if isinstance(day, tuple):
        # A row that spans days (a binding, a treatment, a recurring task) meets a cell when the two overlap; an empty
        # end is open (it runs on), an empty start has always been.
        first, last = day
        first_day = Coalesce(_day_ref(model, first), Value(date.min), output_field=models.DateField())
        last_day = Coalesce(_day_ref(model, last), Value(date.max), output_field=models.DateField())
        return Q(until_on__gte=first_day, from_on__lte=last_day)
    # A row without its day (a task with no due date) lies on the cell while the cell is current.
    ref = Coalesce(_day_ref(model, day), _today(), output_field=models.DateField())
    return Q(from_on__lte=ref, until_on__gte=ref)


def _cell_day(moment):
    """THE seal's day rule in SQL (landing review 3, S4): a moment's day on the clock of the cell it is compared with,
    the cell's site's (`zone`, a column of the provider's cells), never the company's: a cell's days are its site's.
    `day_on` is the same rule in Python."""
    return Cast(Func(F('zone'), moment, function='timezone', output_field=models.DateTimeField()), models.DateField())


def day_on(moment, zone):
    """THE seal's day rule in Python: `moment`'s day on the clock of `zone` (a cell's site's): the day an alarm opened
    (experiments.sealing.keepers_of), the day a raw-data row is dated (experiments/rawdata.py). `_cell_day` is the same
    rule in SQL."""
    from django.utils import timezone
    return timezone.localtime(moment, zone).date()


def _today():
    """Today on the cell's site's clock, read by the database when the query runs (never the day the queryset was
    built)."""
    return _cell_day(Now())


def _day_ref(model, path):
    target = _field_path(model, path)[-1]
    ref = OuterRef(path)
    if isinstance(target, models.DateTimeField):
        # The moment's day on the cell's site's clock; the outer reference is given its type, which a reference to the
        # outer query does not carry.
        return _cell_day(ExpressionWrapper(ref, output_field=models.DateTimeField()))
    return ExpressionWrapper(ref, output_field=models.DateField())


def _paths(value):
    return (value,) if isinstance(value, str) and value else tuple(value or ())


def hidden(seal, part=None, depth=None):
    """The condition (a Q) that is true for the rows of `seal.model` hidden from whoever is looking when the query runs;
    None when the seal hides nothing. Nothing here knows the person: who is looking and what they are granted are
    read inside the statement when it is compiled (Viewing, the provider's subqueries)."""
    part = part or seal.part
    conditions = []
    if _provider is not None and (seal.work is not None or seal.unit or seal.system):
        hidden_work = HiddenWork(part, _provider.hidden_work(part))
        if seal.work is not None:
            lookup = f'{seal.work}__pk__in' if seal.work else 'pk__in'
            conditions.append(Q(**{lookup: hidden_work}))
        if seal.unit or seal.system:
            cells = _provider.cells().filter(work__in=hidden_work)
            days = _day_filter(seal.model, seal.day)
            for target, paths in (('unit', _paths(seal.unit)), ('system', _paths(seal.system))):
                for path in paths:
                    lookup, ref = _correlated(seal.model, path, target)
                    conditions.append(Q(Exists(cells.filter(days, **{lookup: ref}))))
    for link in seal.via:
        parent = seal.model._meta.get_field(link).related_model
        shown = _shown(parent, part, depth).filter(pk=OuterRef(link))
        conditions.append(Q(**{f'{link}__isnull': False}) & ~Q(Exists(shown)))
    if seal.any_of:
        child, link = _child(seal.any_of)
        children = unsealed(child).filter(**{link: OuterRef('pk')})
        shown = _shown(child, part, depth).filter(**{link: OuterRef('pk')})
        conditions.append(Q(Exists(children)) & ~Q(Exists(shown)))
    if seal.hidden_with:
        child, link = _child(seal.hidden_with)
        child_hidden = None if depth == 0 else hidden(seal_of(child), part, None if depth is None else depth - 1)
        if child_hidden is not None:
            conditions.append(Q(Exists(unsealed(child).filter(child_hidden, **{link: OuterRef('pk')}))))
    if not conditions:
        return None
    result = conditions[0]
    for condition in conditions[1:]:
        result |= condition
    fact = seal.cls == FACT and seal.work is None and _provider is not None
    if fact and not hasattr(_provider, 'reach'):
        # A farm fact is shown to a person who holds Oversee (the role matrix): with no Reach to read it from, read in
        # the same statement.
        result &= ~Q(Exists(_provider.oversees()))
    # The system (a command, a named system read) and a person from whom nothing is hidden see every row, and their read
    # is not made longer by the condition (Sealed).
    return Q(Sealed(result, fact=fact))


def _shown(model, part, depth):
    """The rows of a parent or child model the person may see: every row as stored, narrowed by its seal alone (`depth`
    None), or, for a bounded reading, its own condition that far. Never through a manager that also leaves rows out for
    another reason: a voided or deleted parent is not a hidden one, and a child of it stays as visible as it was
    (review W1: a voided harvest kept its record, a deleted sensor rule its alarms)."""
    if depth is None:
        return narrow(unsealed(model))
    seal = seal_of(model)
    condition = None if depth == 0 or seal is None or not seal.filters else hidden(seal, None, depth - 1)
    rows = unsealed(model)
    return rows if condition is None else rows.exclude(condition)


def unsealed(model):
    """Every row of `model` as stored, for the seal's own reads (the condition's parents and children, the stamp, the
    log's read-time rule): never through a manager, since a model's base manager may be sealed itself (base_manager_name
    = 'all_objects': the escape, harvest, delivery and opening-balance records), and narrowed it leaves out the very
    rows the seal asks for: a rule that looks for the hidden rows then finds none and hides nothing."""
    return models.QuerySet(model)


def _child(spec):
    from django.apps import apps
    label, link = spec
    return apps.get_model(label), link


# ---- the works a record lies in (the change token's stamp) ------------------------------------------------------
# A record whose works could not be read (its row or a parent's is gone): hidden from whoever has any work hidden
# (core.audit.revision).
UNKNOWN = '*'


def _links_of(seal):
    """The models a seal follows: its parents (`via`) and its children (`any_of`, `hidden_with`)."""
    found = [seal.model._meta.get_field(link).related_model for link in seal.via]
    return found + [_child(spec)[0] for spec in (seal.any_of, seal.hidden_with) if spec]


def seal_depth(model, _path=()):
    """How many parents and children deep `model`'s seal reaches before every link ends on a record sealed by its own
    cells or work (0 for such a record): read from the seals themselves, so the stamp and the activity log's read-time
    rule follow every path to its end, however long a later seal makes it (an acknowledgement: its alarm, the alarm's
    sensor event, the event's rule, the rule's channel, the channel's bindings: five; landing review L4, W2). A seal
    that leads back to itself is refused."""
    label = model._meta.label
    if not _path and label in _depths:
        return _depths[label]
    seal = seal_of(model)
    if seal is None or not seal.filters:
        return 0
    if label in _path:
        raise ValueError(f'The seals lead in a circle: {" -> ".join((*_path, label))}.')
    found = max((1 + seal_depth(linked, (*_path, label)) for linked in _links_of(seal)), default=0)
    if not _path:
        _depths[label] = found
    return found


_depths = {}        # seal_depth's answers, read again whenever a seal is declared


def _seals_reached(model, depth=None):
    """The seals of `model` and of every parent and child its seal follows (via, any_of, hidden_with), to its end."""
    depth = seal_depth(model) if depth is None else depth
    seal = seal_of(model)
    if seal is None or not seal.filters or depth < 0:
        return []
    found = [seal]
    for link in seal.via:
        found += _seals_reached(model._meta.get_field(link).related_model, depth - 1)
    for spec in (seal.any_of, seal.hidden_with):
        if spec:
            found += _seals_reached(_child(spec)[0], depth - 1)
    return found


def stamp_parts(model):
    """The parts a record of `model` is sealed with, its own and those of the parents and children its seal follows, and
    the parts its log entries hold (`log_parts`): the change token leaves out an entry about it when one of its works
    is hidden from the person for any of them."""
    seal = seal_of(model)
    return sorted({each.part for each in _seals_reached(model)} | set(seal.log_parts if seal is not None else ()))


def stamp_shows_overseer(model):
    """Whether a holder of Oversee reads every record of `model` (a farm fact all the way down its parents and
    children, core.sealing.hidden): the change token then never leaves an entry about it out for them."""
    return all(seal.cls == FACT and seal.work is None for seal in _seals_reached(model))


def works_of(model, pks, depth=None, cells=None):
    """{pk as text: set of work ids as text} for the rows `pks` of `model`, read as the system (base managers, no
    viewer): every piece of confidential work whose seal reaches the row now, whatever its audience: its own work, each
    cell it lies in (on its day; a master record today), and those of the parents (`via`) and children (`any_of`,
    `hidden_with`) its seal follows. It is the seal read the other way round, from the row to the works, along the same
    paths (`_correlated`, `_day_filter`): a superset of the works for which a viewer's seal hides the row, never less
    (core/tests_sealing.py holds the two together). It follows the seal to its end (`seal_depth`); a row that is not
    there gives UNKNOWN.

    The activity log stamps each entry with it when the entry is written (core.audit.stamp), so the change token leaves
    out a change to a record of work hidden from the person looking without reading the seal on every poll.

    `cells`: whether any cell exists (read once per call tree): with none, no row lies in a cell, and the cells are
    not looked up row by row (a farm without experiments, the alarm pass's thousands of entries)."""
    depth = seal_depth(model) if depth is None else depth
    found = {str(pk): set() for pk in pks}
    seal = seal_of(model)
    if not found or seal is None or not seal.filters:
        return found
    if depth < 0:
        return {pk: {UNKNOWN} for pk in found}
    # An id that is not one of the model's (a log entry written by hand, a record type shared by name) names no row.
    keys = {}
    for pk in found:
        try:
            keys[str(model._meta.pk.to_python(pk))] = pk
        except (ValueError, TypeError, ValidationError):
            found[pk].add(UNKNOWN)
    from django.contrib.postgres.expressions import ArraySubquery
    columns = {}
    if _provider is not None and seal.work is not None:
        columns['_work'] = models.F(f'{seal.work}__pk' if seal.work else 'pk')
    if cells is None:
        cells = _provider is not None and _provider.cells().exists()
    if cells and (seal.unit or seal.system):
        days = _day_filter(model, seal.day)
        for target, paths in (('unit', _paths(seal.unit)), ('system', _paths(seal.system))):
            for path in paths:
                lookup, ref = _correlated(model, path, target)
                columns[f'_cells{len(columns)}'] = ArraySubquery(
                    _provider.cells().filter(days, **{lookup: ref}).values('work'))
    rows = unsealed(model).filter(pk__in=list(keys)).annotate(**columns).values('pk', *columns, *seal.via)
    parents = {link: {} for link in seal.via}
    present = set()
    for row in rows:
        key = keys.get(str(row['pk']), str(row['pk']))
        present.add(key)
        for name in columns:
            value = row[name]
            found[key].update(str(each) for each in (value if isinstance(value, list) else [value]) if each is not None)
        for link in seal.via:
            if row[link] is not None:
                parents[link].setdefault(str(row[link]), []).append(key)
    for key in set(keys.values()) - present:
        found[key].add(UNKNOWN)
    for link, children in parents.items():
        theirs = works_of(model._meta.get_field(link).related_model, list(children), depth - 1, cells)
        for parent, rows_of in children.items():
            for key in rows_of:
                found[key].update(theirs[parent])
    for spec in (seal.any_of, seal.hidden_with):
        if spec:
            child, link = _child(spec)
            pairs = list(unsealed(child).filter(**{f'{link}__in': list(present)}).values_list('pk', link))
            theirs = works_of(child, [pk for pk, _parent in pairs], depth - 1, cells)
            for pk, parent in pairs:
                found[str(parent)].update(theirs[str(pk)])
    return found


def narrow(queryset, part=None):
    """`queryset` without the rows hidden from the viewer of the moment."""
    seal = seal_of(queryset.model)
    if seal is not None and seal.mode == ABOUT:
        return seal.rows(queryset)
    if seal is None or not seal.filters:
        return queryset
    if _building.get():
        # Inside HiddenRows's build (a parent's or child's manager): its condition, built now, compiled with the rest.
        condition = hidden(seal, part)
        return queryset if condition is None else queryset.exclude(condition)
    return queryset.exclude(Q(HiddenRows(seal, part)))


# While HiddenRows builds the seal's condition: the managers it reads (parents, children) add theirs built at once, so
# one statement nests one HiddenRows, never one per level (a compile inside a compile per level ran out of stack).
_building = contextvars.ContextVar('sealing_building', default=False)


class HiddenRows(models.Expression):
    """The rows of a sealed model hidden from whoever is looking, as a condition on the outer row's key, built when the
    SQL is compiled and only then: for the system, for a person from whom nothing is hidden and, for a farm fact, for a
    holder of Oversee it is FALSE and nothing of the seal is built at all; for anyone else it is `pk IN (the rows of
    `hidden(seal)`)`, a subquery of its own. Building the seal's condition (its parents' and children's managers, each
    with theirs) when a manager is touched cost more than the reads it narrowed (the alarm outbox's round: 2.5 s of
    3.7 s, run 45649043541), so it is never built for a read that does not need it."""

    contains_aggregate = False

    def __init__(self, seal, part=None, key=None):
        super().__init__(output_field=models.BooleanField())
        self.seal, self.part, self.key = seal, part, key

    def __repr__(self):
        return f'HiddenRows({self.seal.model._meta.label})'

    def get_source_expressions(self):
        return [self.key] if self.key is not None else []

    def set_source_expressions(self, expressions):
        if expressions:
            (self.key,) = expressions

    def resolve_expression(self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False):
        copy = self.copy()
        copy.key = models.F('pk').resolve_expression(query, allow_joins, reuse, summarize)
        return copy

    def get_group_by_cols(self):
        return []

    def as_sql(self, compiler, connection):
        if who() is None:
            return 'FALSE', []
        seal = self.seal
        fact = seal.cls == FACT and seal.work is None and _provider is not None
        found = _reach_of_person()
        if found is not None and (not any(found.hidden.values()) or (fact and found.oversee)):
            return 'FALSE', []
        token = _building.set(True)
        try:
            condition = hidden(seal, self.part)
            if condition is None:
                return 'FALSE', []
            rows = unsealed(seal.model).filter(condition).order_by().values('pk')
        finally:
            _building.reset(token)
        inner, inner_params = rows.query.get_compiler(connection=connection).as_sql()
        key, key_params = compiler.compile(self.key)
        return f'{key} IN ({inner})', [*key_params, *inner_params]


class SealedMixin:
    """A manager whose rows are narrowed for the viewer of the moment (the model's seal says how)."""

    def get_queryset(self):
        return narrow(super().get_queryset())


def sealed(manager_class):
    """`manager_class` with the seal: SealedMixin first, so its narrowing wraps whatever the manager reads."""
    return type(f'Sealed{manager_class.__name__}', (SealedMixin, manager_class), {})


# ---- reading as someone, the request ----------------------------------------------------------------------------
class SealingMiddleware:
    """Gives each request its viewer (the signed-in person; what they are granted is read with the rows) and keeps it
    for a streamed answer's generator. An answer made from sealed records for a signed-in person is never cached."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        lazy = _Lazy(getattr(request, 'user', None))
        token = _current.set(lazy)
        try:
            response = self.get_response(request)
        finally:
            _current.reset(token)
        if response.streaming:
            response.streaming_content = _carried(response.streaming_content, lazy)
        if lazy.read and lazy.light is not None and lazy.light.user_id is not None                 and 'Cache-Control' not in response:
            # A page made from sealed records for a signed-in person: never kept by a browser or a proxy.
            response['Cache-Control'] = 'no-store'
        return response


def _carried(content, lazy):
    """The chunks of a streamed answer, each made as the request's person."""
    chunks = iter(content)
    while True:
        token = _current.set(lazy)
        try:
            chunk = next(chunks)
        except StopIteration:
            return
        finally:
            _current.reset(token)
        yield chunk


# ---- the read log -----------------------------------------------------------------------------------------------
def log_access(kind, entity_type, entity_id, part='', route='', reason=''):
    """One row of the read log (core.AccessEvent) for the viewer of the moment: a view, an export, a refusal, an
    `oversee` read of a cell's facts or a superuser's `support` read. Reading as the system logs nothing."""
    from . import readlog
    current = viewer()
    if current is None or current.user_id is None:
        return None
    return readlog.write(current, kind, entity_type, entity_id, part, route, reason)


def log_accesses(kind, entity_type, entity_ids, part='', route='', reason=''):
    """`log_access` for several records at once, one row each (in the order given, once per record), in one statement:
    a page that shows many (the Oversee cards of a wall) logs them without a write per card."""
    from . import readlog
    current = viewer()
    entity_ids = list(dict.fromkeys(str(each) for each in entity_ids))
    if current is None or current.user_id is None or not entity_ids:
        return []
    return readlog.write_many(current, kind, entity_type, entity_ids, part, route, reason)
