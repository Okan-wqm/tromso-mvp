"""Reading an experiment: the one definition of what belongs to the trial, and what the other pages and checks ask of
the placements. Pure reads; every figure of the farm is read through the farm's own reads (farm/stock/read.py,
farm/feeding/read.py) over the days a placement gives, never copied, and the queries do not grow with the tanks.

- `cells(experiment)`: the single definition of what belongs to the trial: each live placement with its replicate and
  group, in the order of the design. Everything that asks "which tank, which days, which replicate" (the overview, the
  checks, the dataset to come) asks here.
- `booked(unit_ids, first, last)`: the experiments that hold these tanks on some of those days, drafts included (a
  draft reserves its tanks);
- `placements(unit_ids, day)`: the cell each tank is in on a day, at most one (the exclusion constraint), for whoever
  asks which experiment a tank is in (a lock, a badge);
- `overview(experiment)`: per replicate its tanks, the batches of the species that were in them on its days, fish and
  biomass now, survival over the days and the feed conversion over the days: every figure through the farm's own reads,
  bounded by the placement's days, with no "since stocking" figure beside them;
- `data(experiment)`: per tank its days and the feeding records of them, for the Data tab;
- `chips(units, user)`: the placement registry's provider (farm/placements.py): each unit's experiment, group and replicate
  on its site's today, for those who may read experiments;
- `deviations(experiment)`: what happened on the days of the placements that the design did not say (a batch that came in,
  fish moved between replicates or out of the trial, a feed on no band of the diet, a ration that does not follow the diet):
  derived from the farm's own records, never stored, never blocking."""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format, number_format
from django.utils.translation import gettext as _

from core import sealing
from core.people import person_name
from farm import placements as farm_placements
from farm.feeding import read as feeding_read
from farm.feeding.fold import LOST
from farm.models import Batch, Feed, FeedingRecord, ProtocolBand, StockMovement, Tank
from farm.models.feeding import FeedTarget
from farm.models.stock import MovementKind
from farm.stock import read as stock_read
from farm.stock.dates import local_today, site_today

from .models import ExperimentGroup, FactorKind, GroupLevel, Replicate, ReplicateSystem, ReplicateUnit, Status


@dataclass(frozen=True)
class Cell:
    """A tank in a replicate of a group, on the days it is booked to it (both included, on the site's clock)."""
    replicate: Replicate
    group: ExperimentGroup
    unit: object
    first: date
    last: date
    id: object = None                 # the placement's own id (a tank is released or replaced by it)


def cells(experiment):
    """The live placements of an experiment as cells, by group position, replicate number and first day."""
    placements = (ReplicateUnit.objects.filter(replicate__group__experiment=experiment,
                                               replicate__is_deleted=False, replicate__group__is_deleted=False)
                  .select_related('replicate__group', 'unit__production_department__site', 'unit__system')
                  .order_by('replicate__group__position', 'replicate__group__name', 'replicate__number', 'from_on',
                            'unit__code'))
    return [Cell(placement.replicate, placement.replicate.group, placement.unit, placement.from_on,
                 placement.until_on, placement.pk) for placement in placements]


def booked(unit_ids, first, last, exclude=None, model=None, key='unit_id'):
    """{unit id: (first day, last day)} of the booking that holds each tank on some day from `first` to `last` (both
    included) for an experiment other than `exclude`; one booking a tank (the exclusion constraint allows no more).
    Read as the system: a booking by an experiment the person may not read still holds the tank, and is said with its
    days only, never with the experiment (the same answer whoever holds it). `model`, `key`: the system bookings."""
    model = model or ReplicateUnit
    found = {}
    with sealing.system('the booking check'):
        rows = model.objects.filter(**{f'{key}__in': list(ids_of(unit_ids))}, from_on__lte=last, until_on__gte=first)
        if exclude is not None:
            rows = rows.exclude(replicate__group__experiment=exclude)
        for row_key, from_on, until_on in rows.order_by('from_on').values_list(key, 'from_on', 'until_on'):
            found.setdefault(row_key, (from_on, until_on))
    return found


