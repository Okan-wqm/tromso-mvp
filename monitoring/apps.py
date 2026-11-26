from django.apps import AppConfig


class MonitoringConfig(AppConfig):
    name = 'monitoring'

    def ready(self):
        from . import resources  # noqa: F401  declares the boards' tab on Resource.registry
        from .sealing import declare_all
        declare_all()       # how this app's records are sealed (core.sealing)
