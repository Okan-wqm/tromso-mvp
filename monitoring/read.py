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
    attention(cards) -> [Card]                       the cards that need a look first, worst first
    band(cards) -> Band                              what stands above the cards: the tally per state and a chip per
                                                     thing that needs a look, capped
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
optional source that fails (its own savepoint) leaves the cards, its widgets say "no data" and the frame names it ("Could
not be read: Tasks"); a required one that fails raises Unavailable (the fragment answers 503 and the screen keeps its last
picture, saying it is not updated). Either is logged with its name and its trace, at most once a minute per source.
A section the person may not read is not read at all (no query), and the card says so; the state then says what it
is from. Nothing here writes, and a poll writes nothing."""
import hashlib
import logging
from dataclasses import dataclass
from functools import cached_property
from urllib.parse import urlencode
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone, translation
from django.utils.formats import date_format
from django.utils.timesince import timesince
from django.utils.translation import gettext as _, gettext_lazy, ngettext

from core import audit
from core.text import lower as text_lower
from farm.feeding import read as feeding_read, views as feeding_views
from farm.harvest import views as harvest_views
from farm.health import read as health_read, views as health_views
from farm.models import Tank
from farm.stock import read as stock_read, views as stock_views
from farm.stock.dates import local_today
from farm.templatetags.water import water_value
from farm.water import (
    calculation as water_calculation, chemistry, deffeyes, parameters, read as water_read, views as water_views,
)
from farm.water.evaluate import Status
from tasks import read as tasks_read, views as tasks_views

from .cards import catalogue, render, resolve

logger = logging.getLogger(__name__)

STOCK, FEEDING, WATER, TREATMENTS, EVENTS, LICE, TASKS, CHIPS, CHART = (
    'stock', 'feeding', 'water', 'treatments', 'events', 'lice', 'tasks', 'chips', 'chart')


@dataclass(frozen=True)
class Source:
    name: str
    permission: str        # the right that reads it, from the module that owns the records ('' : the provider decides)
    required: bool         # the roll-up needs it: a card is not drawn without it
    label: str = ''        # how a card's frame names it when it could not be read
    of: str = ''           # worked out from another source's answer: read only for a person who may read that one


SOURCES = (
    Source(STOCK, stock_views.VIEW, True, gettext_lazy('Fish')),
    Source(FEEDING, feeding_views.VIEW, True, gettext_lazy('Feeding')),
    Source(WATER, water_views.VIEW, True, gettext_lazy('Water')),
    Source(TREATMENTS, health_views.TREATMENTS['view'], False, gettext_lazy('Treatments')),
    Source(EVENTS, health_views.EVENTS['view'], True, gettext_lazy('Health events')),
    Source(LICE, health_views.COUNTS['view'], False, gettext_lazy('Sea-lice counts')),
    Source(TASKS, tasks_views.VIEW, False, gettext_lazy('Tasks')),
    Source(CHIPS, '', False, gettext_lazy('Experiments')),
    Source(CHART, '', False, gettext_lazy('Deffeyes chart'), of=WATER),
)
BY_NAME = {source.name: source for source in SOURCES}
LABELS = {source.name: source.label for source in SOURCES}
# The sections of a card a right reads.
SECTIONS = tuple(source.name for source in SOURCES if source.permission)
# Read for every card whatever its template: what the state is worked out from.
ROLL_UP = (STOCK, FEEDING, WATER, EVENTS)
# Beyond the sources: the cards that need every active point's water, and the feeding week.
POINTS, WEEK = 'points', 'week'
# When each source last failed and was logged ({name: time}): at most once a minute each, so a wall that asks every
# 15 seconds does not fill the log.
FAILED_AT = {}
FAIL_LOG_SECONDS = 60


class Unavailable(Exception):
    """A source the roll-up needs could not be read: no card can be drawn honestly."""
# What a card names as hidden: the health records are one block of the card.
HEALTH = 'health'
SMALL, BIG, SIMPLE, DETAILED = 'small', 'big', 'simple', 'detailed'
MODES = (SMALL, BIG, SIMPLE, DETAILED)
# The view a screen's charts are drawn in when the address says so: full scale (the default is the close view).
CHART_FULL = 'full'
STOCKED, EMPTY, ALL = 'stocked', 'empty', 'all'
OCCUPANCIES = (STOCKED, EMPTY, ALL)
KINDS = tuple(Tank.Kind.values)
CRITICAL, WARNING, BLIND, UNJUDGED, NOTE, OK, EMPTY_STATE = (
    'critical', 'warning', 'blind', 'unjudged', 'note', 'ok', 'empty')
# The roll-up in the order a wall reads it, worst first, with the one word each state is said with (the card, the
# strip, the announcer's words and the designer's "show as" all read it here).
STATES = ((CRITICAL, gettext_lazy('Critical')), (WARNING, gettext_lazy('Warning')),
          (BLIND, gettext_lazy('No recent data')), (UNJUDGED, gettext_lazy('No limit')), (NOTE, gettext_lazy('Note')),
          (OK, gettext_lazy('OK')), (EMPTY_STATE, gettext_lazy('Empty')))
RANK = {key: rank for rank, (key, _word) in enumerate(STATES)}
WORDS = dict(STATES)
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
    chart: str = ''                     # '' (the close view) or 'full': the view of every chart of the screen
    zoom: frozenset = frozenset()       # the units whose chart is drawn in the OTHER view

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
            board=_uuid(query.get('board', '')), wall=query.get('wall', '') == '1',
            chart=CHART_FULL if query.get('chart', '') == CHART_FULL else '',
            zoom=frozenset(_uuid(item) for item in query.get('zoom', '').split(',') if _uuid(item)))

    def canonical(self, **changes):
        """The address's query, one spelling for one state (sorted, defaults left out): what the change token and the
        fragment's address are built on. `changes` replace fields first."""
        merged = {**self.__dict__, **changes}
        pairs = []
        for name in ('board', 'chart', 'department', 'kind', 'mode', 'q', 'site', 'system'):
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
        if merged['zoom']:
            pairs.append(('zoom', ','.join(sorted(merged['zoom']))))
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
    stale: tuple = ()      # the reasons that are missing or old data: a blind card's, an old critical or warning value

    @property
    def word(self):
        return WORDS[self.key]


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
    chart: object = None                # water.calculation.UnitChart or Refusal of its middle point (a card that shows it)
    chart_view: str = deffeyes.CLOSE    # the view its chart's picture is drawn in (deffeyes.CLOSE, deffeyes.FULL)
    chart_extent: tuple = ()            # what the FULL view's box must hold: one box per screen and water type
    now: object = None
    clock: tuple = ()                   # data-quality notes: a device of its water whose clock is off (clock_notes)

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
    def failed_text(self):
        """The sources that could not be read, as the frame names them, in the order of SOURCES."""
        return ', '.join(str(source.label) for source in SOURCES if source.name in self.failed)

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