def booked_systems(system_ids, first, last, exclude=None):
    """{system id: (first day, last day)}: `booked` for whole systems."""
    return booked(system_ids, first, last, exclude, model=ReplicateSystem, key='system_id')


def ids_of(items):
    return [getattr(item, 'pk', item) for item in items]


def booked_text(code, days):
    """The one sentence a booking by another experiment is said with: the tank or system and the days, never which
    experiment (it may be one the person may not read)."""
    return _('%(code)s is booked by another experiment from %(first)s to %(last)s.') % {
        'code': code, 'first': days[0].isoformat(), 'last': days[1].isoformat()}


def error_df(experiment):
    """The error degrees of freedom the design leaves: its replicates less its groups (pooled over the groups)."""
    groups = ExperimentGroup.objects.filter(experiment=experiment)
    replicates = Replicate.objects.filter(group__in=groups).count()
    return replicates - groups.count()


def placements(unit_ids, day):
    """{unit id: Cell}: the placement each tank has on `day` (both ends included), if any: the exclusion constraint allows
    at most one live placement of a tank on a day."""
    rows = (ReplicateUnit.objects.filter(unit_id__in=list(unit_ids), from_on__lte=day, until_on__gte=day,
                                         replicate__is_deleted=False, replicate__group__is_deleted=False,
                                         replicate__group__experiment__is_deleted=False)
            .select_related('replicate__group__experiment', 'unit'))
    return {row.unit_id: Cell(row.replicate, row.replicate.group, row.unit, row.from_on, row.until_on, row.pk)
            for row in rows}


def progress(experiment, today):
    """Where the experiment is in its days, as (phase, day, total, days): 'before' with the days to go until day 0, 'during'
    with the day (0 is the baseline weighing; the total is the duration), 'after' with the days since the final weighing;
    None without a day 0."""
    if experiment.starts_on is None:
        return None
    end = experiment.starts_on + timedelta(days=experiment.duration_days)
    if today < experiment.starts_on:
        return ('before', None, experiment.duration_days, (experiment.starts_on - today).days)
    if today > end:
        return ('after', None, experiment.duration_days, (today - end).days)
    return ('during', (today - experiment.starts_on).days, experiment.duration_days, None)


@dataclass
class ReplicateFigures:
    """One replicate of the overview: where it stands, what was in it, and its figures over its days (None where a read
    has none: a draft has no figures, a tank without fish no biomass; a dash says why for the conversion)."""
    group: ExperimentGroup
    replicate: Replicate
    cells: list
    batches: list = field(default_factory=list)
    fish: int = None                  # in its tanks now (while it runs)
    biomass_kg: Decimal = None
    survival: Decimal = None          # % of the fish there on its first day that were not lost since
    conversion: object = None         # feeding.read.Conversion over its windows
    gap: list = field(default_factory=list)    # tanks left out of the conversion: no measured point at a move
    unmeasured: str = ''                       # why there is no conversion when a tank's last day has no weighing

    @property
    def tanks(self):
        return [cell.unit for cell in self.cells]


