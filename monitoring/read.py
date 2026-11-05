"""The monitoring cards: one live card per tank, pond or cage, composed from what the other modules derive. THE read
model of the app; nothing else reads the database for a card, and no figure is worked out here: every number on a card
comes from the read that owns it (README, Monitoring).

    sections_for(user) -> frozenset                  what a person may read (the one place that spells a permission)
    Params.from_query(query)                         the page's address: filters, occupancy, mode, the units chosen
    units_for(params, board=None) -> [Tank]          the cheap filters, one query, the farm's one order
    cards(units, user, choice, ...) -> [Card]        each unit's template (monitoring/cards/resolve.py), then ONE bulk
                                                     call per source some card needs, for all the units
    needs(resolved) -> {source: unit ids}            what the templates' widgets show, and the roll-up's fixed set
    state_of(card) -> State                          the one roll-up of a card, a ladder
    attention(cards) -> [Card]                       the cards that need a look first, for the wall's strip
    change_token(user, query, ...) -> str            what changed since the screen last looked, without reading it

The sources, each read once for every card and only for a person who may read it:
- the fish: `stock_of` (farm/stock/read.py), then the occupancy filter, so the heavy reads cover the kept units;
- the feeding: `feeding.read.figures(details, ration=True)`, one walk of the projected weight (today's ration of every
  unit, the week and corrections of the cards whose feeding widget shows the week), and `meal_lines` for why a unit
  has no ration and its drift;
- the water: `water.read.points_water`, one `latest()` (the middle point, and every active point of a card whose
  widgets show another point);
- the medicine withdrawal: the registry's one bulk answer (`harvest.views.withdrawals`), with the stock right, as on
  Production units;
- the health (open events for the state; treatments and the latest sea-lice count of a card with a health widget), the
  tasks (a card with a tasks widget) and the placement chips (a card with an experiments widget).

SOURCES is the one table of them: each with the right that reads it and whether the card can be drawn without it. The
roll-up's set (the fish, the feeding, the middle point's water, the open events) is read for every card whatever its
template, so the state never depends on the template; a source no widget of any shown card needs runs no query. An
optional source that fails (its own savepoint) leaves the cards, its widgets say "no data", and it is logged at most once
a minute; a required one that fails raises Unavailable (the fragment answers 503 and the screen keeps its last picture).
A section the person may not read is not read at all (no query), and the card says so; the state then says what it
is from. Nothing here writes, and a poll writes nothing."""
import hashlib
import logging
from dataclasses import dataclass
from functools import cached_property
from datetime import timedelta
from urllib.parse import urlencode
from uuid import UUID

from django.db import transaction
from django.utils import timezone, translation
from django.utils.timesince import timesince
from django.utils.translation import gettext as _, ngettext

from core import audit
from farm.feeding import read as feeding_read, views as feeding_views
from farm.harvest import views as harvest_views
from farm.health import read as health_read, views as health_views
from farm.models import Tank
from farm.stock import read as stock_read, views as stock_views
from farm.stock.dates import local_today
from farm.water import parameters, read as water_read, views as water_views
from farm.water.evaluate import Status
from tasks import read as tasks_read, views as tasks_views

from .cards import catalogue, render, resolve

logger = logging.getLogger(__name__)

STOCK, FEEDING, WATER, TREATMENTS, EVENTS, LICE, TASKS, CHIPS = (
    'stock', 'feeding', 'water', 'treatments', 'events', 'lice', 'tasks', 'chips')


@dataclass(frozen=True)
class Source:
    name: str
    permission: str        # the right that reads it, from the module that owns the records ('' : the provider decides)
    required: bool         # the roll-up needs it: a card is not drawn without it


SOURCES = (
    Source(STOCK, stock_views.VIEW, True), Source(FEEDING, feeding_views.VIEW, True),
    Source(WATER, water_views.VIEW, True), Source(TREATMENTS, health_views.TREATMENTS['view'], False),
    Source(EVENTS, health_views.EVENTS['view'], True), Source(LICE, health_views.COUNTS['view'], False),
    Source(TASKS, tasks_views.VIEW, False), Source(CHIPS, '', False),
)
# The sections of a card a right reads.
SECTIONS = tuple(source.name for source in SOURCES if source.permission)
# Read for every card whatever its template: what the state is worked out from.
ROLL_UP = (STOCK, FEEDING, WATER, EVENTS)
# Beyond the sources: the cards that need every active point's water, and the feeding week.
POINTS, WEEK = 'points', 'week'
# When each optional source last failed and was logged ({name: time}): at most once a minute each.
FAILED_AT = {}
FAIL_LOG_SECONDS = 60


