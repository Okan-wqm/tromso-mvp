from django.apps import AppConfig


class HrConfig(AppConfig):
    name = 'hr'

    def ready(self):
        from . import resources  # noqa: F401  declares the tabs on Resource.registry
