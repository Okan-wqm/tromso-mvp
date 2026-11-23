"""Test doubles of the push transport (alarms/transports.py): what a connected transport would do, without sending
anything anywhere. Named in settings.ALARM_TRANSPORTS by the tests that need one."""
from ..transports import Failed, Sent, Transport


class RecordingTransport(Transport):
    """Accepts every notification and keeps it, as if the push service had taken it."""

    channel = 'push'
    sent = []

    def send(self, notification):
        type(self).sent.append(notification)
        return Sent(f'recorded {notification.pk}')


class FailingTransport(Transport):
    """Refuses every notification, as a push service that is down."""

    channel = 'push'
    reason = 'the push service did not answer'

    def send(self, notification):
        return Failed(self.reason)