class Unavailable(Exception):
    """A source the roll-up needs could not be read: no card can be drawn honestly."""
# What a card names as hidden: the health records are one block of the card.
HEALTH = 'health'
SIMPLE, DETAILED = 'simple', 'detailed'
MODES = (SIMPLE, DETAILED)
STOCKED, EMPTY, ALL = 'stocked', 'empty', 'all'
OCCUPANCIES = (STOCKED, EMPTY, ALL)
KINDS = tuple(Tank.Kind.values)
CRITICAL, WARNING, BLIND, NOTE, OK, EMPTY_STATE = 'critical', 'warning', 'blind', 'note', 'ok', 'empty'
# The roll-up in the order a wall reads it, worst first.
RANK = {key: rank for rank, key in enumerate((CRITICAL, WARNING, BLIND, NOTE, OK, EMPTY_STATE))}
# A change token is for this long the same whatever happens to the clock-driven figures.
TOKEN_BUCKET = 60


# ---- what a person may read ---------------------------------------------------------------------------------
def sections_for(user):
    """The sections of the card the person may read (STOCK ... TASKS): the one definition. The page, the fragment, the
    token and the tests call it; nothing else spells a permission."""
    return frozenset(source.name for source in SOURCES if source.permission and user.has_perm(source.permission))


# ---- the address -----------------------------------------------------------------------------------------------
def _uuid(value):
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError):
        return ''


@dataclass(frozen=True)
class Params:
    """What a page's address chooses: filters, occupancy (stocked by default), the all-cards mode, the cards that
    differ from it (`flip`), the units picked by hand and the board. A value that names nothing is dropped, so a stale
    link shows what it can."""
    site: str = ''
    department: str = ''
    system: str = ''
    kind: str = ''
    occupancy: str = STOCKED
    q: str = ''
    units: tuple = ()
    mode: str = ''
    flip: frozenset = frozenset()
    board: str = ''
    wall: bool = False

    @classmethod
    def from_query(cls, query):
        """From a QueryDict (or any mapping with `get` and `getlist`)."""
        return cls(
            site=_uuid(query.get('site', '')), department=_uuid(query.get('department', '')),
            system=_uuid(query.get('system', '')), kind=query.get('kind', '') if query.get('kind', '') in KINDS else '',
            occupancy=query.get('occupancy', '') if query.get('occupancy', '') in OCCUPANCIES else STOCKED,
            q=query.get('q', '').strip()[:100],
            units=tuple(sorted({_uuid(item) for value in query.getlist('units') for item in value.split(',')} - {''})),
            mode=query.get('mode', '') if query.get('mode', '') in MODES else '',
            flip=frozenset(_uuid(item) for item in query.get('flip', '').split(',') if _uuid(item)),
            board=_uuid(query.get('board', '')), wall=query.get('wall', '') == '1')

    def canonical(self, **changes):
        """The address's query, one spelling for one state (sorted, defaults left out): what the change token and the
        fragment's address are built on. `changes` replace fields first."""
        merged = {**self.__dict__, **changes}
        pairs = []
        for name in ('board', 'department', 'kind', 'mode', 'q', 'site', 'system'):
            if merged[name]:
                pairs.append((name, merged[name]))
        if merged['wall']:
            pairs.append(('wall', '1'))
        if merged['occupancy'] != STOCKED:
            pairs.append(('occupancy', merged['occupancy']))
        if merged['units']:
            pairs.append(('units', ','.join(sorted(merged['units']))))
        if merged['flip']:
            pairs.append(('flip', ','.join(sorted(merged['flip']))))
        return urlencode(sorted(pairs))


