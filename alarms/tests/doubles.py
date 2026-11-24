"""Test doubles of the push transport (alarms/transports.py): what a connected transport would do, without sending
anything anywhere. Named in settings.ALARM_TRANSPORTS by the tests that need one. Each declares its payload limit
(`max_chars`) as a real one does, and the recording ones refuse a text longer than it, as a push service or an SMS
gateway does."""
from ..transports import Failed, Sent, Transport


class RecordingTransport(Transport):
    """Accepts every notification within its limit (a push payload: about 4,000 characters) and keeps it, as if the
    push service had taken it; a flood message is kept in `floods` too, (its first notification, the flood). A text
    over the limit is refused, as the push service refuses it."""

    channel = 'push'
    max_chars = 4000
    sent = []
    floods = []

    def send(self, notification, flood=None):
        if len(getattr(notification, 'text', '')) > self.max_chars:
            return Failed(f'refused: {len(notification.text)} characters, over {self.max_chars}')
        type(self).sent.append(notification)
        if flood is not None:
            type(self).floods.append((notification, flood))
        return Sent(f'recorded {notification.pk}')


class SmsTransport(RecordingTransport):
    """An SMS gateway: 160 characters a message, the rest as the recording transport."""

    max_chars = 160


class FailingTransport(Transport):
    """Refuses every notification, as a push service that is down."""

    channel = 'push'
    max_chars = 4000
    reason = 'the push service did not answer'

    def send(self, notification, flood=None):
        return Failed(self.reason)
