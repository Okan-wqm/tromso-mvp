from django.apps import AppConfig


class FarmConfig(AppConfig):
    name = 'farm'

    def ready(self):
        from . import resources  # noqa: F401  declares the tabs on Resource.registry