def _log_failure(name, message):
    """Logs the error being handled, with its trace, naming the source: at most once a minute per source."""
    now = timezone.now()
    last = FAILED_AT.get(name)
    if last is None or (now - last).total_seconds() >= FAIL_LOG_SECONDS:
        FAILED_AT[name] = now
        logger.exception(message, name)


def _required(name, loader, *args):
    """A source the roll-up needs: its answer, or Unavailable when it raises, logged with its name and cause (the screens
    keep their last picture and say they are not updated; the log says why). No savepoint: nothing is read after it."""
    try:
        return loader(*args)
    except Exception as error:
        _log_failure(name, 'The %s source the monitoring cards\' state needs failed; the screens keep their last '
                           'picture (503).')
        raise Unavailable(name) from error


def _optional(name, loader, *args):
    """An optional source read in its own savepoint: its answer, or {} and the name among the failed when it raises
    (logged, and said on the card's frame). A chip, a task count or a treatment list is never a reason a card cannot be
    shown."""
    try:
        with transaction.atomic():
            return loader(*args), False
    except Exception:                                           # fail open, and say so
        _log_failure(name, 'The %s source of the monitoring cards failed; its widgets say "no data" and the frame '
                           'names it.')
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
    """{source: unit ids} for {unit id: Resolved}: the sources of every widget of each unit's layout (the unit's chart
    too for a value widget bound to a value the chart works out), the roll-up's set for every unit, and POINTS (every
    active point's water) and WEEK (the feeding week) for the cards that show them."""
    found = {source.name: set() for source in SOURCES}
    found[POINTS], found[WEEK] = set(), set()
    for unit_id, chosen in resolved.items():
        for name in ROLL_UP:
            found[name].add(unit_id)
        for widget in chosen.layout['widgets']:
            for name in catalogue.WIDGETS[widget['type']].sources:
                found[name].add(unit_id)
            if widget.get('bind', {}).get('parameter') in catalogue.CALCULATED:
                found[CHART].add(unit_id)               # a value the unit's chart works out
            opts = widget.get('opts', {})
            if (widget['type'] == 'water_table' and opts.get('points') == 'all') or widget['type'] == 'points' or \
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
    stock = _required(STOCK, stock_read.stock_of, units) if STOCK in sections else {}
    kept = [unit for unit in units if occupancy == ALL or (unit.pk in stock) == (occupancy == STOCKED)]
    stocked = [unit for unit in kept if unit.pk in stock]
    resolved = _required('templates', resolve.templates_for, kept,
                         {unit.pk: _species(stock[unit.pk]) for unit in stocked}, choice)
    need = needs(resolved)
    feeding = (_required(FEEDING, lambda: feeding_read.figures(
        {unit.pk: stock[unit.pk] for unit in stocked}, details=[unit for unit in stocked if unit.pk in need[WEEK]],
        ration=True)) if FEEDING in sections and stocked else {})
    water = (_required(WATER, lambda: water_read.points_water(
        kept, now, middle_only=[unit.pk for unit in kept if unit.pk not in need[POINTS]]))
        if WATER in sections and kept else {})
    withdrawals = _required('withdrawal', harvest_views.withdrawals, stocked) if STOCK in sections and stocked else {}
    clocks = _clocks({unit.pk: water.get(unit.pk, ()) for unit in stocked}, now) if water and stocked else {}
    events = _required(EVENTS, health_read.open_events, kept) if EVENTS in sections and kept else {}
    failed = set()

    def optional(name, loader, *args):
        wanted = [unit for unit in kept if unit.pk in need[name]]
        if not wanted or (name in SECTIONS and name not in sections) or (
                BY_NAME[name].of and BY_NAME[name].of not in sections):
            return {}
        found, broke = _optional(name, loader, *args, wanted)
        if broke:
            failed.add(name)
        return found

    treatments = optional(TREATMENTS, health_read.recent_treatments)
    counts = optional(LICE, lambda wanted: health_read.latest_counts([unit.pk for unit in wanted]))
    tasks = optional(TASKS, lambda wanted: tasks_read.per_unit([unit.pk for unit in wanted], now))
    chips = optional(CHIPS, lambda wanted: _placements(wanted, user))
    # From the water just read: no value is read again, and the fish's limits once for all the cards that show it.
    charts = optional(CHART, lambda wanted: water_calculation.charts_of(wanted, water, now))
    extents = chart_extents(kept, charts)
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
            chips=tuple(chips.get(unit.pk, ())), failed=frozenset(failed), chart=charts.get(unit.pk),
            chart_view=(deffeyes.FULL if (choice.chart == CHART_FULL) != (str(unit.pk) in choice.zoom)
                        else deffeyes.CLOSE),
            chart_extent=extents.get(unit.water_type, ()),
            hidden=hidden, sections=sections, now=now, clock=tuple(clocks.get(unit.pk, ()))))
    return found


