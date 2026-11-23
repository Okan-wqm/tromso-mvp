"""The one write path of the store (storage §3.4). Every operation is one function here and goes through
`_commit`, the only code that writes InventoryOperation and InventoryLine rows. In one transaction it:

1. locks the items, then the locations, each in primary-key order (two writers of one item or one
   location take turns; a feeding takes no lock: it never waits for the store);
2. refuses a form sent twice (its token) and checks what needs no folding: the date on the clock of every
   site it touches (the farm's dates, farm/stock/dates.py: not in the future, at most the correction window
   back), live locations, arrivals into active locations only, the lot of the item, a live supplier that
   supplies the item's category, lot number and expiry where the category needs them (owner decision
   Q-S5: not for feed, yes for medicines);
3. writes the operation and its lines, a lot the delivery (or count) names for the first time with them;
4. folds every item it touches, its lines alone (inventory/fold.py `physical`), and refuses when a
   departure would take a lot in a location below 0, on its day or later: a backdated operation is
   placed where it belongs and accepted only if every later day stays right. Feeding is not part of
   this check: it is drawn on read and never refuses or is refused (Q-S1);
5. writes the activity log.

A failure raises ValidationError (a dict of field to message: 'date', 'location', 'destination', 'lot',
'supplier', 'quantity', 'lines', 'reason', 'notes' or NON_FIELD_ERRORS) and nothing is written. A void
is the undo: the farm's one void (farm.stock.services.voided) and step 4 without the operation; a lot left
without live lines goes with it."""
from dataclasses import dataclass

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import connection, transaction
from django.db.models.functions import Upper
from django.utils.translation import gettext as _

from core import audit
from core.models import AuditLog, EntryKey
from farm.models.supplier import SupplyCategory
from farm.stock.dates import check_site_date, shown_date, site_today
from farm.stock.services import AlreadyRecorded, locked, needs_notes, voided
from farm.templatetags.feeding import amount

from . import read
from .fold import physical
from .models import (
    InventoryItem, InventoryLine, InventoryLot, InventoryOperation, LineKind, OperationKind, StorageLocation, Unit,
)

__all__ = ['AlreadyRecorded', 'count', 'issue', 'item_for', 'receive', 'return_to_supplier', 'transfer', 'void',
           'write_off']

# The categories whose lots need their number and expiry (owner decision Q-S5): medicines, once the health
# module's Medicine is an item of the store; feed may have neither.
LOT_REQUIRED = {SupplyCategory.MEDICINES}
ARRIVING = (LineKind.IN, LineKind.TRANSFER_IN)


@dataclass
class NewLot:
    """A lot a delivery or a count names by its number and expiry: found, or made, inside the transaction."""
    item: InventoryItem
    number: str
    expiry: object = None


@dataclass
class Entry:
    lot: object             # InventoryLot or NewLot
    location: StorageLocation
    kind: str
    quantity: object
    pair: int = None
    unit_cost: object = None
    currency: str = ''


