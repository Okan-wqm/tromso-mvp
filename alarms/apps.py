from django.apps import AppConfig


class AlarmsConfig(AppConfig):
    """The alarms: what the water limits and the sensor rules raise, who is notified and how (the outbox, escalation and
    acknowledgements), all append-only (alarms/models.py)."""

    name = 'alarms'

    def ready(self):
        from . import resources  # noqa: F401  declares the recipient rules' tab on Resource.registry