def chart_extents(units, charts):
    """{water type: ((DIC, alkalinity),)}: for each water type of the screen's units, the one point every chart's box
    must hold so that the charts of that water share ONE box at full scale (deffeyes.card_figure `extent`): the
    largest DIC and the largest alkalinity (a water's own or its band's upper end) among the charts that could be
    worked out. Fresh and sea water keep a box each: their waters are far apart, and a shared box would shrink both."""
    found = {}
    for unit in units:
        chart = charts.get(unit.pk)
        if not isinstance(chart, water_calculation.UnitChart):
            continue
        analysis = chart.calculation.analysis
        top = analysis.limits.alkalinity_high_mg_l
        alkalinity = max(analysis.alkalinity_meq, top / chemistry.MG_CACO3_PER_MEQ if top is not None else 0.0)
        dic, high = found.get(unit.water_type, (0.0, 0.0))
        found[unit.water_type] = (max(dic, analysis.dic), max(high, alkalinity))
    return {water_type: (point,) for water_type, point in found.items()}


def _live_channels(water):
    """{channel number: {unit id}} of the live values on the units' cards (`water`: {unit id: [PointWater]})."""
    channels = {}
    for unit_id, points in water.items():
        for point_water in points:
            for reading in point_water.readings.values():
                for each in (reading, *reading.deciding):
                    if each.sample.live and each.sample.channel_no is not None:
                        channels.setdefault(each.sample.channel_no, set()).add(unit_id)
    return channels


