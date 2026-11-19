"""The water's live sources: values that do not come from a sample, given by a provider that registers itself (the
sensors app does, from `SensorsConfig.ready()`); the farm never imports one. A provider answers for TARGETS: a sampling
point (`(POINT, pk)`) or a system (`(SYSTEM, pk)`, a measurement of the system's water as a whole). Which targets count
for a point, and in which order, is decided in one place only: farm/water/read.py (`latest` and `Series`), owner rule
A1. This module only gathers the providers' answers.

A provider is an object with three methods:

    latest(targets, now) -> {target: {code: [SensorValue]}}
        every usable channel's newest good value (stale ones too: the reader decides), primary channels first;
    value_at(targets, code, moment) -> {target: [SensorValue]}
        each channel's newest good value at or before `moment`, from the channels bound to the target at that time.
    bound(targets, code, since, until) -> {target}
        the targets with a channel of the parameter bound there at some time in the range (one cheap ask, so a series
        never asks per moment for a place nothing was bound to).

A pH value carries its channel's scale and the moment that scale holds from (SensorValue): the provider says what the
channel is set to, the farm decides what the value is on the NBS scale (farm/water/read.py, Context.sensor_ph).

A provider that raises is left out of the answer and the answer says so (`failed`): the pages then say that the live
values could not be read, and show what the samples give. Each provider runs in its own savepoint, so a database error
inside it cannot spoil the caller's transaction."""
import logging
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction

logger = logging.getLogger(__name__)

POINT, SYSTEM = 'point', 'system'
PRIMARY, BACKUP = 'primary', 'backup'
ROLE_ORDER = {PRIMARY: 0, BACKUP: 1}

_providers = []


@dataclass(frozen=True)
class SensorValue:
    """One channel's value of one water parameter: the value in the parameter's unit, when it was measured, how long it
    counts as fresh (seconds), the channel's role at its target and its number. A pH channel's value says its channel's
    scale (`ph_scale`: '' for NBS, else a farm.models.water.PhScale code) and since when that scale holds
    (`ph_scale_from`: None, since the channel was made): farm/water/read.py puts it on the NBS scale, never here."""
    code: str
    value: float
    at: datetime
    fresh_for: int
    role: str
    channel_no: int
    ph_scale: str = ''
    ph_scale_from: datetime | None = None


@dataclass(frozen=True)
class Answer:
    """What the providers said: {target: {code: [SensorValue]}} (latest) or {target: [SensorValue]} (value_at), and
    whether one of them failed."""
    values: dict
    failed: bool = False


def register(provider):
    if provider not in _providers:
        _providers.append(provider)


def unregister(provider):
    if provider in _providers:
        _providers.remove(provider)


def _ask(method, *args):
    merged, failed = {}, False
    for provider in list(_providers):
        try:
            with transaction.atomic():
                found = getattr(provider, method)(*args)
        except Exception:                                        # fail open, and say so
            logger.exception('A water source (%r) failed; its values are left out.', provider)
            failed = True
            continue
        for target, values in found.items():
            if isinstance(values, dict):
                slot = merged.setdefault(target, {})
                for code, items in values.items():
                    slot.setdefault(code, []).extend(items)
            else:
                merged.setdefault(target, []).extend(values)
    return Answer(merged, failed)


def latest(targets, now):
    """The providers' newest values for the targets."""
    targets = list(dict.fromkeys(targets))
    if not targets or not _providers:
        return Answer({})
    return _ask('latest', targets, now)


def value_at(targets, code, moment):
    """The providers' values of one parameter at a moment, for the targets."""
    targets = list(dict.fromkeys(targets))
    if not targets or not _providers:
        return Answer({})
    return _ask('value_at', targets, code, moment)


def ordered(values):
    """Primary channels first, then backups; among one role the newest first."""
    return sorted(values, key=lambda value: (ROLE_ORDER.get(value.role, 2), -value.at.timestamp()))


def bound(targets, code, since, until):
    """The targets that have a channel of `code` bound there at some time between since and until, in one ask; a failing
    provider counts every target as bound (so the values are asked for, and the failure said)."""
    targets = list(dict.fromkeys(targets))
    if not targets or not _providers:
        return set()
    found = set()
    for provider in list(_providers):
        try:
            with transaction.atomic():
                found |= set(provider.bound(targets, code, since, until))
        except Exception:                                        # fail open, and say so through value_at
            logger.exception('A water source (%r) failed; its places are asked one by one.', provider)
            return set(targets)
    return found
