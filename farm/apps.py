from django.apps import AppConfig


class FarmConfig(AppConfig):
    name = 'farm'

    def ready(self):
        from . import resources  # noqa: F401  declares the tabs on Resource.registry
        from .handling import withdrawal
        from .health.withdrawal import provider

        # The medicine withdrawal the handling check reads (farm/handling/withdrawal.py) is the health records'.
        withdrawal.register(provider)
