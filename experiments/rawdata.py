"""An experiment's raw data, one CSV for its team (owner 2026-11-24): the platform keeps the fish's welfare, collects
clean data and keeps it confidential; the analysis is the experiment owner's, on their own computer.

One row per value recorded on a tank of the experiment on its days (each placement, read.cells): the feeding records
fed to the experiment's fish (read.feed_target), the stock lines (counts and weights: stocked, died, weighed,
moved), the sea-lice counts and the water measured at the tank's own sampling points or its system's. Long format, so
every kind of record fits the same columns: date (dd.mm.yyyy), time (HH:MM on the site's clock, or empty), group,
replicate, tank, record, source (the feed, the operation, the sampling point), variable (the column's code, its unit in
its name) and value (a dot for decimals, as analysis tools read it). Voided records are not there.

Who may download it: whoever reads the experiment's data (its team, a grantee of the data or the results;
experiments.sealing.parts_of); every download goes to the read log (core.sealing.log_access, EXPORT), the team's too."""
import csv
import io
from django.utils import timezone

from core import sealing
from core.dates import company_zone
from farm.models.site import zone_of
from farm.feeding import read as feeding_read
from farm.health import read as health_read
from farm.stock import read as stock_read
from farm.water import read as water_read
from farm.water.parameters import COLUMNS as WATER_COLUMNS

from . import read

HEADER = ('date', 'time', 'group', 'replicate', 'tank', 'record', 'source', 'variable', 'value')
STOCK_VALUES = ('count_delta', 'avg_weight_g', 'measured_weight_kg', 'sample_count', 'sample_weight_kg')
LICE_VALUES = ('fish_counted', 'adult_females', 'mobile', 'attached')


def _day(value):
    return value.strftime('%d.%m.%Y')


def _clock(value):
    return '' if value is None else value.strftime('%H:%M')


def _number(value):
    return '' if value is None else format(value, 'f') if not isinstance(value, int) else str(value)


def rows(experiment):
    """The CSV's rows (HEADER's columns), ordered by day, time, tank, record and variable."""
    found = []
    cells = read.cells(experiment)
    if not cells:
        return found
    zone = zone_of(experiment.site)       # the site's clock: its days, as the seal reads them (review 3, S4)
    target = read.feed_target(experiment)
    units = {cell.unit.pk for cell in cells}
    first, last = min(cell.first for cell in cells), max(cell.last for cell in cells)

    def places(unit_id, day):
        return [cell for cell in cells if cell.unit.pk == unit_id and cell.first <= day <= cell.last]

    def add(cell, day, clock, record, source, values):
        for variable, value in values:
            if value is not None:
                found.append((day, clock, cell.group.name, f'R{cell.replicate.number}', cell.unit.code, record, source,
                              variable, _number(value)))

    for row in feeding_read.records(units, first, last, target):
        for cell in places(row.unit_id, row.date):
            add(cell, row.date, _clock(row.time), 'feeding', row.feed.code or row.feed.name,
                [('amount_kg', row.amount_kg), ('meals', row.meals)])
    for line in stock_read.lines_of(units, first, last):
        for cell in places(line.unit_id, line.operation.date):
            add(cell, line.operation.date, '', 'stock', f'{line.operation.kind} {line.kind} {line.batch.code}',
                [(name, getattr(line, name)) for name in STOCK_VALUES])
    for count in health_read.lice_counts(units, first, last):
        for cell in places(count.unit_id, count.date):
            add(cell, count.date, '', 'lice', '', [(name, getattr(count, name)) for name in LICE_VALUES])
    systems = {cell.unit.system_id for cell in cells if cell.unit.system_id}
    for sample in water_read.live_samples_at(units, systems):
        moment = timezone.localtime(sample.measured_at, zone)
        day = sealing.day_on(sample.measured_at, zone)
        if not first <= day <= last:
            continue
        reached = ([sample.point.unit_id] if sample.point.unit_id else
                   [cell.unit.pk for cell in cells if cell.unit.system_id == sample.point.system_id])
        for unit_id in dict.fromkeys(reached):
            for cell in places(unit_id, day):
                add(cell, day, _clock(moment), 'water', sample.point.name,
                    [(code, getattr(sample, code)) for code in WATER_COLUMNS])
    found.sort(key=lambda row: (row[0], row[1], row[4], row[5], row[6], row[7]))
    return [(_day(row[0]), *row[1:]) for row in found]


def csv_text(experiment):
    """The CSV, with its header, as text (UTF-8 with a byte-order mark, so a spreadsheet reads its letters right)."""
    out = io.StringIO()
    out.write('﻿')
    writer = csv.writer(out, lineterminator='\n')
    writer.writerow(HEADER)
    writer.writerows(rows(experiment))
    return out.getvalue()


def filename(experiment, now=None):
    """`<code>-raw-data-<yyyy-mm-dd>.csv` (the day on the company's clock, sortable in a folder)."""
    day = timezone.localtime(now or timezone.now(), company_zone()).date()
    return f'{experiment.code}-raw-data-{day:%Y-%m-%d}.csv'
