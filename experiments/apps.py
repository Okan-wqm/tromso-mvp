from django.apps import AppConfig


class ExperimentsConfig(AppConfig):
    name = 'experiments'

    def ready(self):
        from . import resources  # noqa: F401  declares the tab on Resource.registry
