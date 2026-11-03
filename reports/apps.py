from django.apps import AppConfig


class ReportsConfig(AppConfig):
    """Regulatory reports (Production › Reports): its own app, with its own tables and migrations, reading the farm's
    records (the stock ledger, the feeding records, the harvest plan, the health records); the farm never reads it."""

    name = 'reports'
    verbose_name = 'Reports'

    def ready(self):
        from . import resources  # noqa: F401  declares the tab on Resource.registry
