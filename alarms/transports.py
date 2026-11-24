"""How a notification leaves the platform: one transport per channel, named in settings.ALARM_TRANSPORTS ({channel: dotted
path of a Transport class}). None is connected today (the mobile app that receives the push comes later): the setting is
empty, the outbox waits, and the pages say that nothing is sent. A transport plugs in by being named there; nothing else
changes. The tests use a double (alarms/tests/doubles.py) that records what it would send."""
from dataclasses import dataclass

from django.conf import settings
from django.utils.module_loading import import_string


@dataclass(frozen=True)
class Sent:
    detail: str = ''


@dataclass(frozen=True)
class Failed:
    detail: str = ''


@dataclass(frozen=True)
class Flood:
    """A flood message (alarms/floods.py): `size` alarms of one kind for the person, the oldest opened at `since`, one
    of them `example` (an alarm's summary); `cleared`: all of them have cleared, the last at `last_cleared`. The
    notification handed with it is the first of them, its `text` the flood's (alarms/outbox.py text)."""
    size: int
    since: object
    example: str
    cleared: bool = False
    last_cleared: object = None


class Transport:
    """Takes one notification (its alarm, recipient, channel and level) to the person; returns Sent or Failed with a
    short detail, never raises for a delivery that did not happen. The outbox (alarms/outbox.py) calls it on a thread of
    its own with a time limit, outside any transaction: it must not use the database. A notification can come twice (a
    sender that died after the transport took it and before its attempt was written sends it again): its id
    (`notification.pk`) is the key the push service collapses on, so the person sees it once. `notification.text` is what
    the person is told, in their language (alarms/outbox.py text)."""

    channel = ''

    def send(self, notification, flood=None):
        """`flood`: send one message for the whole flood instead of the notification's own (alarms/floods.py)."""
        raise NotImplementedError


def transport_for(channel):
    """The transport of `channel`, or None when none is connected."""
    path = getattr(settings, 'ALARM_TRANSPORTS', {}).get(channel)
    return import_string(path)() if path else None