def units_for(params, board=None):
    """The units a page shows before occupancy: the cheap filters (site, department, system, kind, the units picked
    by hand or the board's, a text in the code or name), in the farm's one order (site, department, code). One query.
    A board named in the address that has no cards, or no longer exists (deleted while a wall shows it), shows no unit.
    Occupancy needs the stock, which `cards` reads."""
    if params.board and (board is None or not board.rows.all()):
        return []                                               # a board with no cards, or one that is gone, shows none
    found = Tank.objects.select_related('production_department__site', 'system')
    if params.site:
        found = found.filter(production_department__site_id=params.site)
    if params.department:
        found = found.filter(production_department_id=params.department)
    if params.system:
        found = found.filter(system_id=params.system)
    if params.kind:
        found = found.filter(kind=params.kind)
    chosen = set(params.units)
    if board is not None:
        chosen |= {str(row.unit_id) for row in board.rows.all()}
    if chosen:
        found = found.filter(pk__in=chosen)
    units = [unit for unit in found
             if not params.q or any(params.q.lower() in word.lower() for word in (unit.code, unit.name) if word)]
    units.sort(key=lambda unit: (unit.production_department.site.name if unit.production_department.site else '',
                                 unit.production_department.name, unit.code))
    return units


# ---- a card ---------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class State:
    """A card's roll-up: its rung of the ladder, why (each reason the owning read's own words), and which sections it
    was worked out from (a person who may not read the water sees a state from the stock and the feeding alone)."""
    key: str
    reasons: tuple = ()
    basis: tuple = ()
    stale: tuple = ()      # the key readings that are missing or old, for a blind card


@dataclass(frozen=True)
class Card:
    unit: object
    template: object                    # resolve.Resolved: the template it is drawn with, and why
    today: object                       # the unit's own farm-local day
    stock: object = None                # farm.stock.read.UnitStock, None when the unit holds no fish
    day: object = None                  # feeding.projection.UnitDay of today
    feeding: object = None              # feeding.read.UnitFeeding
    lines: tuple = ()                   # feeding.read.meal_lines of the day: why no ration, the drift
    drift: str = ''                     # '', 'soon' or 'now': the worst of its batches' estimates
    water: tuple = ()                   # water.read.PointWater of its points, the middle one first
    withdrawal: tuple = ()              # the medicine withdrawal blocks in force
    treatments: tuple = ()
    events: tuple = ()
    lice: object = None
    chips: tuple = ()                   # where the unit stands in work the farm does not own (farm.placements)
    tasks: object = None                # tasks.read.UnitTasks
    hidden: tuple = ()                  # what the person may not read: FEEDING, WATER, HEALTH, TASKS
    sections: frozenset = frozenset()
    failed: frozenset = frozenset()     # the optional sources that failed: their widgets say "no data"
    now: object = None

    @cached_property
    def widgets(self):
        """The widgets its template draws, in reading order (monitoring/cards/render.py)."""
        return render.build(self)

    @property
    def middle_water(self):
        """The PointWater of its middle point, or None."""
        return _middle(self)

    @cached_property
    def state(self):
        return state_of(self)

    @cached_property
    def can(self):
        """{section: whether the person may read it}, for a template."""
        return {section: section in self.sections for section in SECTIONS}

    @property
    def days_stocked(self):
        return self.stock.days(self.today) if self.stock else None

    @property
    def losses(self):
        return self.stock.losses


def _weigh(lines):
    """The worst drift of a unit's batches ('now' over 'soon')."""
    found = {line['drift'] for line in lines}
    return 'now' if 'now' in found else 'soon' if 'soon' in found else ''


def _optional(name, loader, *args):
    """An optional source read in its own savepoint: its answer, or {} and the name among the failed when it raises
    (logged at most once a minute per source). A chip, a task count or a treatment list is never a reason a card cannot
    be shown."""
    try:
        with transaction.atomic():
            return loader(*args), False
    except Exception:                                           # fail open
        now = timezone.now()
        last = FAILED_AT.get(name)
        if last is None or (now - last).total_seconds() >= FAIL_LOG_SECONDS:
            FAILED_AT[name] = now
            logger.exception('The %s source of the monitoring cards failed; its widgets say "no data".', name)
        return {}, True


def _placements(units, user):
    """{unit id: [Placement]} from the farm's placement registry (a trial's replicate), one call for all the units; none
    when the registry is not there."""
    try:
        from farm import placements
    except ImportError:
        return {}
    return placements.of(units, user)