def overview(experiment, today=None):
    """[ReplicateFigures] of an experiment, in the order of its design, every one a slot (a replicate without a tank has
    none of the rest). The queries do not grow with the tanks: the placements, the batches that were in them (of the
    species: cleaner fish never count), the fish now, the losses over the days and one walk of the feeding per distinct
    window. The figures of a draft are not read (nothing has started); a closed experiment shows no "now". Over the days
    means the placement's: the conversion from its first day to the latest weighing, or, once its last day has come (or
    the experiment closed), to the weighing of that day; the survival from the fish of its first day, less the fish lost
    since."""
    today = today or site_today(experiment.site)
    groups = list(ExperimentGroup.objects.filter(experiment=experiment).order_by('position', 'name'))
    replicates = list(Replicate.objects.filter(group__in=groups).order_by('number'))
    by_replicate = {}
    for cell in cells(experiment):
        by_replicate.setdefault(cell.replicate.pk, []).append(cell)
    rows = [ReplicateFigures(group, replicate, by_replicate.get(replicate.pk, []))
            for group in groups for replicate in replicates if replicate.group_id == group.pk]
    if experiment.status == Status.DRAFT or not by_replicate:
        for row in rows:
            row.conversion = feeding_read.Conversion([])
        return rows
    units = {cell.unit.pk: cell.unit for row in rows for cell in row.cells}
    presence = stock_read.Presence.of_units(list(units))
    found = {batch_id for unit_id in units for batch_id in presence.batches.get(unit_id, ())}
    batches = Batch.all_objects.select_related('species').in_bulk(found)
    mine = {pk for pk, batch in batches.items() if batch.species_id == experiment.species_id}
    for row in rows:
        seen = {}
        for cell in row.cells:
            for batch_id in presence.batches.get(cell.unit.pk, ()):
                if batch_id in mine and presence.present_between(cell.unit.pk, batch_id, cell.first, cell.last):
                    seen[batch_id] = batches[batch_id]
        row.batches = sorted(seen.values(), key=lambda batch: batch.code)
    _stock_now(experiment, rows, units, today)
    _survival(rows, units, mine, presence, today)
    _conversion(rows, today, experiment.status == Status.CLOSED)
    return rows


def _stock_now(experiment, rows, units, today):
    """The fish and the biomass in each replicate's tanks now, of its own batches, for a running experiment."""
    if experiment.status != Status.RUNNING:
        return
    stock = stock_read.stock_of(list(units.values()))
    for row in rows:
        own = {batch.pk for batch in row.batches}
        fish, grams, live = 0, Decimal(0), False
        for cell in row.cells:
            if not cell.first <= today <= cell.last:
                continue
            live = True
            unit_stock = stock.get(cell.unit.pk)
            for share in unit_stock.shares if unit_stock else ():
                if share.batch.pk in own:
                    fish, grams = fish + share.count, grams + share.grams
        if live:
            row.fish, row.biomass_kg = fish, grams / 1000


def _survival(rows, units, mine, presence, today):
    """The share of the fish present on a replicate's first day that were not lost (mortality, cull, an adjustment down)
    since, up to its last day or today: one query for the losses of every tank. Only the tanks the replicate began with
    give its starting fish: the fish a replacement tank receives are the same fish (moved), not new ones, so what was
    lost in it from its first day on counts, and what was in it on that day does not."""
    first = min(cell.first for row in rows for cell in row.cells)
    last = min(max(cell.last for row in rows for cell in row.cells), today)
    lines = (StockMovement.objects.filter(unit_id__in=list(units), batch_id__in=mine, operation__is_deleted=False,
                                          kind__in=LOST, count_delta__lt=0, operation__date__gte=first,
                                          operation__date__lte=last)
             .values_list('unit_id', 'batch_id', 'operation__date', 'count_delta'))
    losses = {}
    for unit_id, batch_id, day, delta in lines:
        losses.setdefault((unit_id, batch_id), []).append((day, -delta))
    for row in rows:
        start = lost = 0
        began = min((cell.first for cell in row.cells), default=None)
        for cell in row.cells:
            initial = cell.first == began
            for batch in row.batches:
                if initial:
                    start += presence.count_at_end(cell.unit.pk, batch.pk, cell.first)
                lost += sum(count for day, count in losses.get((cell.unit.pk, batch.pk), ())
                            if (cell.first < day if initial else cell.first <= day) and day <= min(cell.last, today))
        if start:
            row.survival = Decimal(100) * (start - lost) / start


def window_end(cell, today, closed):
    """The last day a placement's conversion is read to: its own last day once that has come (or the experiment is
    closed), else None, the latest weighing."""
    return cell.last if closed or cell.last <= today else None


