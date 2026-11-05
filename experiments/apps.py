from django.apps import AppConfig


class ExperimentsConfig(AppConfig):
    name = 'experiments'

    def ready(self):
        from farm import placements

        from . import read, resources  # noqa: F401  resources declares the tab on Resource.registry

        # The chip beside a tank booked to an experiment on Production units, the meal board and the drawer (it fails open).
        placements.register(read.chips)