def _clocks(water, now):
    """`clock_notes`, in a savepoint (only when a card shows a live value): a data-quality note that cannot be read is
    left out and logged, never a reason to keep the wall's last picture."""
    if not _live_channels(water):
        return {}
    try:
        with transaction.atomic():
            return clock_notes(water, now)
    except Exception:
        _log_failure('clock', 'The %s notes of the monitoring cards could not be read; the cards go on without them.')
        return {}


def clock_notes(water, now):
    """{unit id: ['Device clock is 4 min ahead (PROBE-1)']} of the devices whose live values are on the units' cards
    (`water`: {unit id: [PointWater]}, the card's own read) and whose clock is past the alarm rules' warning limit
    (alarms/clock.py: the alarm's own judgement, never a second one). No query when no card shows a live value."""
    from alarms import clock
    from sensors.models import Channel
    channels = _live_channels(water)
    if not channels:
        return {}
    devices = {}
    for channel_no, device_id, code in Channel.all_objects.filter(channel_no__in=list(channels)).values_list(
            'channel_no', 'device_id', 'device__code'):
        devices.setdefault(device_id, (code, set()))[1].update(channels[channel_no])
    by_unit = {}
    for device_id, note in clock.notes(list(devices), now).items():
        code, units = devices[device_id]
        for unit_id in units:
            by_unit.setdefault(unit_id, []).append(f'{note} ({code})')
    return {unit_id: sorted(notes) for unit_id, notes in by_unit.items()}


# ---- the state ---------------------------------------------------------------------------------------------------------
def _middle(card):
    """The PointWater of the card's middle point (always the first, when there is one), else None."""
    first = card.water[0] if card.water else None
    return first if first is not None and first.point is not None and (
        first.for_unit or first.point.kind == water_read.MIDDLE) else None


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


def _alerts(middle, now):
    """([critical reasons], [warning reasons], [the reasons that are old values]) of the middle point's values the limits
    judge critical or a warning, fresh or old: an old one keeps its judgement and says "no recent data" (the value is the
    last word there is about the water; it is never dropped for being old). The values and the words are the water
    page's one rule, farm.water.read.PointWater.alerts."""
    critical, warning, old = [], [], []
    alerts = list(middle.alerts if middle is not None else ())
    listed = {id(reading.sample) for reading, _judged, _stale in alerts if not reading.derived}
    for reading, judged, stale in alerts:
        if reading.value is None or (reading.derived and id(reading.sample) in listed):
            continue                                # a derived value is no second reason beside its own measurement
        status = Status(judged).label
        label = reading.parameter.label
        where = reading.decided_at
        if where is not None and middle.point is not None and where != middle.point:
            label = f'{label} ({where})'            # another point of the unit's water decided it (A9.1, P2): say which
        if not stale:
            text = '{}: {}'.format(label, status)
        else:
            text = '{}: {}'.format(label, _('%(status)s, no recent data') % {'status': status})
        text = Reason(text, _brief(reading, middle, stale))
        if stale:
            old.append(text)
        (critical if judged == Status.CRITICAL else warning).append(text)
    return critical, warning, old


@dataclass(frozen=True)
class Brief:
    """A reason in short, for a small card's one line and the band's chip: a value against the bound it is past
    (`figure` 'O₂ (mg/L) 5.00', `sign` '<', `bound` 'critical limit 6.00' with ", no recent data" when the value is
    old, `limit` '6.00'), or, with no sign and no bound, the reason's own words."""
    figure: str
    sign: str = ''
    bound: str = ''
    limit: str = ''
    critical: bool = False
    old: bool = False

    @property
    def sentence(self):
        """One line for the band's chip, whose shape (and word, for a screen reader) says the rung: a critical value
        against its bound in words ('CO₂ (mg/L) 28.9 > critical limit 20.0'), a warning against the number alone
        ('CO₂ (mg/L) 18.8 > 15.0'); an old value says so."""
        if not self.sign:
            return self.figure
        said = f'{self.figure} {self.sign} {self.bound if self.critical else self.limit}'
        return _('%(value)s, no recent data') % {'value': said} if self.old and not self.critical else said