def _conversion(rows, today, closed):
    """Each replicate's feed conversion over its windows: `feeding.read.windows_in`, once per distinct window (usually
    one: the span), the windows of the tanks and batches of the replicate summed, as the figures page sums its own
    (`Conversion`: a ratio of sums)."""
    asked = {}
    for row in rows:
        for cell in row.cells:
            asked.setdefault((cell.first, window_end(cell, today, closed)), set()).add(cell.unit.pk)
    windows = {key: feeding_read.windows_in(sorted(unit_ids), *key) for key, unit_ids in asked.items()}
    for row in rows:
        own = {batch.pk for batch in row.batches}
        taken, gap = [], []
        for cell in row.cells:
            found = [window for (unit_id, batch_id), window in windows[(cell.first, window_end(cell, today, closed))]
                     .items() if unit_id == cell.unit.pk and batch_id in own]
            taken.extend(found)
            if not found and own and len(row.cells) > 1:
                gap.append(cell.unit.code)
        row.conversion = feeding_read.Conversion(taken)
        row.gap = gap if taken else []
        ended = next((cell for cell in row.cells if window_end(cell, today, closed) is not None), None)
        if not taken and own and ended is not None:
            row.unmeasured = _('%(tank)s has no weighing on %(day)s, its last day: the feed conversion is read from the weighing '
                               'of the first day to the weighing of the last.') % {
                'tank': ended.unit.code, 'day': ended.last.isoformat()}


@dataclass
class TankData:
    """A tank of the experiment for the Data tab: its days and the feeding records of them."""
    cell: Cell
    records: int
    kilos: Decimal


def feed_target(experiment):
    """Whom the experiment's feeding records are for: the farm splits a unit's feed between its production fish and the cleaner
    fish beside them (the record's `target`), and the experiment's species says which of the two its fish are: the other
    kind's feeding is never the trial's."""
    return FeedTarget.CLEANER_FISH if experiment.species.is_cleaner_fish else FeedTarget.PRODUCTION


def data(experiment):
    """[TankData] of the experiment's tanks, in the order of the design: per placement its days and the feeding records
    of the tank on them (one read of the units' feeding, `feeding.read.feedings`: the count and the feed given)."""
    found = cells(experiment)
    if not found:
        return []
    target = feed_target(experiment)
    records = feeding_read.feedings({cell.unit.pk for cell in found}, since=min(cell.first for cell in found))
    result = []
    for cell in found:
        mine = [record for record in records if record.unit_id == cell.unit.pk and cell.first <= record.date <= cell.last
                and record.target == target]
        result.append(TankData(cell, len(mine), sum((record.amount_kg for record in mine), Decimal(0))))
    return result


# ---- deviations: what happened that the design did not say ------------------------------------------------------------
FOREIGN_BATCH, TRANSFER, FEED_OFF_BAND, RATION_OFF_DIET = 'foreign_batch', 'transfer', 'feed_off_band', 'ration_off_diet'


@dataclass(frozen=True)
class Deviation:
    """A fact of a running or finished experiment that the design did not say, read from the farm's own records on the days
    of a placement: derived, never stored, never blocking (a fish is never refused for a design): the one list the
    Overview shows and the end-of-trial report will quote. `code` names the rule, `about` tells two of a rule on one
    placement apart (a batch, a feed, a transfer)."""
    code: str
    cell: Cell
    first: date
    last: date
    text: str
    about: str = ''


def _days(first, last):
    day = first
    while day <= last:
        yield day
        day += timedelta(days=1)


def _runs(days):
    """[(first, last)] of the runs of consecutive days in a sorted list."""
    runs = []
    for day in days:
        if runs and day - runs[-1][1] == timedelta(days=1):
            runs[-1] = (runs[-1][0], day)
        else:
            runs.append((day, day))
    return runs


def _diet_protocols(experiment):
    """{group id: the feeding protocol of the group's diet level}: a group without a diet is not in it."""
    rows = (GroupLevel.objects.filter(experiment=experiment, factor__kind=FactorKind.DIET, level__protocol__isnull=False)
            .select_related('level__protocol'))
    return {row.group_id: row.level.protocol for row in rows}


