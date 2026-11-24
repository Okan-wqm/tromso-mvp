from django.apps import AppConfig


class AlarmsConfig(AppConfig):
    """The alarms: what the water limits and the sensor rules raise, who is notified and how (the outbox, escalation and
    acknowledgements), all append-only (alarms/models.py)."""

    name = 'alarms'

    def ready(self):
        from . import checks, resources  # noqa: F401  registers the deployment check; declares the rules' tab
