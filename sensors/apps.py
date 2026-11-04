from django.apps import AppConfig


class SensorsConfig(AppConfig):
    name = 'sensors'

    def ready(self):
        from farm.water import sources

        from . import resources  # noqa: F401  declares the configuration tabs on Resource.registry
        from .provider import PROVIDER
        # The bound water channels join the water read (farm/water/read.py); the farm never imports this app.
        sources.register(PROVIDER)