def deviations(experiment, today=None):
    """[Deviation] of an experiment over the days its placements have had (to today at the latest), in the order of its
    design; a draft has none (nothing has begun). The queries do not grow with the tanks.
    - `foreign_batch`: a batch of the experiment's species that is in a tank on some day of its placement and was not there on
      the placement's first day (a stocking, or a transfer in, since the tank came in). Cleaner fish never count;
    - `transfer`: fish moved between tanks of two replicates, or between a tank of the experiment and one that is not in it
      (a move inside one replicate, as a replacement makes, is not one);
    - `feed_off_band`: feed given to a tank on a day of its placement that is on no band of its group's protocol;
    - `ration_off_diet`: the farm's own rule (`ration.Policy.resolve`) gives a batch in a tank another protocol than the
      diet of its group, or none, on some day: a protocol assigned to the batch in the unit beats the unit's, or the diet's
      own row is gone."""
    if experiment.status == Status.DRAFT:
        return []
    today = today or site_today(experiment.site)
    placed = [cell for cell in cells(experiment) if cell.first <= today]
    if not placed:
        return []
    order = {cell.id: index for index, cell in enumerate(placed)}
    units = {cell.unit.pk: cell.unit for cell in placed}
    presence = stock_read.Presence.of_units(list(units))
    batches = Batch.all_objects.in_bulk({batch_id for unit_id in units for batch_id in presence.batches.get(unit_id, ())})
    mine = {pk for pk, batch in batches.items() if batch.species_id == experiment.species_id}
    protocols = _diet_protocols(experiment)
    found = (_foreign_batches(placed, presence, batches, mine, today) + _transfers(placed, today)
             + _feed_off_band(placed, protocols, today, feed_target(experiment))
             + _ration_off_diet(placed, protocols, presence, mine, units, today))
    return sorted(found, key=lambda item: (order[item.cell.id], item.first, item.code, item.about))


def _until(cell, today):
    return min(cell.last, today)


def _foreign_batches(placed, presence, batches, mine, today):
    found = []
    for cell in placed:
        unit_id = cell.unit.pk
        for batch_id in sorted(presence.batches.get(unit_id, ()), key=lambda pk: batches[pk].code):
            if batch_id not in mine or presence.present(unit_id, batch_id, cell.first):
                continue
            days = [day for day in _days(cell.first, _until(cell, today)) if presence.present(unit_id, batch_id, day)]
            if days:
                found.append(Deviation(FOREIGN_BATCH, cell, days[0], days[-1], _(
                    'Batch %(batch)s was in %(tank)s, though it was not there on the first day of the tank in the '
                    'experiment.') % {'batch': batches[batch_id].code, 'tank': cell.unit.code}, batches[batch_id].code))
    return found


