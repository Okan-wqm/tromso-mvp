"""Every rule of the store, checked from scratch over the whole ledger (storage §3.6). The write path holds
these on every write; this finds a row that got past it (a hand edit in the database, a bug).
`manage.py check_inventory` prints what it finds; the test suite runs it after its store tests. Its messages
are for the developer, in English."""
from collections import Counter, defaultdict

from farm.stock.dates import site_today

from . import read
from .fold import physical
from .models import InventoryItem, InventoryLine, InventoryLot, InventoryOperation, LineKind, OperationKind
from .models import StorageLocation
from .services import LOT_REQUIRED

ONE_OUT = (OperationKind.ISSUE, OperationKind.WRITE_OFF, OperationKind.RETURN)


def _operation_problems(operation, lines):
    name = f'{operation.get_kind_display()} {operation.pk} of {operation.date}'
    kinds = Counter(line.kind for line in lines)
    problems = []
    if operation.kind == OperationKind.RECEIPT:
        if not lines or set(kinds) != {LineKind.IN}:
            problems.append(f'{name} must be delivered lines only, at least one.')
        for line in lines:
            if line.lot.item.category not in operation.supplier.supplies:
                problems.append(f'{name}: {operation.supplier.code} does not supply {line.lot.item.category}.')
    elif operation.kind in ONE_OUT:
        if len(lines) != 1 or lines[0].kind != LineKind.OUT:
            problems.append(f'{name} must be one line out.')
        if operation.kind == OperationKind.RETURN:
            for line in lines:
                if line.lot.item.category not in operation.supplier.supplies:
                    problems.append(f'{name}: {operation.supplier.code} does not supply {line.lot.item.category}.')
    elif operation.kind == OperationKind.TRANSFER:
        pairs = defaultdict(list)
        for line in lines:
            pairs[line.pair].append(line)
        if not pairs or set(kinds) - {LineKind.TRANSFER_OUT, LineKind.TRANSFER_IN}:
            problems.append(f'{name} must be pairs of lines moved out and in.')
        for pair, members in pairs.items():
            if sorted(line.kind for line in members) != [LineKind.TRANSFER_IN, LineKind.TRANSFER_OUT] \
                    or sum(line.quantity for line in members) != 0 or len({line.lot_id for line in members}) != 1 \
                    or len({line.location_id for line in members}) != 2:
                problems.append(f'{name}: pair {pair} does not move one lot from one location to another.')
    elif operation.kind == OperationKind.COUNT:
        if set(kinds) - {LineKind.COUNT}:
            problems.append(f'{name} has lines other than counted ones.')
        if any(line.location_id != operation.location_id for line in lines):
            problems.append(f'{name} counts lines outside its location.')
    if any(line.unit_cost is not None for line in lines) and operation.kind != OperationKind.RECEIPT:
        problems.append(f'{name} has a unit cost but is not a delivery.')
    return problems


def problems():
    """Every broken rule of the store, as sentences; empty when it adds up."""
    found = []
    lines_of = defaultdict(list)
    for line in InventoryLine.objects.filter(operation__is_deleted=False).select_related('lot__item'):
        lines_of[line.operation_id].append(line)
    for operation in InventoryOperation.objects.select_related('supplier'):
        found += _operation_problems(operation, lines_of.get(operation.pk, []))
    for item in InventoryItem.all_objects.all():
        if item.feed_id is None:
            found.append(f'Item {item.pk} links to nothing.')
    for lot in InventoryLot.objects.select_related('item'):
        if lot.item.category in LOT_REQUIRED and (not lot.number or lot.expiry_date is None):
            found.append(f'Lot {lot.pk} of {lot.item.category} has no number or no expiry.')
        if lot.number != lot.number.strip():
            found.append(f'Lot {lot.pk} has spaces around its number.')
    lines, counts = read.physical_lines(None)
    for item_id, item_lines in lines.items():
        shortfall = physical(item_lines, counts)
        if shortfall is not None:
            line = shortfall.line
            found.append(f'Item {item_id}: line {line.id} ({line.kind} {line.quantity} on {line.op.day}) takes its '
                         f'lot below 0; {shortfall.available} was there.')
    deleted = StorageLocation.all_objects.filter(is_deleted=True).select_related('site').in_bulk()
    if deleted:
        for fold in read.folds().values():
            for bucket in fold.segments:
                place = deleted.get(bucket[0])
                if place is not None and fold.balance(bucket, site_today(place.site)):
                    found.append(f'Location {place.code} is deleted but holds stock.')
    return found
