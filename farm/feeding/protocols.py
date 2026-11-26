"""The write path of a protocol's feeding table, and its copy (Duplicate). A table is saved as a whole: the stored
bands go and the bands given are written with their cells, in one transaction, logged on the protocol as one change
("Feeding table", before and after, in English like every log row). A protocol that is assigned keeps its table
(owner decision Q3): the rations of its past days are read from it, so a change is made on a copy."""
import re

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import transaction
from django.utils.translation import gettext as _, gettext_lazy

from core import access, audit
from core.models import AuditLog
from farm.models import FeedingProtocol, ProtocolBand, ProtocolRate
from farm.models.feeding_protocol import ProtocolStatus

# Who may (asked by each act itself, whoever calls: the data-layering audit, L-6): the protocol pages' rights.
CHANGE, ADD = 'farm.change_feedingprotocol', 'farm.add_feedingprotocol'
TABLE = gettext_lazy('Feeding table')
# The general fields a copy takes over (FeedingProtocol), and how the log names a copy's table.
COPIED = ('species', 'expected_fcr', 'uneaten_pct', 'mortality_pct_month', 'fcr_between', 'uneaten_between',
          'sfr_between', 'notes')


def _number(value):
    return f'{value.normalize():f}'


def describe(protocol):
    """The table as the activity log keeps it: one line per band, e.g. "50–100 g: GR-4, 4 meals, FCR 1.1; 12 °C
    1.1 %, 14 °C 1.3 %"; None without bands."""
    lines = []
    for band in protocol.bands.select_related('feed').prefetch_related('rates').order_by('min_weight_g'):
        upper = _number(band.max_weight_g) if band.max_weight_g is not None else '…'
        fcr = f', FCR {_number(band.expected_fcr)}' if band.expected_fcr is not None else ''
        if band.uneaten_pct is not None:
            fcr += f', uneaten {_number(band.uneaten_pct)} %'
        if band.mortality_pct_month is not None:
            fcr += f', mortality {_number(band.mortality_pct_month)} % a month'
        cells = ', '.join(f'{_number(rate.temperature_c)} °C {_number(rate.sfr_pct)} %'
                          for rate in sorted(band.rates.all(), key=lambda rate: rate.temperature_c))
        lines.append(f'{_number(band.min_weight_g)}–{upper} g: {band.feed.code}, {band.meals_per_day} meals{fcr}; '
                     f'{cells}')
    return '\n'.join(lines) or None


def _write(protocol, columns, rows, column_name):
    for row in rows:
        band = ProtocolBand.objects.create(
            protocol=protocol, min_weight_g=row['min_weight_g'], max_weight_g=row['max_weight_g'], feed=row['feed'],
            meals_per_day=row['meals_per_day'], expected_fcr=row['expected_fcr'],
            uneaten_pct=row.get('uneaten_pct'), mortality_pct_month=row.get('mortality_pct_month'))
        ProtocolRate.objects.bulk_create([ProtocolRate(band=band, temperature_c=temperature,
                                                       sfr_pct=row[column_name(temperature)])
                                          for temperature in columns])


def save_table(user, protocol, columns, rows, version, column_name):
    """Replaces the protocol's table with `rows` (the cleaned bands of the grid, each with a cell per temperature of
    `columns`, read by `column_name`). Refused when the protocol is assigned, or changed since `version`."""
    access.require(user, CHANGE)
    with transaction.atomic():
        protocol = FeedingProtocol.objects.select_for_update().get(pk=protocol.pk)
        if protocol.is_assigned():
            raise ValidationError({NON_FIELD_ERRORS: _('The protocol is assigned, so its table is fixed: duplicate it '
                                                       'to change it.')})
        if version != protocol.version:
            raise ValidationError({NON_FIELD_ERRORS: _('Someone else changed this feeding protocol while you were '
                                                       'editing it. The table now shows their version; make your '
                                                       'changes again.')})
        if not rows and protocol.status == ProtocolStatus.ACTIVE:
            raise ValidationError({NON_FIELD_ERRORS: _('An active protocol has a table.')})
        with audit.source_language():
            before = describe(protocol)
            protocol.bands.all().delete()
            _write(protocol, columns, rows, column_name)
            after = describe(protocol)
            protocol.version += 1
            protocol.updated_by = user
            protocol.save(update_fields=['version', 'updated_by', 'updated_at'])
            if before != after:
                audit.record(user, AuditLog.Action.UPDATE, protocol, {str(TABLE): [before, after]})
        return protocol


def copy_name(name):
    """The first free name of a copy: "Trout grow-out (copy)", then "(copy 2)" and so on."""
    base = re.sub(r' \(copy(?: \d+)?\)$', '', name)
    taken = {item.lower() for item in FeedingProtocol.objects.values_list('name', flat=True)}
    for number in range(1, 1000):
        candidate = f'{base} (copy)' if number == 1 else f'{base} (copy {number})'
        if candidate.lower() not in taken and len(candidate) <= FeedingProtocol._meta.get_field('name').max_length:
            return candidate
    raise ValidationError({NON_FIELD_ERRORS: _('Rename the protocol first: its copies have used every name.')})


def duplicate(user, protocol, snapshot):
    """A draft copy of the protocol and its table, to change and assign from a date; logged as created, with its
    fields (`snapshot`: the tab's) and its table."""
    access.require(user, ADD)
    with transaction.atomic():
        source = FeedingProtocol.objects.get(pk=protocol.pk)
        copy = FeedingProtocol(name=copy_name(source.name), status=ProtocolStatus.DRAFT, created_by=user,
                               updated_by=user, **{name: getattr(source, name) for name in COPIED})
        copy.full_clean()
        copy.save()
        for band in source.bands.prefetch_related('rates').order_by('min_weight_g'):
            rates = list(band.rates.all())
            band.pk, band.protocol = None, copy
            band.save()
            ProtocolRate.objects.bulk_create([ProtocolRate(band=band, temperature_c=rate.temperature_c,
                                                           sfr_pct=rate.sfr_pct) for rate in rates])
        with audit.source_language():
            values = {**snapshot(copy), str(TABLE): describe(copy)}
            audit.record_create(user, copy, values)
        return copy