def _transfers(placed, today):
    by_unit = {}
    for cell in placed:
        by_unit.setdefault(cell.unit.pk, []).append(cell)
    kinds = (MovementKind.TRANSFER_OUT, MovementKind.TRANSFER_IN)
    touching = (StockMovement.objects.filter(kind__in=kinds, unit_id__in=list(by_unit), operation__is_deleted=False,
                                             operation__date__gte=min(cell.first for cell in placed),
                                             operation__date__lte=today).values('operation_id'))
    lines = (StockMovement.objects.filter(kind__in=kinds, operation_id__in=touching)
             .values_list('operation_id', 'pair', 'operation__date', 'unit_id', 'kind', 'count_delta'))
    moves = {}
    for operation_id, pair, day, unit_id, kind, delta in lines:
        move = moves.setdefault((operation_id, pair), {'day': day, 'fish': 0})
        if kind == MovementKind.TRANSFER_OUT:
            move['out'], move['fish'] = unit_id, move['fish'] + abs(delta)
        else:
            move['into'] = unit_id
    codes = dict(Tank.all_objects.filter(pk__in={unit_id for move in moves.values() for unit_id in
                                                 (move.get('out'), move.get('into'))}).values_list('pk', 'code'))
    found = []
    for (operation_id, pair), move in moves.items():
        if 'out' not in move or 'into' not in move:
            continue
        day, ends = move['day'], (move['out'], move['into'])
        cover = {unit_id: next((cell for cell in by_unit.get(unit_id, ()) if cell.first <= day <= cell.last), None)
                 for unit_id in ends}
        if not any(cover.values()):
            continue                                              # neither tank was in the experiment that day
        if {cell.replicate.pk for cell in by_unit.get(ends[0], ())} & {cell.replicate.pk for cell in by_unit.get(ends[1], ())}:
            continue                                              # inside one replicate: a replacement's move
        values = {'fish': move['fish'], 'out': codes[ends[0]], 'into': codes[ends[1]], 'day': day.isoformat()}
        outsider = next((unit_id for unit_id in ends if unit_id not in by_unit), None)
        if outsider is not None:
            values['tank'] = codes[outsider]
            text = _('%(fish)s fish were moved from %(out)s to %(into)s on %(day)s, and %(tank)s is not a tank of the '
                     'experiment.') % values
        else:
            text = _('%(fish)s fish were moved from %(out)s to %(into)s on %(day)s, between two replicates.') % values
        found.append(Deviation(TRANSFER, cover[ends[0]] or cover[ends[1]], day, day, text, f'{operation_id}/{pair}'))
    return found


def _feed_off_band(placed, protocols, today, target):
    diet = [cell for cell in placed if cell.group.pk in protocols]
    if not diet:
        return []
    bands = {}
    for protocol_id, feed_id in ProtocolBand.objects.filter(
            protocol_id__in={protocol.pk for protocol in protocols.values()}).values_list('protocol_id', 'feed_id'):
        bands.setdefault(protocol_id, set()).add(feed_id)
    given = {}
    for unit_id, day, feed_id, kilos in (
            FeedingRecord.objects.filter(unit_id__in={cell.unit.pk for cell in diet},
                                         date__gte=min(cell.first for cell in diet), date__lte=today, target=target)
            .order_by().values_list('unit_id', 'date', 'feed_id', 'amount_kg')):
        given.setdefault(unit_id, []).append((day, feed_id, kilos))
    feeds = Feed.all_objects.in_bulk({feed_id for rows in given.values() for _day, feed_id, _kilos in rows})
    found = []
    for cell in diet:
        protocol = protocols[cell.group.pk]
        off = {}
        for day, feed_id, kilos in given.get(cell.unit.pk, ()):
            if cell.first <= day <= _until(cell, today) and feed_id not in bands.get(protocol.pk, ()):
                off.setdefault(feed_id, []).append((day, kilos))
        for feed_id, rows in sorted(off.items(), key=lambda item: feeds[item[0]].name):
            days = sorted(day for day, _kilos in rows)
            found.append(Deviation(FEED_OFF_BAND, cell, days[0], days[-1], _(
                '%(tank)s was fed %(feed)s (%(count)s feedings, %(kilos)s kg), which is on no band of %(protocol)s.') % {
                'tank': cell.unit.code, 'feed': feeds[feed_id].name, 'count': len(rows),
                'kilos': number_format(sum((kilos for _day, kilos in rows), Decimal(0)), 1),
                'protocol': protocol.name}, feeds[feed_id].name))
    return found


