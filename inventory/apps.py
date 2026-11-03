from django.apps import AppConfig


class InventoryConfig(AppConfig):
    """The store (Operations › Storage, Company › Facility › Storage locations): its own app, with its own
    tables and migrations, on top of the farm's records (sites, feeds, suppliers, the feeding records)."""

    name = 'inventory'
    verbose_name = 'Storage'

    def ready(self):
        from . import resources  # noqa: F401  declares the tab on Resource.registry
