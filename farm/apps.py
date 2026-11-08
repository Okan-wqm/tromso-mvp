from django.apps import AppConfig


class FarmConfig(AppConfig):
    name = 'farm'

    def ready(self):
        from . import checks, resources  # noqa: F401  registers the system checks, declares the tabs
        from .handling import withdrawal
        from .health.withdrawal import provider

        # The medicine withdrawal the handling check reads (farm/handling/withdrawal.py) is the health records'.
        withdrawal.register(provider)