class Reason(str):
    """A reason of a card's state: the sentence itself (the owning read's own words, as every card, the announcer and
    the tests read it), carrying its `brief`. Anything that loses the brief (a copy, a format) falls back to the whole
    sentence (`brief_of`): more words, never fewer."""

    def __new__(cls, text, brief=None):
        made = super().__new__(cls, text)
        made.brief = brief
        return made


def brief_of(reason):
    """The Brief of a reason: its own, else its whole sentence."""
    return getattr(reason, 'brief', None) or Brief(str(reason))


BOUND_WORDS = {Status.CRITICAL: gettext_lazy('critical limit %(bound)s'),
               Status.WARNING: gettext_lazy('warning limit %(bound)s')}


def _brief(reading, middle, stale):
    """The Brief of a value the limits judge critical or a warning: the value that is past a bound (the water's own
    answer, farm.water.read.crossed: the worse fresh value when that decided it), named by its parameter's short label
    and its point when not the card's middle, and the bound with its kind; "no recent data" when the value is old. None
    when no one bound says it (the card then says the whole reason)."""
    found = water_read.crossed(reading)
    if found is None:
        return None
    source, name, bound = found
    label = str(source.parameter.short)
    if source.point is not None and middle.point is not None and source.point != middle.point:
        label = f'{label} ({source.point})'
    limit = water_value(bound, source.code)
    words = BOUND_WORDS[Status(reading.judged)] % {'bound': limit}
    if stale:
        words = _('%(bound)s, no recent data') % {'bound': words}
    return Brief(f'{label} {water_value(source.value, source.code)}', '<' if name.endswith('low') else '>', str(words),
                 limit, reading.judged == Status.CRITICAL, stale)


def state_of(card):
    """The card's roll-up (`_ladder`), with its data-quality notes (a device of its water whose clock is off, owner
    2026-11-09) said whatever its rung: beside a critical, a warning or a blind card's reasons, and as a note where it
    would be OK. An empty unit's card has none."""
    state = _ladder(card)
    if not card.clock or state.key == EMPTY_STATE:
        return state
    return State(NOTE if state.key == OK else state.key, state.reasons + card.clock, state.basis, state.stale)


