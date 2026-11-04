from django.apps import AppConfig


class SensorsConfig(AppConfig):
    name = 'sensors'

    def ready(self):
        from . import resources  # noqa: F401  declares the configuration tabs on Resource.registry
