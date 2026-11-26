"""How a notification leaves the platform: one transport per channel, named in settings.ALARM_TRANSPORTS ({channel: dotted
path of a Transport class}). None is connected today (the mobile app that receives the push comes later): the setting is
empty, the outbox waits, and the pages say that nothing is sent. A transport plugs in by being named there; nothing else
changes. The tests use a double (alarms/tests/doubles.py) that records what it would send."""
import logging
from dataclasses import dataclass

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Sent:
    detail: str = ''


@dataclass(frozen=True)
class Failed:
    detail: str = ''


@dataclass(frozen=True)
class Flood:
    """A message for several notifications (alarms/floods.py): `size` alarms of one kind for the person, the oldest
    opened at `since`, one of them `example` (an alarm's summary); `cleared`: all of them have cleared, the last at
    `last_cleared`. The notification handed with it is the first of them, its `text` the message's (alarms/outbox.py
    text)."""
    size: int
    since: object
    example: str
    cleared: bool = False
    last_cleared: object = None
    # the summary of critical alarms that cleared long before they could be sent (alarms/outbox.py SUMMARY_AFTER)
    summary: bool = False
    # a follow-up message of criticals: each one's (summary, cleared at or None), and how many of them are open
    listed: tuple = ()
    open: int = 0


class Transport:
    """Takes one notification (its alarm, recipient, channel and level) to the person; returns Sent or Failed with a
    short detail, never raises for a delivery that did not happen. The outbox (alarms/outbox.py) calls it on a thread of
    its own with a time limit, outside any transaction: it must not use the database. A notification can come twice (a
    sender that died after the transport took it and before its attempt was written sends it again): its id
    (`notification.pk`) is the key the push service collapses on, so the person sees it once. `notification.text` is what
    the person is told, in their language (alarms/outbox.py text), never longer than `max_bytes`.

    `max_bytes`: the longest text its service takes, in UTF-8 bytes (a push payload's limit is in bytes and covers the
    envelope too, so a real push transport declares well under its 4,096, about 3,000; an SMS 160), declared by each
    transport as a whole number of at least 1; the outbox builds every text to it (F-A: a longer one would be refused
    for ever). `manage.py check --deploy` refuses a configured transport without one (alarms/checks.py); one that
    reaches a round all the same sends nothing: each attempt fails, said why."""

    channel = ''
    max_bytes = None

    def send(self, notification, flood=None):
        """`flood`: send one message for the whole flood instead of the notification's own (alarms/floods.py)."""
        raise NotImplementedError


_imported = set()          # the paths that have imported (an import that worked is kept by Python itself)
_said = set()              # what was logged already: a fault of the configuration is said once, not every pass


def _say(key, message, *values, error=False):
    """Logs a fault of the transports' configuration once per process and fault (`key`)."""
    if key not in _said:
        _said.add(key)
        (logger.exception if error else logger.error)(message, *values)


def _importable(path):
    """Whether the transport class at `path` imports. One that did is remembered; one that did not is tried again the
    next time it is asked (the next pass: a package installed, a file restored), its error logged once per error, never
    raised (landing review 5, N8)."""
    if path in _imported:
        return True
    try:
        import_string(path)
    except Exception as error:                                # a mistyped path, a missing package
        _say(('import', path, f'{type(error).__name__}: {error}'),
             'The alarm transport %s cannot be imported: its channel counts as not connected.', path, error=True)
        return False
    _imported.add(path)
    return True


def configured():
    """{channel: dotted path} of settings.ALARM_TRANSPORTS, for the channels there are (alarms.models.Channel). A
    setting that is not a dictionary names no transport, and a key that is no channel (a typing mistake: 'Push', a
    channel not built yet) or a path that is not text is left out: each said once in the log, and refused by name by
    `manage.py check --deploy` (alarms/checks.py). Reading it never fails."""
    from .models import Channel
    setting = getattr(settings, 'ALARM_TRANSPORTS', None) or {}
    if not isinstance(setting, dict):
        _say(('shape', type(setting).__name__), 'settings.ALARM_TRANSPORTS is a %s, not a {channel: path} dictionary: '
             'no channel counts as connected.', type(setting).__name__)
        return {}
    unknown = sorted(repr(key) for key in setting if key not in Channel.values)
    if unknown:
        _say(('unknown', *unknown), 'settings.ALARM_TRANSPORTS names %s, not a notification channel (%s): left out.',
             ', '.join(unknown), ', '.join(Channel.values))
    found = {}
    for channel in Channel.values:
        path = setting.get(channel)
        if path and not isinstance(path, str):
            _say(('path', channel, repr(path)), 'settings.ALARM_TRANSPORTS[%r] is not a dotted path: the channel '
                 'counts as not connected.', channel)
        elif path:
            found[channel] = path
    return found


def connected_channels():
    """THE channels a notification can leave on now (landing review 4, R4, L8): those settings.ALARM_TRANSPORTS names a
    transport for (`configured`) that imports. Never builds a transport to answer (a constructor may open a
    connection); a setting of the wrong shape, a key that is no channel and a path that does not import are channels
    not connected, logged: asking never fails, so it cannot roll back a pass's notify or supervision. The routing, the
    safety net, the sender and the pages all ask here."""
    return [channel for channel, path in configured().items() if _importable(path)]


def transport_for(channel):
    """The transport of `channel`, or None when none is connected."""
    path = configured().get(channel)
    return import_string(path)() if path else None
