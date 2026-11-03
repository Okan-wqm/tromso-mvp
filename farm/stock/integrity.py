"""Every rule of the stock, checked from scratch over the whole ledger (stock-db §6.5), the one rule
the feeding and health records share with it: every live feeding finds fish in its unit at the start or the
end of its day, as every live treatment on its first day and every sea-lice count on its day, and the rows a
harvest adds (its record, the plan it fulfils, the warnings acknowledged). The stock, feeding and health
services hold these on every write; this finds a row that got past them (a hand edit in
the database, a bug). `manage.py check_stock` prints what it finds; the test suite runs
it after its stock tests. Its messages are for the developer, in English."""
from collections import Counter, defaultdict

from django.db.models import Sum

from farm.feeding import read as feeding_read
from farm.feeding.fold import walk
from farm.health import read as health_read
from farm.models import (
    Batch, DeliveryRecord, EscapeRecord, HandlingAcknowledgement, HandlingPlanItem, HarvestRecord, Species,
    StockMovement, StockOperation, Tank,
)
from farm.models.handling import KIND_OF_OPERATION
from farm.models.harvest import FULFILLED_BY
from farm.models.stock import MovementKind, OperationKind
from farm.models.tank import NEEDS_FISH, NEEDS_NO_FISH

from . import read
from .fold import StockError, fold

# The lines each kind of operation is made of (a cross-row rule, so not a CHECK).
ONE_LINE = {OperationKind.MORTALITY: MovementKind.MORTALITY, OperationKind.CULL: MovementKind.CULL,
            OperationKind.WEIGHING: MovementKind.WEIGHING, OperationKind.ADJUSTMENT: MovementKind.ADJUSTMENT,
            OperationKind.DELIVERY: MovementKind.DELIVERY}


def _operation_problems(operation, lines, batches):
    name = f'{operation.get_kind_display()} {operation.pk} of {operation.date}'
    kinds = Counter(line.kind for line in lines)
    if not lines:
        return [f'{name} has no lines.']
    problems = []
    if len({line.batch_id for line in lines}) != 1:
        problems.append(f'{name} has lines of several batches.')
    if operation.kind == OperationKind.INPUT:
        if set(kinds) != {MovementKind.INPUT}:
            problems.append(f'{name} has lines other than stocking lines.')
        if len({line.unit_id for line in lines}) != len(lines):
            problems.append(f'{name} stocks a unit twice.')
        batch = batches.get(lines[0].batch_id)
        if batch is not None and batch.input_date != operation.date:
            problems.append(f'{name} is not on the stocking date of {batch.code} ({batch.input_date}).')
    elif operation.kind in ONE_LINE:
        if len(lines) != 1 or lines[0].kind != ONE_LINE[operation.kind]:
            problems.append(f'{name} must be one {ONE_LINE[operation.kind]} line.')
    elif operation.kind in (OperationKind.TRANSFER, OperationKind.GRADING):
        pairs = defaultdict(int)
        sources = set()
        for line in lines:
            if line.pair is not None:
                pairs[line.pair] += line.count_delta
            if line.kind == MovementKind.TRANSFER_OUT:
                sources.add(line.unit_id)
        if any(pairs.values()):
            problems.append(f'{name} does not move as many fish in as out.')
        if len(sources) != 1:
            problems.append(f'{name} has {len(sources)} source units.')
        if any(line.kind == MovementKind.TRANSFER_IN and line.unit_id in sources for line in lines):
            problems.append(f'{name} moves fish into its own source.')
    elif operation.kind == OperationKind.HARVEST:
        if kinds[MovementKind.HARVEST] != 1 or set(kinds) - {MovementKind.HARVEST, MovementKind.ADJUSTMENT}:
            problems.append(f'{name} must be one harvest line and at most one adjustment.')
    return problems


