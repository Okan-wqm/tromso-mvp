"""Reading the harvests, computed on read from the stock ledger: nothing about a harvest is stored twice.

- the fish and the round kilos weighed are the harvest line's (`count_delta`, `measured_weight_kg`);
- the book kilos are what the fold took out for that line (farm.stock.read.moved_grams): the fish leave at
  their batch's average in the unit, the last fish take whatever the book holds;
- the difference is weighed − book, in kg and in % of the book: how far the book was from the scale;
- the average weight at harvest is weighed kilos × 1000 ÷ fish;
- the unaccounted loss is the count adjustment a harvest that empties the unit writes, with its book kilos;
- where the fish went is the operation's HarvestRecord; the plan it fulfilled, the plan item that links it.

A voided harvest stays in the history (shown when asked for) and counts in no total; its book kilos are
not worked out, since the fold leaves it out."""
from dataclasses import dataclass, field
from decimal import Decimal

from farm.models import HandlingAcknowledgement, HandlingPlanItem, HarvestRecord, StockMovement
from farm.models.stock import MovementKind
from farm.stock.read import moved_grams

HUNDRED = Decimal(100)
ZERO = Decimal(0)


@dataclass(frozen=True)
class Book:
    """The kilos the book took out for a line, and, for a harvest, the kilos weighed beside them."""
    kg: Decimal
    weighed_kg: Decimal = None

    @property
    def difference_kg(self):
        return None if self.weighed_kg is None else self.weighed_kg - self.kg

    @property
    def difference_pct(self):
        return HUNDRED * self.difference_kg / self.kg if self.weighed_kg is not None and self.kg else None


def add_book(lines):
    """Sets `book` (Book) on the harvest and count-adjustment lines of live operations among `lines`
    (StockMovement, with their operation): one fold for their batches."""
    lines = [line for line in lines if line.kind in (MovementKind.HARVEST, MovementKind.ADJUSTMENT)
             and not line.operation.is_deleted]
    if not lines:
        return
    moved = moved_grams({line.batch_id for line in lines})
    for line in lines:
        grams = moved.get(line.id)
        line.book = None if grams is None else Book(grams / 1000, line.measured_weight_kg)


@dataclass
class Harvest:
    """One harvest operation as the list shows it."""
    line: StockMovement                  # the harvest line, with its operation, unit and batch
    record: HarvestRecord = None         # where the fish went (missing on harvests recorded before it existed)
    loss: StockMovement = None           # the unaccounted loss of a harvest that emptied the unit
    plan: HandlingPlanItem = None
    acknowledged: list = field(default_factory=list)

    @property
    def operation(self):
        return self.line.operation

    @property
    def unit(self):
        return self.line.unit

    @property
    def site(self):
        return self.line.unit.production_department.site

    @property
    def batch(self):
        return self.line.batch

    @property
    def fish(self):
        return -self.line.count_delta

    @property
    def weighed_kg(self):
        return self.line.measured_weight_kg

    @property
    def avg_weight_g(self):
        return self.weighed_kg * 1000 / self.fish

    @property
    def book(self):
        return getattr(self.line, 'book', None)

    @property
    def loss_book(self):
        return getattr(self.loss, 'book', None) if self.loss is not None else None


def harvests(lines):
    """The Harvest of every harvest line in `lines` (a StockMovement queryset of harvest lines), with its
    record, unaccounted loss, plan and acknowledgements, and the book kilos of the live ones."""
    lines = list(lines.select_related(
        'operation__created_by', 'operation__deleted_by', 'unit__production_department__site', 'batch__species'))
    operations = [line.operation_id for line in lines]
    records = HarvestRecord.all_objects.select_related('facility', 'transport').in_bulk(operations)
    losses = {line.operation_id: line for line in StockMovement.objects.filter(
        operation_id__in=operations, kind=MovementKind.ADJUSTMENT).select_related('operation')}
    plans = {item.operation_id: item for item in HandlingPlanItem.all_objects.filter(
        operation_id__in=operations, is_deleted=False)}
    acknowledged = {}
    for row in HandlingAcknowledgement.objects.filter(operation_id__in=operations):
        acknowledged.setdefault(row.operation_id, []).append(row)
    add_book([*lines, *losses.values()])
    return [Harvest(line, records.get(line.operation_id), losses.get(line.operation_id),
                    plans.get(line.operation_id), acknowledged.get(line.operation_id, [])) for line in lines]


@dataclass
class Total:
    """The live harvests of one batch or one site added up."""
    label: str
    fish: int = 0
    weighed_kg: Decimal = ZERO
    book_kg: Decimal = ZERO
    harvests: int = 0

    @property
    def difference_kg(self):
        return self.weighed_kg - self.book_kg

    @property
    def difference_pct(self):
        return HUNDRED * self.difference_kg / self.book_kg if self.book_kg else None

    @property
    def avg_weight_g(self):
        return self.weighed_kg * 1000 / self.fish if self.fish else None

    def add(self, harvest):
        self.fish += harvest.fish
        self.weighed_kg += harvest.weighed_kg
        self.book_kg += harvest.book.kg
        self.harvests += 1


def totals(rows, key, label):
    """[Total] of the live rows grouped by `key(row)`, each named `label(row)`, in the order first met."""
    found = {}
    for row in rows:
        if row.operation.is_deleted or row.book is None:
            continue
        found.setdefault(key(row), Total(label(row))).add(row)
    return list(found.values())
