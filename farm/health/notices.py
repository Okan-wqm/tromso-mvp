"""Who has told Mattilsynet of a listed disease, and when (dyrehelseforskriften § 7: at once, on suspicion).

The fact is not a column of the health event: it is the filing of a disease notice, which the regulatory reports keep with
its frozen content, its channel and its receipt (Production › Reports). The health records read it through this registry,
as the handling check reads the medicine withdrawal (farm/handling/withdrawal.py), and the farm never imports the
reports. An app that keeps notices registers a provider in its `ready()`:

    from farm.health import notices
    notices.register(provider)

A provider has two methods: `told(events)` gives {event id: Notified} for the events of which Mattilsynet has been
told (a notice filed for it), and `start_url(event, user)` the address a person who may start a notice for the event
opens ('' for one who may not). With no provider registered `told` is None: "not checked", which the pages never
read as "not notified"."""
from dataclasses import dataclass
from datetime import datetime

from django.utils.translation import gettext_noop

_providers = []


@dataclass(frozen=True)
class Notified:
    at: datetime            # when it was told: the time the notice was filed
    reference: str = ''     # the receipt or case number the authority gave


def register(provider):
    """Adds a provider (called once, from an app's ready())."""
    if provider not in _providers:
        _providers.append(provider)


def told(events):
    """{event id: Notified} of these events Mattilsynet has been told of; None when no provider is registered. The
    earliest telling counts when several providers know one."""
    if not _providers:
        return None
    found = {}
    for provider in _providers:
        for event_id, notified in provider.told(events).items():
            if event_id not in found or notified.at < found[event_id].at:
                found[event_id] = notified
    return found


def pending(events):
    """The live events with a listed diagnosis Mattilsynet has not been told of, in the order given; None when not
    checked."""
    notified = told(events)
    if notified is None:
        return None
    return [event for event in events if event.notifiable and not event.is_deleted and event.pk not in notified]


def start_url(event, user):
    """Where a person who may start the notice for the event goes; '' for one who may not, or with no provider."""
    for provider in _providers:
        url = provider.start_url(event, user)
        if url:
            return url
    return ''


# The label the activity log's old rows carry for the column this registry replaced (the health event's "Mattilsynet notified
# at"): kept in the catalogs so those rows stay translated.
LEGACY_LABELS = (gettext_noop('Mattilsynet notified at'),)
