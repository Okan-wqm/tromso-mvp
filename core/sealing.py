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
from contextlib import contextmanager
from dataclasses import dataclass, field

from django.core import checks
from django.db import models
from django.db.models import Exists, OuterRef, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

# The parts of a confidential piece of work a grant can open (experiments: the owner's five).
PARTS = ('design', 'results', 'systems', 'data', 'water')
# A seal's class: a farm fact (the fish, their feed, water, health; an `oversee` holder sees it) or science (the design
# and the results; only the team and the grantees).
FACT, SCIENCE = 'fact', 'science'
# A seal's mode: `row` filters the model's rows; `exempt` leaves them, with a written reason.
ROW, EXEMPT = 'row', 'exempt'
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
    Oversee). A superuser sees everything (each such read of science is logged, `support`)."""
    user_id: int | None = None
    username: str = ''
    is_super: bool = False
    oversee: bool = False
    team: frozenset = frozenset()
    granted: dict = field(default_factory=dict)

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


class _System:
    """Reading as the system: every row, for a named reason."""

    def __init__(self, reason):
        self.reason = reason


class _Lazy:
    """A request's viewer, loaded on its first sealed read (one query) and kept for the rest of the request."""

    def __init__(self, user):
        self.user = user
        self.loaded = None

    def get(self):
        if self.loaded is None:
            self.loaded = load(self.user)
        return self.loaded


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
    """The app that knows what a cell is (experiments) gives: `load(user) -> Viewer`, `cells()` (a queryset of the
    sealed cells: unit, system, from_on, until_on, work id) and `hidden_work(viewer, part)` (a queryset of the ids of
    the sealed work the viewer may not read for that part)."""
    global _provider
    _provider = provider


def provider():
    return _provider


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
    - `mode`: ROW filters the rows; EXEMPT does not, and `reason` says why."""
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
    if seal.mode == EXEMPT and not seal.reason:
        raise ValueError(f'{model._meta.label}: an exempt model says why.')
    _registry[model._meta.label] = seal
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


def check_registry(app_configs=None, models=None, **kwargs):
    """E101: a model reaching a unit, a system or another keyed record without a seal. E102: a filtering seal whose
    model has a manager without SealedMixin."""
    from django.apps import apps
    model_list = models if models is not None else apps.get_models()
    errors = [checks.Error(f'{label} reaches a unit, a system or another sealed record and declares no seal.',
                           hint='Declare it with core.sealing.declare(...) in its app\'s ready(), or exempt it with a '
                                'reason.', id='core.E101')
              for label in undeclared(model_list)]
    for seal in registry():
        if seal.filters:
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
        today = timezone.localdate()
        return Q(from_on__lte=today, until_on__gte=today)
    if isinstance(day, tuple):
        first, last = day
        last_ref = _day_ref(model, last)
        condition = Q(until_on__gte=_day_ref(model, first))
        return condition & (Q(from_on__lte=last_ref) if last_ref is not None else Q())
    ref = _day_ref(model, day)
    return Q(from_on__lte=ref, until_on__gte=ref)


def _day_ref(model, path):
    target = _field_path(model, path)[-1]
    ref = OuterRef(path)
    if isinstance(target, models.DateTimeField):
        return TruncDate(ref)
    return ref


def _paths(value):
    return (value,) if isinstance(value, str) and value else tuple(value or ())


def hidden(seal, current, part=None):
    """The condition (a Q) that is true for the rows of `seal.model` hidden from `current`; None when none are."""
    if current is None or current.is_super:
        return None
    if seal.cls == FACT and current.oversee and seal.work is None:
        return None
    part = part or seal.part
    conditions = []
    if seal.work is not None and _provider is not None:
        lookup = f'{seal.work}__pk__in' if seal.work else 'pk__in'
        conditions.append(Q(**{lookup: _provider.hidden_work(current, part)}))
    if (seal.unit or seal.system) and _provider is not None:
        seen = list(current.sees(part))
        cells = _provider.cells().exclude(work__in=seen) if seen else _provider.cells()
        days = _day_filter(seal.model, seal.day)
        for target, paths in (('unit', _paths(seal.unit)), ('system', _paths(seal.system))):
            for path in paths:
                lookup, ref = _correlated(seal.model, path, target)
                conditions.append(Q(Exists(cells.filter(days, **{lookup: ref}))))
    for link in seal.via:
        parent = seal.model._meta.get_field(link).related_model
        shown = parent._default_manager.filter(pk=OuterRef(link))
        conditions.append(Q(**{f'{link}__isnull': False}) & ~Q(Exists(shown)))
    if seal.any_of:
        child, link = _child(seal.any_of)
        children = child._base_manager.filter(**{link: OuterRef('pk')})
        shown = child._default_manager.filter(**{link: OuterRef('pk')})
        conditions.append(Q(Exists(children)) & ~Q(Exists(shown)))
    if seal.hidden_with:
        child, link = _child(seal.hidden_with)
        child_hidden = hidden(seal_of(child), current, part)
        if child_hidden is not None:
            conditions.append(Q(Exists(child._base_manager.filter(child_hidden, **{link: OuterRef('pk')}))))
    if not conditions:
        return None
    result = conditions[0]
    for condition in conditions[1:]:
        result |= condition
    return result


def _child(spec):
    from django.apps import apps
    label, link = spec
    return apps.get_model(label), link


def narrow(queryset, part=None):
    """`queryset` without the rows hidden from the viewer of the moment."""
    seal = seal_of(queryset.model)
    if seal is None or not seal.filters:
        return queryset
    condition = hidden(seal, viewer(), part)
    return queryset if condition is None else queryset.exclude(condition)


class SealedMixin:
    """A manager whose rows are narrowed for the viewer of the moment (the model's seal says how)."""

    def get_queryset(self):
        return narrow(super().get_queryset())


def sealed(manager_class):
    """`manager_class` with the seal: SealedMixin first, so its narrowing wraps whatever the manager reads."""
    return type(f'Sealed{manager_class.__name__}', (SealedMixin, manager_class), {})


# ---- reading as someone, the request ----------------------------------------------------------------------------
class SealingMiddleware:
    """Gives each request its viewer (the signed-in person, loaded on the first sealed read) and keeps it for a streamed
    answer's generator. An answer to someone who reads confidential work is never cached."""

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
        if lazy.loaded is not None and lazy.loaded.any_grant:
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
def log_access(kind, entity_type, entity_id, part='', route=''):
    """One row of the read log (core.AccessEvent) for the viewer of the moment: a view, an export, a refusal, an
    `oversee` read of a cell's facts or a superuser's `support` read. Reading as the system logs nothing."""
    from .models import AccessEvent
    current = viewer()
    if current is None or current.user_id is None:
        return None
    return AccessEvent.objects.create(user_id=current.user_id, user_name=current.username, kind=kind,
                                      entity_type=entity_type, entity_id=str(entity_id), part=part, route=route[:120])