def _ladder(card):
    """The one roll-up of a card, a ladder whose thresholds are the owners' and none invented here:
    1. critical: a water value judged critical, fresh or old (an old one says its age, and the card is marked old);
    2. warning: a value judged a warning (fresh or old, the same), the unit over its capacity, an estimate that says
       weigh now;
    3. blind: a stocked unit whose temperature or oxygen is missing or older than its freshness (a fresh pH hides a
       three-day-old oxygen in the water's own status: that status ranks OK above stale), with no middle point, or whose
       live sensors could not be read; never OK, never red; not worked out when the water is hidden (the card says so);
    4. unjudged ("No limit"): a value of the stocked unit that no limit row judges for its fish (the owner has set
       none): what it means for the fish is not known, so it is never OK;
    5. note: a withdrawal in force (a chip, not an alarm: it lasts weeks), weigh soon, a ration that cannot be worked
       out (with its reason), an open health event;
    6. ok, or empty when there are no fish.
    Word, shape and reasons, never colour alone: each reason is the owning read's text."""
    basis = tuple(name for name, shown in (
        (STOCK, STOCK in card.sections), (FEEDING, FEEDING in card.sections), (WATER, WATER in card.sections),
        (HEALTH, EVENTS in card.sections)) if shown)
    if card.stock is None:
        return State(EMPTY_STATE, (), basis)
    note = []
    middle = _middle(card)                  # the unit's own water: a detailed card's other points do not change its state
    critical, warning, old = _alerts(middle, card.now)
    if critical:
        return State(CRITICAL, tuple(critical), basis, tuple(text for text in old if text in critical))
    if card.stock.over_capacity:
        warning.append(_('Over capacity'))
    if card.drift == 'now':
        warning.append(_('Weigh now: the estimate is not reliable'))
    if warning:
        return State(WARNING, tuple(warning), basis, tuple(text for text in old if text in warning))
    if WATER in card.sections:
        stale = []
        for label, reading in _key_readings(card):
            if reading is None:
                stale.append(_('%(label)s: no recent data') % {'label': label})
            elif not reading.fresh(card.now):
                stale.append(_('%(label)s: no recent data, %(age)s old') % {'label': label,
                                                                               'age': _age(reading, card.now)})
        if middle is not None:
            stale += [_('%(label)s: timestamp in the future') % {'label': reading.parameter.label}
                      for reading in middle.future]       # a data error, never silently OK
        if middle is not None and middle.sensors_failed:
            stale.append(_('Live sensor values could not be read: samples only.'))
        if stale:
            return State(BLIND, tuple(stale), basis, tuple(stale))
        unjudged = [_('%(label)s: no limit for these fish') % {'label': reading.parameter.label}
                    for reading in (middle.unjudged if middle is not None else ())]
        if unjudged:
            return State(UNJUDGED, tuple(unjudged), basis)
    if card.withdrawal:
        text, until = _('Medicine withdrawal in force'), getattr(card.withdrawal[0], 'until', None)
        # (in short, with its date: a small card has no room for the withdrawal's chip and its date)
        note.append(Reason(text, Brief(text, bound=_('until %(date)s') % {
            'date': date_format(until, 'DATE_FORMAT')}) if until else None))
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
    """The cards a wall's strip names, worst first: critical, warning, blind and no-limit ones, each in the farm's
    order."""
    worse = [card for card in cards_ if RANK[card.state.key] <= RANK[UNJUDGED]]
    return sorted(worse, key=lambda card: RANK[card.state.key])


# ---- the band ---------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Chip:
    """One entry of the band: the units it names (the first `shown` by their code, `more` of them only counted), the
    rung they are on and what is wrong, in short."""
    state: str
    cards: tuple
    text: str
    shown: tuple
    more: int

    @property
    def word(self):
        return WORDS[self.state]

    @property
    def rest(self):
        """The codes of the units it only counts, for its title."""
        return ', '.join(card.unit.code for card in self.cards[len(self.shown):])


@dataclass(frozen=True)
class Band:
    """What stands above the cards on every screen and page of them: how many units are on each rung (`tally`:
    (key, word, count), worst first, the rungs that have a unit), a chip per thing that needs a look (`chips`), and how
    many abnormal units no chip names because there were more chips than fit (`more`)."""
    tally: tuple
    chips: tuple
    more: int


def band(cards_, chips=None, codes=None):
    """The Band of the cards shown. The tally counts EVERY card, so nothing is left out of the count whatever the cap.
    The chips, worst first (`attention`): a critical or warning unit with the first reason of its state in short
    (`Brief`: the value against the bound it is past); units whose chip would say the same words share one chip; the
    units with no recent data share one, and those with a value no limit judges another (their words are the state's:
    the card says which value). At most `chips` chips (settings.MONITOR_BAND_CHIPS), each naming at most `codes` units
    (settings.MONITOR_BAND_CODES); the rest are counted, never dropped silently."""
    chips = settings.MONITOR_BAND_CHIPS if chips is None else chips
    codes = settings.MONITOR_BAND_CODES if codes is None else codes
    counts = {}
    for card in cards_:
        counts[card.state.key] = counts.get(card.state.key, 0) + 1
    tally = tuple((key, word, counts[key]) for key, word in STATES if key in counts)
    groups = {}
    for card in attention(cards_):
        state = card.state
        if state.key in (CRITICAL, WARNING) and state.reasons:
            text = brief_of(state.reasons[0]).sentence
        else:
            text = text_lower(str(state.word))
        groups.setdefault((state.key, text), []).append(card)
    found = [Chip(key, tuple(members), text, tuple(members[:codes]), max(len(members) - codes, 0))
             for (key, text), members in groups.items()]
    return Band(tally, tuple(found[:chips]), sum(len(chip.cards) for chip in found[chips:]))


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