def needs(resolved):
    """{source: unit ids} for {unit id: Resolved}: the sources of every widget of each unit's layout, the roll-up's set
    for every unit, and POINTS (every active point's water) and WEEK (the feeding week) for the cards that show them."""
    found = {source.name: set() for source in SOURCES}
    found[POINTS], found[WEEK] = set(), set()
    for unit_id, chosen in resolved.items():
        for name in ROLL_UP:
            found[name].add(unit_id)
        for widget in chosen.layout['widgets']:
            for name in catalogue.WIDGETS[widget['type']].sources:
                found[name].add(unit_id)
            opts = widget.get('opts', {})
            if (widget['type'] == 'water_table' and opts.get('points') == 'all') or \
                    widget.get('bind', {}).get('point', water_read.MIDDLE) != water_read.MIDDLE:
                found[POINTS].add(unit_id)
            if widget['type'] == 'feeding' and opts.get('week'):
                found[WEEK].add(unit_id)
    return found


def _species(own):
    return own.shares[0].batch.species_id if own is not None and own.shares else None


def cards(units, user, choice, occupancy=STOCKED, now=None):
    """[Card] of the units after the occupancy filter, each with its template (resolve.templates_for, two queries). ONE
    bulk call per source some card needs, for all the units; none for a source the person may not read. Raises
    Unavailable when a source of the roll-up fails."""
    now = now or timezone.now()
    sections = sections_for(user)
    units = list(units)
    try:
        stock = stock_read.stock_of(units) if STOCK in sections else {}
        kept = [unit for unit in units if occupancy == ALL or (unit.pk in stock) == (occupancy == STOCKED)]
        stocked = [unit for unit in kept if unit.pk in stock]
        resolved = resolve.templates_for(kept, {unit.pk: _species(stock[unit.pk]) for unit in stocked}, choice)
        need = needs(resolved)
        feeding = (feeding_read.figures({unit.pk: stock[unit.pk] for unit in stocked},
                                        details=[unit for unit in stocked if unit.pk in need[WEEK]], ration=True)
                   if FEEDING in sections and stocked else {})
        water = (water_read.points_water(kept, now, middle_only=[unit.pk for unit in kept if unit.pk not in need[POINTS]])
                 if WATER in sections and kept else {})
        withdrawals = harvest_views.withdrawals(stocked) if STOCK in sections and stocked else {}
        events = health_read.open_events(kept) if EVENTS in sections and kept else {}
    except Exception as error:
        raise Unavailable(str(error)) from error
    failed = set()

    def optional(name, loader, *args):
        wanted = [unit for unit in kept if unit.pk in need[name]]
        if not wanted or (name in SECTIONS and name not in sections):
            return {}
        found, broke = _optional(name, loader, *args, wanted)
        if broke:
            failed.add(name)
        return found

    treatments = optional(TREATMENTS, health_read.recent_treatments)
    counts = optional(LICE, lambda wanted: health_read.latest_counts([unit.pk for unit in wanted]))
    tasks = optional(TASKS, lambda wanted: tasks_read.per_unit([unit.pk for unit in wanted], now))
    chips = optional(CHIPS, lambda wanted: _placements(wanted, user))
    hidden = tuple(key for key, shown in ((FEEDING, FEEDING in sections), (WATER, WATER in sections),
                                          (HEALTH, bool(sections & {TREATMENTS, EVENTS, LICE})),
                                          (TASKS, TASKS in sections)) if not shown)
    found = []
    for unit in kept:
        today = local_today(unit)
        own = stock.get(unit.pk)
        figures = feeding.get(unit.pk)
        day = figures.ration if figures else None
        lines = tuple(feeding_read.meal_lines(day, {share.batch.pk: share.batch for share in own.shares}, today)
                      if own and day else ())
        found.append(Card(
            unit=unit, template=resolved[unit.pk], today=today, stock=own, day=day, feeding=figures,
            lines=lines, drift=_weigh(lines), water=tuple(water.get(unit.pk, ())),
            withdrawal=tuple(withdrawals.get(unit.pk, ())), treatments=tuple(treatments.get(unit.pk, ())),
            events=tuple(events.get(unit.pk, ())), lice=counts.get(unit.pk), tasks=tasks.get(unit.pk),
            chips=tuple(chips.get(unit.pk, ())), failed=frozenset(failed),
            hidden=hidden, sections=sections, now=now))
    return found


# ---- the state ---------------------------------------------------------------------------------------------------------
def _middle(card):
    """The PointWater of the card's middle point (always the first, when there is one), else None."""
    first = card.water[0] if card.water else None
    return first if first is not None and first.point is not None and first.point.kind == water_read.MIDDLE else None


