"""Test doubles of the push transport (alarms/transports.py): what a connected transport would do, without sending
anything anywhere. Named in settings.ALARM_TRANSPORTS by the tests that need one. Each declares its payload limit in
UTF-8 bytes (`max_bytes`) as a real one does, and the recording ones refuse a text longer than it, as a push service or
an SMS gateway does."""
from ..transports import Failed, Sent, Transport


class RecordingTransport(Transport):
    """Accepts every notification within its limit (a push payload: about 4,000 bytes) and keeps it, as if the push
    service had taken it; a flood message is kept in `floods` too, (its first notification, the flood). A text over the
    limit is refused, as the push service refuses it."""

    channel = 'push'
    max_bytes = 4000
    max_chars = max_bytes            # the interface before the fix (REVIEW4 addendum); goes with it
    sent = []
    floods = []

    def send(self, notification, flood=None):
        size = len(getattr(notification, 'text', '').encode('utf-8'))
        if size > self.max_bytes:
            return Failed(f'refused: {size} bytes, over {self.max_bytes}')
        type(self).sent.append(notification)
        if flood is not None:
            type(self).floods.append((notification, flood))
        return Sent(f'recorded {notification.pk}')


class SmsTransport(RecordingTransport):
    """An SMS gateway: 160 bytes a message, the rest as the recording transport."""

    max_bytes = 160
    max_chars = max_bytes


class UndeclaredTransport(Transport):
    """A transport that declares no limit: it must never be handed anything (its `calls` stays empty)."""

    channel = 'push'
    calls = []

    def send(self, notification, flood=None):
        type(self).calls.append(notification)
        return Sent('taken')


class NotATransport:
    """A class named in the setting that is not a Transport."""

    max_bytes = 4000


class FailingTransport(Transport):
    """Refuses every notification, as a push service that is down."""

    channel = 'push'
    max_bytes = 4000
    max_chars = max_bytes
    reason = 'the push service did not answer'

    def send(self, notification, flood=None):
        return Failed(self.reason)
