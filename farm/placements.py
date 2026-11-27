"""The placement registry: where a unit stands in work the farm does not own, said beside the unit.

An app that books units to something (the experiments book tanks to a replicate of a trial) registers a provider in its
`ready()`:

    from farm import placements
    placements.register(provider)      # provider(units, user) -> {unit id: [Placement]}

and Production units (the row and the drawer) and the meal board show each unit's chips (`of`). The farm knows nothing
of what the provider reads. It **fails open**: with no provider registered, or one that raises (its own savepoint, so a
database error stays inside it), the page shows no chip and nothing else changes: a chip is a convenience, never a
reason a page, a meal or a stocking cannot be shown."""
import logging
from dataclasses import dataclass

from django.db import transaction

logger = logging.getLogger(__name__)

_providers = []


@dataclass(frozen=True)
class Placement:
    label: str                   # the chip's text, e.g. "E-2026-001 · Control · R2"
    title: str = ''              # what it says on hover
    url: str = ''                # where the chip leads ('' for none)
    notice: str = ''             # what everyone who works the unit must read, shown in full beside the chip, never on hover


def register(provider):
    """Adds a provider (called once, from an app's ready())."""
    if provider not in _providers:
        _providers.append(provider)


def of(units, user):
    """{unit id: [Placement]} of these units for this person, every provider's, in the order they registered. A provider
    that raises is logged and left out."""
    units = list(units)
    found = {}
    if not units:
        return found
    for provider in _providers:
        try:
            with transaction.atomic():
                chips = {unit_id: list(rows) for unit_id, rows in provider(units, user).items()}
            if not all(isinstance(chip, Placement) for rows in chips.values() for chip in rows):
                raise TypeError('a placement provider answers {unit id: [Placement]}')
        except Exception:                                      # fail open: no chip is worth a broken page
            logger.exception('The placement provider %s failed; its chips are left out.', provider)
            continue
        for unit_id, rows in chips.items():
            found.setdefault(unit_id, []).extend(rows)
    return found