def _key_readings(card):
    """[(label, reading or None)] of the temperature and the oxygen at the card's middle point (oxygen: the mg/L or
    the saturation, whichever is there): None when the point has none, or no middle point."""
    middle = _middle(card)
    found = []
    for code, label in ((parameters.TEMPERATURE, parameters.get(parameters.TEMPERATURE).label),
                        ('oxygen', parameters.get(parameters.OXYGEN_MG_L).label)):
        reading = None
        if middle is not None:
            codes = (parameters.OXYGEN_MG_L, parameters.OXYGEN_PCT) if code == 'oxygen' else (code,)
            reading = next((middle.get(each) for each in codes if middle.get(each) is not None
                            and middle.get(each).value is not None), None)
        found.append((label, reading))
    return found


def _age(reading, now):
    return timesince(reading.at, now, depth=1)


def state_of(card):
    """The one roll-up of a card, a ladder whose thresholds are the owners' and none invented here:
    1. critical: a water reading judged critical;
    2. warning: a reading judged a warning, the unit over its capacity, an estimate that says weigh now;
    3. blind: a stocked unit whose temperature or oxygen is missing or older than its freshness (a fresh pH hides a
       three-day-old oxygen in the water's own status: that status ranks OK above stale), or with no middle point;
       never OK, never red; not worked out when the water is hidden (the card says so);
    4. note: a withdrawal in force (a chip, not an alarm: it lasts weeks), weigh soon, a ration that cannot be worked
       out (with its reason), an open health event;
    5. ok, or empty when there are no fish.
    Word, shape and reasons, never colour alone: each reason is the owning read's text."""
    basis = tuple(name for name, shown in (
        (STOCK, STOCK in card.sections), (FEEDING, FEEDING in card.sections), (WATER, WATER in card.sections),
        (HEALTH, EVENTS in card.sections)) if shown)
    if card.stock is None:
        return State(EMPTY_STATE, (), basis)
    critical, warning, note = [], [], []
    middle = _middle(card)                  # the unit's own water: a detailed card's other points do not change its state
    for point in ([middle] if middle is not None else []):
        for reading in point.alerts:
            text = '{}: {}'.format(reading.parameter.label, Status(reading.status).label)
            (critical if reading.status == Status.CRITICAL else warning).append(text)
    if critical:
        return State(CRITICAL, tuple(critical), basis)
    if card.stock.over_capacity:
        warning.append(_('Over capacity'))
    if card.drift == 'now':
        warning.append(_('Weigh now: the estimate is not reliable'))
    if warning:
        return State(WARNING, tuple(warning), basis)
    if WATER in card.sections:
        stale = []
        for label, reading in _key_readings(card):
            if reading is None:
                stale.append(_('%(label)s: no recent data') % {'label': label})
            elif not reading.fresh(card.now):
                stale.append(_('%(label)s: no recent data, %(age)s old') % {'label': label,
                                                                               'age': _age(reading, card.now)})
        if stale:
            return State(BLIND, tuple(stale), basis, tuple(stale))
    if card.withdrawal:
        note.append(_('Medicine withdrawal in force'))
    if card.drift == 'soon':
        note.append(_('Weigh soon'))
    note += [line['why'] for line in card.lines if line['why']]
    if card.events:
        note.append(ngettext('%(count)d open health event', '%(count)d open health events', len(card.events))
                    % {'count': len(card.events)})
    if note:
        return State(NOTE, tuple(note), basis)
    return State(OK, (), basis)


def attention(cards_):
    """The cards a wall's strip names, worst first: critical, warning and blind ones, each in the farm's order."""
    worse = [card for card in cards_ if RANK[card.state.key] <= RANK[BLIND]]
    return sorted(worse, key=lambda card: RANK[card.state.key])


# ---- the change token -------------------------------------------------------------------------------------------------
def change_token(user, canonical_query, board='', now=None):
    """What the screen asks "has anything changed?" with: a hash of the activity log's revision, the minute, the language,
    what the person may read, the board and the canonical address. No user id and no unit id: a unit made, edited or
    deleted writes a log entry, so the revision moves. The revision is read FIRST, before any data: a change between
    the two reads then makes the next token differ, never the other way round. The minute re-draws the figures that run
    on the clock (age, next meal) at most once a minute per screen."""
    revision = audit.revision()
    now = now or timezone.now()
    parts = (revision, str(int(now.timestamp() // TOKEN_BUCKET)), translation.get_language() or '',
             ','.join(sorted(sections_for(user))), board, canonical_query)
    return hashlib.sha256('\x1f'.join(parts).encode()).hexdigest()[:32]
