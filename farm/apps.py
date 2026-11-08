from django.apps import AppConfig


class FarmConfig(AppConfig):
    name = 'farm'

    def ready(self):
        from . import resources  # noqa: F401  declares the tabs on Resource.registry
        from . import withdrawal_gate
        from .handling import withdrawal
        from .health.withdrawal import provider
        from .models import (
            Feed, FeedingRecord, MedicineWithdrawal, SamplingPoint, Species, StockMovement, StockOperation, Treatment,
            WaterMeasurement,
        )

        # The medicine withdrawal the handling check reads (farm/handling/withdrawal.py) is the health records'.
        withdrawal.register(provider)
        # What a withdrawal is worked out from: changed only inside the withdrawal guard (farm/withdrawal_gate.py).
        withdrawal_gate.install({
            Treatment: None, FeedingRecord: None, WaterMeasurement: None, MedicineWithdrawal: None,
            StockOperation: None, StockMovement: None, Feed: ('feed_type',), Species: ('withdrawal_temperature_c',),
            SamplingPoint: ('is_active', 'kind', 'unit', 'system', 'equipment'),
        })
