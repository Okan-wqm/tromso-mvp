"""The medicine-withdrawal registry: who knows when fish may go to food again.

The health records (treatments and medicines) register a provider in their app's `ready()`:

    from farm.handling import withdrawal
    withdrawal.register(provider)      # provider(unit, day) -> iterable of WithdrawalBlock

A provider returns the withdrawals of the fish in `unit` on `day`: one block per batch and cause, following
the batch wherever it was treated. `until` is the first day the fish may be harvested, None when it cannot be
worked out ("unknown", which counts as a warning, never as clear); `approximate` when it is projected (degree
days still accruing). A block whose `until` is on or before the day is clear.

`blocks(unit, day)` asks every provider. With none registered it returns None, not an empty list: the check
then says "Medicine withdrawal not checked" instead of reading it as clear."""
from dataclasses import dataclass
from datetime import date

_providers = []


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


def blocks(unit, day):
    """Every provider's blocks for the fish in `unit` on `day`; None when no provider is registered."""
    if not _providers:
        return None
    return [block for provider in _providers for block in provider(unit, day)]
