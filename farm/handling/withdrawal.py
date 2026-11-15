"""The medicine-withdrawal registry: who knows when fish may go to food again.

The health records (treatments and medicines) register a provider in their app's `ready()`:

    from farm.handling import withdrawal
    withdrawal.register(provider)      # provider(units, day) -> {unit id: [WithdrawalBlock]}

A provider returns the withdrawals of the fish in `units` on `day` (None: each unit's own today), the units that
have none left out: one block per batch and cause, following the batch wherever it was treated. It answers for
all the units at once, so a page of fifty units costs what a page of one does. `until` is the first day the fish may be harvested, None when it cannot be
worked out ("unknown", which counts as a warning, never as clear); `approximate` when it is projected (degree
days still accruing). A block whose `until` is on or before the day is clear.

`blocks_of(units, day=None)` asks every provider; `blocks(unit, day)` is its case of one unit. With none registered
they return None, not an empty list: the check then says "Medicine withdrawal not checked" instead of reading it
as clear."""
from dataclasses import dataclass
from datetime import date, timedelta

from django.utils import formats
from django.utils.translation import gettext as _

_providers = []


def harvest_from(until, approximate=False, shown=None):
    """THE words for a withdrawal's end, on every page, message and log line that says it (flow fault M-01): the first
    day the fish may be harvested. "harvest from 25.11.2026"; "harvest from about 25.11.2026" when it is projected;
    "end unknown" when it cannot be worked out. Never "until <date>": `until` is the first FREE day, and "until" read
    as the last HELD day on one page and as the first free day on five others, a day apart for one withdrawal.
    `shown`: how the day is written (default: the page's date format, dd.mm.yyyy; a command's output its own)."""
    if until is None:
        return _('end unknown')
    day = shown(until) if shown is not None else formats.date_format(until, 'DATE_FORMAT')
    if approximate:
        return _('harvest from about %(date)s') % {'date': day}
    return _('harvest from %(date)s') % {'date': day}


def held_until(until, approximate=False):
    """The Treatments list's words for a withdrawal's end, BOTH days (flow fault M-01 proposed both; review F-09): the
    last day the fish are held and, in the one wording (`harvest_from`), the first day they may be harvested: "until
    13.12.2026 (harvest from 14.12.2026)", "until about … (harvest from about …)", "end unknown". The last held day
    is only ever said with the first free day beside it: "until <date>" alone was read both ways."""
    harvest = harvest_from(until, approximate)
    if until is None:
        return harvest
    params = {'last': formats.date_format(until - timedelta(days=1), 'DATE_FORMAT'), 'harvest': harvest}
    if approximate:
        return _('until about %(last)s (%(harvest)s)') % params
    return _('until %(last)s (%(harvest)s)') % params


@dataclass(frozen=True)
class WithdrawalBlock:
    batch: object                # the Batch held
    until: date | None           # the first day it may be harvested; None: unknown
    approximate: bool            # projected ("about <date>")
    reason: str                  # what holds it, in the person's words (the treatment and medicine, or why unknown)
    source: object               # what the provider found it in (a treatment), for its own pages


def register(provider):
    """Adds a provider (called once, from an app's ready())."""
    if provider not in _providers:
        _providers.append(provider)


def blocks_of(units, day=None):
    """{unit id: [WithdrawalBlock]} of every unit given (an empty list for one with none), every provider's blocks
    for the fish in them on `day` (None: each unit's today); None when no provider is registered."""
    if not _providers:
        return None
    found = {unit.pk: [] for unit in units}
    for provider in _providers:
        for unit_id, blocks in provider(units, day).items():
            found[unit_id].extend(blocks)
    return found


def blocks(unit, day):
    """Every provider's blocks for the fish in `unit` on `day`; None when no provider is registered."""
    found = blocks_of([unit], day)
    return None if found is None else found[unit.pk]


SOURCE_NAMES = {'treatment': 'treatment', 'feedingrecord': 'feeding'}


def source_key(source):
    """What a withdrawal comes from, as the acknowledgements store it: "treatment:<id>" or "feeding:<id>" (a medicated
    feeding no in-feed treatment covers); '' for none. check_withdrawal matches an acknowledgement to a harvest's
    withdrawal by it."""
    if source is None:
        return ''
    name = source._meta.model_name
    return f'{SOURCE_NAMES.get(name, name)}:{source.pk}'
