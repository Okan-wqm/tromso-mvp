"""Every rule of the stock, checked from scratch over the whole ledger (stock-db §6.5). The stock
service holds these on every write; this finds a row that got past it (a hand edit in the database, a
bug). `manage.py check_stock` prints what it finds; the test suite runs it after its stock tests.
Its messages are for the developer, in English."""
from collections import Counter, defaultdict

from django.db.models import Sum

from farm.models import Batch, StockMovement, StockOperation, Tank
from farm.models.stock import MovementKind, OperationKind
from farm.models.tank import NEEDS_FISH, NEEDS_NO_FISH

from . import read
from .fold import StockError, fold

# The lines each kind of operation is made of (a cross-row rule, so not a CHECK).
ONE_LINE = {OperationKind.MORTALITY: MovementKind.MORTALITY, OperationKind.CULL: MovementKind.CULL,
            OperationKind.WEIGHING: MovementKind.WEIGHING, OperationKind.ADJUSTMENT: MovementKind.ADJUSTMENT}


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
    for batch_id in batches:
        try:
            shares.update(fold(read.ledger([batch_id])))
        except StockError as error:
            line = error.line
            found.append(f'Batch {batches[batch_id].code}: {error.reason} at line {line.id} '
                         f'({line.kind} {line.count_delta:+d} in unit {line.unit_id} on {line.op.date}).')
    sums = (StockMovement.objects.filter(operation__is_deleted=False).values('unit_id', 'batch_id')
            .annotate(fish=Sum('count_delta')))
    for row in sums:
        share = shares.get((row['unit_id'], row['batch_id']))
        if share is not None and share.count != row['fish']:
            found.append(f'Unit {row["unit_id"]}, batch {row["batch_id"]}: the fold has {share.count} fish, '
                         f'the lines add up to {row["fish"]}.')

    counts = read.unit_counts(list(Tank.all_objects.values_list('pk', flat=True)))
    species = defaultdict(set)
    for (unit_id, batch_id), share in shares.items():
        if share.count:
            species[unit_id].add(batches[batch_id].species_id)
    for unit in Tank.all_objects.all():
        fish = counts.get(unit.pk, 0)
        if fish and unit.is_deleted:
            found.append(f'Unit {unit.code} is deleted but holds {fish} fish.')
        if fish and unit.status in NEEDS_NO_FISH:
            found.append(f'Unit {unit.code} is {unit.status} but holds {fish} fish.')
        if not fish and unit.status in NEEDS_FISH and not unit.is_deleted:
            found.append(f'Unit {unit.code} is {unit.status} but holds no fish.')
        if len(species[unit.pk]) > 1:
            found.append(f'Unit {unit.code} holds {len(species[unit.pk])} species.')
    return found
