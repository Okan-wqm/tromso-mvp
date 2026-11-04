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
- `data(experiment)`: per tank its days and the feeding records of them, for the Data tab."""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from farm.feeding import read as feeding_read
from farm.feeding.fold import LOST
from farm.models import Batch, StockMovement
from farm.stock import read as stock_read
from farm.stock.dates import site_today

from .models import ExperimentGroup, Replicate, ReplicateUnit, Status


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


def booked(unit_ids, first, last, exclude=None):
    """{unit id: the Experiment that holds it} for the tanks held on some day from `first` to `last` (both included)
    by an experiment other than `exclude`; one experiment a tank (the exclusion constraint allows no more)."""
    found = {}
    rows = (ReplicateUnit.objects.filter(unit_id__in=list(unit_ids), from_on__lte=last, until_on__gte=first)
            .select_related('replicate__group__experiment'))
    if exclude is not None:
        rows = rows.exclude(replicate__group__experiment=exclude)
    for placement in rows.order_by('from_on'):
        found.setdefault(placement.unit_id, placement.replicate.group.experiment)
    return found


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
    since, up to its last day or today: one query for the losses of every tank."""
    first = min(cell.first for row in rows for cell in row.cells)
    last = min(max(cell.last for row in rows for cell in row.cells), today)
    lines = (StockMovement.objects.filter(unit_id__in=list(units), batch_id__in=mine, operation__is_deleted=False,
                                          kind__in=LOST, count_delta__lt=0, operation__date__gt=first,
                                          operation__date__lte=last)
             .values_list('unit_id', 'batch_id', 'operation__date', 'count_delta'))
    losses = {}
    for unit_id, batch_id, day, delta in lines:
        losses.setdefault((unit_id, batch_id), []).append((day, -delta))
    for row in rows:
        start = lost = 0
        for cell in row.cells:
            for batch in row.batches:
                start += presence.count_at_end(cell.unit.pk, batch.pk, cell.first)
                lost += sum(count for day, count in losses.get((cell.unit.pk, batch.pk), ())
                            if cell.first < day <= min(cell.last, today))
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


@dataclass
class TankData:
    """A tank of the experiment for the Data tab: its days and the feeding records of them."""
    cell: Cell
    records: int
    kilos: Decimal


def data(experiment):
    """[TankData] of the experiment's tanks, in the order of the design: per placement its days and the feeding records
    of the tank on them (one read of the units' feeding, `feeding.read.feedings`: the count and the feed given)."""
    found = cells(experiment)
    if not found:
        return []
    records = feeding_read.feedings({cell.unit.pk for cell in found}, since=min(cell.first for cell in found))
    result = []
    for cell in found:
        mine = [record for record in records if record.unit_id == cell.unit.pk and cell.first <= record.date <= cell.last]
        result.append(TankData(cell, len(mine), sum((record.amount_kg for record in mine), Decimal(0))))
    return result