# ---- items and lots ------------------------------------------------------------------------------
def item_for(feed, user=None):
    """The store's item of a feed, made the first time it is needed (a delivery, a reorder level). An
    advisory lock makes two writers take turns for it."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('inventory_items'))")
        item = InventoryItem.objects.filter(feed=feed).first()
        if item is None:
            item = InventoryItem.objects.create(feed=feed, unit=Unit.KG, created_by=user, updated_by=user)
            with audit.source_language():
                audit.record_create(user, item, audit.snapshot(item, ['feed', 'unit']))
        return item


def lot_label(lot):
    """A lot as messages name it: its number, else its expiry, else that it has none."""
    if lot.number:
        return lot.number
    if lot.expiry_date:
        return _('no number, expiring %(date)s') % {'date': shown_date(lot.expiry_date)}
    return _('no number')


def _check_lot(category, number, expiry):
    if category in LOT_REQUIRED and (not number or expiry is None):
        raise ValidationError({'lines': _('A lot of %(category)s needs its number and its expiry date.') % {
            'category': str(SupplyCategory(category).label).lower()}})


def _resolve(user, wanted):
    """The InventoryLot of a NewLot: the live lot of the item with that number (any case), or, without a
    number, with that expiry; made when there is none. A known number with another expiry is refused."""
    number = wanted.number.strip()
    _check_lot(wanted.item.category, number, wanted.expiry)
    lots = InventoryLot.objects.filter(item=wanted.item)
    lot = (lots.annotate(upper=Upper('number')).filter(upper=number.upper()).first() if number
           else lots.filter(number='', expiry_date=wanted.expiry).first())
    if lot is not None:
        if number and wanted.expiry is not None and lot.expiry_date != wanted.expiry:
            raise ValidationError({'lines': (
                _('Lot %(lot)s of %(item)s is recorded with the expiry date %(date)s.') if lot.expiry_date else
                _('Lot %(lot)s of %(item)s is recorded without an expiry date.')) % {
                'lot': lot.number, 'item': wanted.item, 'date': shown_date(lot.expiry_date) if lot.expiry_date else ''}})
        return lot
    lot = InventoryLot.objects.create(item=wanted.item, number=number, expiry_date=wanted.expiry, created_by=user,
                                      updated_by=user)
    with audit.source_language():
        audit.record_create(user, lot, audit.snapshot(lot, ['item', 'number', 'expiry_date']), label=_lot_name(lot))
    return lot


def _lot_name(lot):
    """How the activity log names a lot: its item and number (English, like every log row)."""
    return f'{lot.item} · {lot.number or "-"}{f" · {lot.expiry_date.isoformat()}" if lot.expiry_date else ""}'


# ---- the one write path --------------------------------------------------------------------------
def _already(token):
    if token is not None:
        done = EntryKey.record_of(token, InventoryOperation)
        if done is not None:
            raise AlreadyRecorded(done)


def _commit(user, kind, day, entries, *, location=None, supplier=None, reference='', reason='', notes='',
            token=None):
    """Writes an operation and its lines (see the module's docstring); returns the operation."""
    with transaction.atomic():
        items = locked(InventoryItem, {entry.lot.item.pk for entry in entries}
                       | set(_items_at(location) if location is not None else ()))
        places = {entry.location.pk for entry in entries} | ({location.pk} if location is not None else set())
        locations = locked(StorageLocation, places)
        _already(token)
        _check_static(kind, day, entries, locations, supplier)
        for entry in entries:
            if isinstance(entry.lot, NewLot):
                entry.lot = _resolve(user, entry.lot)
            elif entry.lot.is_deleted:
                raise ValidationError({'lot': _('Lot %(lot)s was voided.') % {'lot': lot_label(entry.lot)}})
        seen = set()
        for entry in entries:
            key = (entry.lot.pk, entry.location.pk, entry.kind, entry.pair)
            if key in seen:
                raise ValidationError({'lines': _('Lot %(lot)s of %(item)s in %(location)s is listed twice.') % {
                    'lot': lot_label(entry.lot), 'item': entry.lot.item, 'location': entry.location.code}})
            seen.add(key)
        operation = InventoryOperation.objects.create(
            kind=kind, date=day, location=locations[location.pk] if location is not None else None,
            supplier=supplier, reference=reference.strip(), reason=reason, notes=notes.strip(),
            created_by=user, updated_by=user)
        if token is not None:
            EntryKey.note(token, operation)
        InventoryLine.objects.bulk_create([
            InventoryLine(operation=operation, lot=entry.lot, location=locations[entry.location.pk], kind=entry.kind,
                          quantity=entry.quantity, pair=entry.pair, unit_cost=entry.unit_cost,
                          currency=entry.currency)
            for entry in entries])
        _check_timeline(set(items), operation.pk)
        _log(user, AuditLog.Action.CREATE, operation)
        return operation


def _items_at(location):
    """The items that ever had a line in `location` (a count sets them all)."""
    return InventoryItem.all_objects.filter(lots__lines__location=location).values_list('pk', flat=True).distinct()


def _check_static(kind, day, entries, locations, supplier):
    for place in locations.values():
        if place.is_deleted:
            raise ValidationError({'location': _('%(location)s is deleted.') % {'location': place.code}})
    check_site_date(day, [place.site for place in locations.values()])
    for entry in entries:
        place = locations[entry.location.pk]
        if entry.kind in ARRIVING and place.status != StorageLocation.Status.ACTIVE:
            field = 'destination' if entry.kind == LineKind.TRANSFER_IN else 'location'
            raise ValidationError({field: _('%(location)s is inactive: it takes no new stock.') % {
                'location': place.code}})
    if supplier is not None:
        if supplier.is_deleted:
            raise ValidationError({'supplier': _('%(supplier)s is deleted.') % {'supplier': supplier}})
        for entry in entries:
            category = entry.lot.item.category
            if category not in supplier.supplies:
                raise ValidationError({'supplier': _('%(supplier)s is not a supplier of %(category)s (Purchasing › '
                                                     'Suppliers).') % {
                    'supplier': supplier, 'category': str(SupplyCategory(category).label).lower()}})


def _check_timeline(item_ids, new_op_id=None):
    """Step 4: the physical book of every item (its lines alone) never below 0; and no deleted location
    holds stock again (a void that brings back what left it)."""
    lines, counts = read.physical_lines(list(item_ids))
    for item_id in item_ids:
        shortfall = physical(lines.get(item_id, []), counts)
        if shortfall is not None:
            raise _explain(shortfall, new_op_id)
    deleted = StorageLocation.all_objects.filter(is_deleted=True, lines__lot__item__in=item_ids).distinct()
    deleted = {place.pk: place for place in deleted.select_related('site')}
    if not deleted:
        return
    for fold in read.folds(InventoryItem.all_objects.filter(pk__in=item_ids)).values():
        for bucket in fold.segments:
            place = deleted.get(bucket[0])
            if place is not None and fold.balance(bucket, site_today(place.site)) > 0:
                raise ValidationError({NON_FIELD_ERRORS: _(
                    '%(location)s is deleted and would hold stock again: restore it first.') % {
                    'location': place.code}})


def _explain(shortfall, new_op_id):
    """The Shortfall as a message a person can act on, on the field it concerns."""
    line = shortfall.line
    lot = InventoryLot.all_objects.select_related('item__feed').get(pk=line.lot)
    place = StorageLocation.all_objects.get(pk=line.location)
    params = {'available': amount(shortfall.available), 'unit': lot.item.get_unit_display(), 'item': lot.item,
              'lot': lot_label(lot), 'location': place.code, 'date': shown_date(line.op.day),
              'operation': str(OperationKind(line.op.kind).label).lower()}
    if line.op.id == new_op_id:
        return ValidationError({'quantity': _(
            'Only %(available)s %(unit)s of %(item)s, lot %(lot)s, are in %(location)s on %(date)s.') % params})
    return ValidationError({NON_FIELD_ERRORS: _(
        'The %(operation)s of %(date)s from %(location)s would be left without its stock: only %(available)s '
        '%(unit)s of %(item)s, lot %(lot)s, would be there. Void that operation first, or correct this one.')
        % params})


def describe(line):
    """One line of an operation for the activity log, in English like every log row."""
    text = f'{line.location.code} · {line.lot.item} · lot {line.lot.number or "-"}'
    if line.lot.expiry_date:
        text += f' (expires {line.lot.expiry_date.isoformat()})'
    sign = '' if line.kind == LineKind.COUNT else ('+' if line.quantity > 0 else '')
    text += f': {audit.english(LineKind(line.kind).label).lower()} {sign}{line.quantity.normalize():f} {line.lot.item.unit}'
    if line.unit_cost is not None:
        text += f' at {line.unit_cost.normalize():f} {line.currency}'
    return text


def label(operation, lines=None):
    """How the activity log names an operation: what, where, which items and lots, when; a search for a
    location's code, a feed's or a lot's number finds it."""
    lines = lines if lines is not None else list(operation.lines.select_related('location', 'lot__item__feed'))
    places = [line.location.code for line in lines] or ([operation.location.code] if operation.location_id else [])
    lots = ', '.join(dict.fromkeys(f'{line.lot.item.product.code} {line.lot.number or "-"}' for line in lines))
    return ' · '.join(part for part in (audit.english(operation.get_kind_display()), ', '.join(dict.fromkeys(places)),
                                        lots, operation.date.isoformat()) if part)


def _log(user, action, operation):
    lines = list(operation.lines.select_related('location', 'lot__item__feed'))
    with audit.source_language():
        names = ['kind', 'date', 'location', 'supplier', 'reference', 'notes']
        changes = {label_: [None, value] for label_, value in audit.snapshot(operation, names).items()
                   if value is not None}
        if operation.reason:
            changes[str(_('Reason'))] = [None, audit.message(operation.reason_label())]
        changes[str(_('Lines'))] = [None, '; '.join(describe(line) for line in lines) or '-']
        audit.record(user, action, operation, changes, label=label(operation, lines))


# ---- the operations ------------------------------------------------------------------------------
def receive(user, *, supplier, day, lines, reference='', notes='', token=None):
    """A delivery from a supplier: `lines` = [(feed, lot number, expiry, location, quantity, unit cost,
    currency)]; a lot named for the first time is made, a known one reused (its expiry must agree)."""
    if not lines:
        raise ValidationError({'lines': _('List what was delivered.')})
    entries = [Entry(NewLot(item_for(feed, user), number, expiry), location, LineKind.IN, quantity,
                     unit_cost=unit_cost, currency=(currency or '').strip().upper())
               for feed, number, expiry, location, quantity, unit_cost, currency in lines]
    for entry in entries:
        if (entry.unit_cost is None) != (not entry.currency):
            raise ValidationError({'lines': _('A unit cost needs its currency, and a currency a unit cost.')})
    return _commit(user, OperationKind.RECEIPT, day, entries, supplier=supplier, reference=reference, notes=notes,
                   token=token)


def _departure(user, kind, *, location, lot, day, quantity, notes='', token=None, **fields):
    return _commit(user, kind, day, [Entry(lot, location, LineKind.OUT, -quantity)], notes=notes, token=token,
                   **fields)


def issue(user, *, location, lot, day, quantity, reason, notes='', token=None):
    """Taken out for a use other than feeding (a treatment, samples, maintenance)."""
    needs_notes(reason, notes)
    return _departure(user, OperationKind.ISSUE, location=location, lot=lot, day=day, quantity=quantity,
                      reason=reason, notes=notes, token=token)


def write_off(user, *, location, lot, day, quantity, reason, notes='', token=None):
    """Thrown away: expired, damaged, contaminated, spilled."""
    needs_notes(reason, notes)
    return _departure(user, OperationKind.WRITE_OFF, location=location, lot=lot, day=day, quantity=quantity,
                      reason=reason, notes=notes, token=token)


def return_to_supplier(user, *, location, lot, day, quantity, supplier, reference='', notes='', token=None):
    """Sent back to a supplier: it leaves the store (the source's return added stock, STR-03)."""
    return _departure(user, OperationKind.RETURN, location=location, lot=lot, day=day, quantity=quantity,
                      supplier=supplier, reference=reference, notes=notes, token=token)


def transfer(user, *, source, lot, destination, day, quantity, notes='', token=None):
    """A lot moved from one location to another, on the same site or another one (owner decision Q-S6),
    dated on both sites' clocks: a pair of lines, out and in, of the same lot."""
    if destination == source:
        raise ValidationError({'destination': _('Choose another location than the one it leaves.')})
    entries = [Entry(lot, source, LineKind.TRANSFER_OUT, -quantity, pair=1),
               Entry(lot, destination, LineKind.TRANSFER_IN, quantity, pair=1)]
    return _commit(user, OperationKind.TRANSFER, day, entries, notes=notes, token=token)


def count(user, *, location, day, lines, found=(), notes='', token=None):
    """One location counted at the end of `day`: `lines` = [(lot, quantity counted)], `found` = [(feed, lot
    number, expiry, quantity)] for lots the book did not have there (a lot never delivered is made, its
    supplier unknown). Everything else the book has there is counted as 0. One person records it, no
    approval (owner decision Q-S7); the variance is read, never stored."""
    entries = [Entry(lot, location, LineKind.COUNT, quantity) for lot, quantity in lines]
    entries += [Entry(NewLot(item_for(feed, user), number, expiry), location, LineKind.COUNT, quantity)
                for feed, number, expiry, quantity in found]
    return _commit(user, OperationKind.COUNT, day, entries, location=location, notes=notes, token=token)


def void(user, operation, reason):
    """The undo: the operation stops counting, with its reason, within the backdating window of its sites.
    Refused when a later departure needs its stock (the message names it); a lot left without live lines
    is voided with it."""
    with transaction.atomic():
        operation = InventoryOperation.all_objects.select_for_update(of=('self',)).get(pk=operation.pk)
        lines = list(operation.lines.select_related('location__site', 'lot__item__feed'))
        item_ids = {line.lot.item_id for line in lines}
        if operation.location_id:
            item_ids |= set(_items_at(operation.location_id))
        locked(InventoryItem, item_ids)
        places = locked(StorageLocation, {line.location_id for line in lines} | (
            {operation.location_id} if operation.location_id else set()))
        voided(user, operation, reason, [place.site for place in places.values()], label(operation, lines),
               check=lambda: _check_timeline(item_ids))
        for lot in {line.lot for line in lines}:
            if not InventoryLine.objects.filter(lot=lot, operation__is_deleted=False).exists():
                lot.soft_delete(user)
                with audit.source_language():
                    audit.record_delete(user, lot, label=_lot_name(lot))
        return operation
