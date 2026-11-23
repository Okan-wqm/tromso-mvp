"""Test doubles of the push transport (alarms/transports.py): what a connected transport would do, without sending
anything anywhere. Named in settings.ALARM_TRANSPORTS by the tests that need one."""
from ..transports import Failed, Sent, Transport


class RecordingTransport(Transport):
    """Accepts every notification and keeps it, as if the push service had taken it; a flood message is kept in
    `floods` too, (its first notification, the flood)."""

    channel = 'push'
    sent = []
    floods = []

    def send(self, notification, flood=None):
        type(self).sent.append(notification)
        if flood is not None:
            type(self).floods.append((notification, flood))
        return Sent(f'recorded {notification.pk}')


class FailingTransport(Transport):
    """Refuses every notification, as a push service that is down."""

    channel = 'push'
    reason = 'the push service did not answer'

    def send(self, notification, flood=None):
        return Failed(self.reason)