def problems():
    """Every broken rule of the stock, as sentences; empty when the stock adds up."""
    found = []
    batches = Batch.all_objects.in_bulk()
    operations = StockOperation.objects.in_bulk()
    lines_of = defaultdict(list)
    for line in StockMovement.objects.filter(operation__is_deleted=False):
        lines_of[line.operation_id].append(line)
    for operation in operations.values():
        found += _operation_problems(operation, lines_of.get(operation.pk, []), batches)

    inputs = Counter()
    for operation in operations.values():
        if operation.kind == OperationKind.INPUT and lines_of.get(operation.pk):
            inputs[lines_of[operation.pk][0].batch_id] += 1
    for batch in batches.values():
        if not batch.is_deleted and inputs[batch.pk] != 1:
            found.append(f'Batch {batch.code} has {inputs[batch.pk]} live stocking operations instead of one.')
        if batch.is_deleted and inputs[batch.pk]:
            found.append(f'Batch {batch.code} is voided but its stocking counts.')

    shares = {}
    broken = False
    for batch_id in batches:
        try:
            shares.update(fold(read.ledger([batch_id])))
        except StockError as error:
            broken = True
            line = error.line
            found.append(f'Batch {batches[batch_id].code}: {error.reason} at line {line.id} '
                         f'({line.kind} {line.count_delta:+d} in unit {line.unit_id} on {line.op.date}).')
    if not broken:      # a broken batch is reported above; its units' feedings cannot be placed
        codes = dict(Tank.all_objects.values_list('pk', 'code'))
        health = health_read.dated_records(list(codes))
        walked = walk(read.ledger(list(batches)), feeding_read.feedings(),
                      days=[(unit_id, day) for _kind, _record, unit_id, day in health])
        for feeding in walked.orphans:
            found.append(f'Feeding {feeding.id} of {feeding.date} in unit {codes[feeding.unit_id]}: no fish in '
                         f'the unit at the start or the end of that day.')
        for kind, record, unit_id, day in health:
            if not health_read.has_fish_for(kind, walked.days[(unit_id, day)]):
                found.append(f'{kind.replace("_", " ").capitalize()} {record.pk} of {day} in unit {codes[unit_id]}: '
                             f'no fish in the unit at the start or the end of that day.')
    sums = (StockMovement.objects.filter(operation__is_deleted=False).values('unit_id', 'batch_id')
            .annotate(fish=Sum('count_delta')))
    for row in sums:
        share = shares.get((row['unit_id'], row['batch_id']))
        if share is not None and share.count != row['fish']:
            found.append(f'Unit {row["unit_id"]}, batch {row["batch_id"]}: the fold has {share.count} fish, '
                         f'the lines add up to {row["fish"]}.')

    found += _harvest_problems(operations, lines_of)
    found += _record_problems(operations, lines_of)

    counts = read.unit_counts(list(Tank.all_objects.values_list('pk', flat=True)))
    species = defaultdict(set)
    for (unit_id, batch_id), share in shares.items():
        if share.count:
            species[unit_id].add(batches[batch_id].species_id)
    cleaner = set(Species.all_objects.exclude(cleaner_fish_type='').values_list('pk', flat=True))
    sea = read.sea_units(list(species))
    for unit in Tank.all_objects.all():
        fish = counts.get(unit.pk, 0)
        if fish and unit.is_deleted:
            found.append(f'Unit {unit.code} is deleted but holds {fish} fish.')
        if fish and unit.status in NEEDS_NO_FISH:
            found.append(f'Unit {unit.code} is {unit.status} but holds {fish} fish.')
        if not fish and unit.status in NEEDS_FISH and not unit.is_deleted:
            found.append(f'Unit {unit.code} is {unit.status} but holds no fish.')
        if read.mixed(species[unit.pk], cleaner, unit.pk in sea):
            found.append(f'Unit {unit.code} holds {len(species[unit.pk])} species.')
    return found


def _record_problems(operations, lines_of):
    """What an escape and a delivery add to their operation: every count adjustment on its own is an escape with its
    record (the line's reason says so), every delivery has where the fish went, and no other kind of operation has one."""
    found = []
    escapes = EscapeRecord.all_objects.select_related('operation').in_bulk()
    deliveries = DeliveryRecord.all_objects.select_related('operation').in_bulk()
    for operation in operations.values():
        name = f'{operation.get_kind_display()} {operation.pk} of {operation.date}'
        if operation.kind == OperationKind.ADJUSTMENT:
            if operation.pk not in escapes:
                found.append(f'{name} has no escape record (a count adjustment on its own is an escape).')
            elif any(line.reason != 'escape' for line in lines_of.get(operation.pk, [])):
                found.append(f'{name} has an escape record and a line of another reason.')
        if operation.kind == OperationKind.DELIVERY and operation.pk not in deliveries:
            found.append(f'{name} has no delivery record (who received the fish).')
    for records, kind, what in ((escapes, OperationKind.ADJUSTMENT, 'an escape record'),
                                (deliveries, OperationKind.DELIVERY, 'a delivery record')):
        for record in records.values():
            if record.operation.kind != kind:
                found.append(f'{record.operation.get_kind_display()} {record.operation_id} has {what}.')
    return found


def _harvest_problems(operations, lines_of):
    """What the harvest adds to an operation, checked across rows: every live harvest names where its fish
    went (one HarvestRecord) and no other kind of operation has a record; a plan item is fulfilled by an
    operation of its kind, of its unit and batch; an acknowledgement belongs to a handling."""
    found = []
    records = HarvestRecord.all_objects.select_related('operation').in_bulk()
    for operation in operations.values():
        if operation.kind == OperationKind.HARVEST and operation.pk not in records:
            found.append(f'Harvest {operation.pk} of {operation.date} has no harvest record (slaughter facility).')
    for record in records.values():
        if record.operation.kind != OperationKind.HARVEST:
            found.append(f'{record.operation.get_kind_display()} {record.operation_id} has a harvest record.')
    for item in HandlingPlanItem.all_objects.filter(is_deleted=False, operation__isnull=False).select_related(
            'operation'):
        operation = item.operation
        if operation.kind != FULFILLED_BY[item.kind]:
            found.append(f'Plan item {item.pk} ({item.kind}) is fulfilled by a {operation.kind}.')
            continue
        source = next((line for line in lines_of.get(operation.pk, []) if line.count_delta < 0), None)
        if source is not None and (source.unit_id, source.batch_id) != (item.unit_id, item.batch_id):
            found.append(f'Plan item {item.pk} names other fish than the {operation.kind} that fulfils it.')
    handled = set(KIND_OF_OPERATION)
    for row in HandlingAcknowledgement.objects.filter(operation__isnull=False).select_related('operation'):
        if row.operation.kind not in handled:
            found.append(f'Acknowledgement {row.pk} belongs to a {row.operation.kind}, which is not a handling.')
    return found
