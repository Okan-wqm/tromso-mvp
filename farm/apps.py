from django.apps import AppConfig


class FarmConfig(AppConfig):
    name = 'farm'

    def ready(self):
        from . import resources  # noqa: F401  declares the tabs on Resource.registry
        from . import withdrawal_gate
        from .handling import withdrawal
        from .health.withdrawal import blockers_while_live, provider
        from .models import (
            Feed, FeedingRecord, MedicineWithdrawal, SamplingPoint, Species, StockMovement, StockOperation, System, Tank,
            Treatment, WaterMeasurement,
        )

        # The medicine withdrawal the handling check reads (farm/handling/withdrawal.py) is the health records'.
        withdrawal.register(provider)
        # What a withdrawal is worked out from: changed only inside the withdrawal guard (farm/withdrawal_gate.py). A
        # treatment's units through their link table; a unit's loop (whose samples count for it without its own).
        # A system, a unit, a species or a sampling point deleted or restored counts while its withdrawal_blockers(), as
        # they stand with it live, say why (fish it reaches held by a withdrawal; samples on the point).
        deleted = {'is_deleted': lambda record: ' '.join(blockers_while_live(record))}
        withdrawal_gate.install({
            Treatment: None, Treatment.units.through: None, FeedingRecord: None, WaterMeasurement: None,
            MedicineWithdrawal: None, StockOperation: None, StockMovement: None, Feed: ('feed_type',),
            Species: ('withdrawal_temperature_c',), Tank: ('system',),
            SamplingPoint: ('is_active', 'kind', 'unit', 'system', 'equipment'),
        }, conditional={System: deleted, Tank: deleted, Species: deleted, SamplingPoint: deleted})