def _ration_off_diet(placed, protocols, presence, mine, units, today):
    diet = [cell for cell in placed if cell.group.pk in protocols]
    if not diet:
        return []
    policy = feeding_read.policy({cell.unit.pk: units[cell.unit.pk] for cell in diet}, mine,
                                 min(cell.first for cell in diet), timezone.now())
    found = []
    for cell in diet:
        wanted, unit_id, off = protocols[cell.group.pk], cell.unit.pk, {}
        for batch_id in presence.batches.get(unit_id, ()):
            if batch_id not in mine:
                continue
            for day in _days(cell.first, _until(cell, today)):
                if presence.present(unit_id, batch_id, day):
                    row = policy.resolve(unit_id, batch_id, day)[0]
                    if row is None or row.protocol_id != wanted.pk:
                        off.setdefault(row.protocol.name if row is not None else '', []).append(day)
        for actual, days in sorted(off.items()):
            for first, last in _runs(sorted(set(days))):
                values = {'tank': cell.unit.code, 'protocol': wanted.name, 'first': first.isoformat(),
                          'last': last.isoformat(), 'actual': actual}
                text = (_('The ration of %(tank)s follows %(actual)s, though %(protocol)s is the diet of its group, from '
                         '%(first)s to %(last)s.') if actual else
                        _('No feeding protocol reaches %(tank)s, though %(protocol)s is the diet of its group, from '
                          '%(first)s to %(last)s.'))
                found.append(Deviation(RATION_OFF_DIET, cell, first, last, text % values, actual))
    return found


# ---- the chip beside a unit on the farm's pages ------------------------------------------------------------------------
def chips(units, user):
    """{unit id: [farm.placements.Placement]}: the experiment, group and replicate each unit is booked to on its site's today
    (drafts reserve their tanks, so they show too), for a person who may read experiments and the experiment's places
    (core.sealing: its team, a grantee of its systems, anyone for an open one); one read of `placements` for each
    distinct day, so the farm's pages do not grow with their units.

    A person who holds Oversee sees, on a tank of an experiment they may not read, the card instead (plan 3, owner
    decision C2.5): "Research trial", its lead, its approval and its days; never its number, name, group, replicate or
    team, and no link. Each such card read is in the read log (`oversee`)."""
    by_day = {}
    for unit in units:
        by_day.setdefault(local_today(unit), []).append(unit.pk)
    found = {}
    if user.has_perm('experiments.view_experiment'):
        for day, unit_ids in by_day.items():
            for unit_id, cell in placements(unit_ids, day).items():
                experiment = cell.group.experiment
                found[unit_id] = [farm_placements.Placement(
                    label=f'{experiment.code} · {cell.group.name} · R{cell.replicate.number}',
                    title=f'{experiment.name} ({experiment.get_status_display()})',
                    url=reverse('experiments:experiment_detail', args=[experiment.pk]))]
    if user.has_perm('experiments.oversee_experiment') and not user.is_superuser:
        for day, unit_ids in by_day.items():
            for unit_id, card in cards([pk for pk in unit_ids if pk not in found], day).items():
                found[unit_id] = [card]
    return found


def cards(unit_ids, day):
    """{unit id: Placement} the card of the experiment each tank is booked to on `day`, read as the system (the card says
    only what a person overseeing the tank must know), each card logged as an `oversee` read."""
    if not unit_ids:
        return {}
    found = {}
    with sealing.system('the oversee card'):
        rows = (ReplicateUnit.objects.filter(unit_id__in=list(unit_ids), from_on__lte=day, until_on__gte=day,
                                             replicate__is_deleted=False, replicate__group__is_deleted=False,
                                             replicate__group__experiment__is_deleted=False)
                .select_related('replicate__group__experiment'))
        lines = {}
        for row in rows:
            experiment = row.replicate.group.experiment
            lead = experiment.members.filter(role='lead').select_related('user').first()
            lines[row.unit_id] = (experiment, lead.user if lead else None, row.from_on, row.until_on)
    for unit_id, (experiment, lead, first, last) in lines.items():
        parts = [_('Lead: %(name)s') % {'name': person_name(lead)}] if lead else []
        if experiment.approval_ref:
            parts.append(_('Approval %(ref)s') % {'ref': experiment.approval_ref} + (
                ' ' + _('valid until %(day)s') % {'day': date_format(experiment.approval_valid_until)}
                if experiment.approval_valid_until else ''))
        parts.append(_('%(first)s to %(last)s') % {'first': date_format(first), 'last': date_format(last)})
        found[unit_id] = farm_placements.Placement(label=_('Research trial'), title=' · '.join(parts), url='')
        sealing.log_access('oversee', 'unit', unit_id, part='systems', route='experiments.read.cards')
    return found
