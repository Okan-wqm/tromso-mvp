from django.apps import AppConfig


class MonitoringConfig(AppConfig):
    name = 'monitoring'

    def ready(self):
        from . import resources  # noqa: F401  declares the boards' tab on Resource.registry
