from django.apps import AppConfig


class FarmConfig(AppConfig):
    name = 'farm'

    def ready(self):
        from . import checks, resources  # noqa: F401  registers the system checks, declares the tabs
        from . import withdrawal_gate
        from .handling import withdrawal
        from .health.withdrawal import blockers_while_live, provider, weighed
        from .models import (
            Feed, FeedingRecord, MedicineWithdrawal, ProbeDay, ProbeDayClosing, SamplingPoint, Species, StockMovement,
            StockOperation, System, Tank, Treatment, WaterMeasurement, WithdrawalFloor,
        )

        # The water's staleness rules (farm/water/freshness.py) are read again after a row is saved and at every request.
        from django.core.signals import request_started
        from django.db.models.signals import post_delete, post_save

        from core.models import PlatformSettings

        from .models import WaterFreshness
        from .water import freshness
        for model in (WaterFreshness, PlatformSettings):
            post_save.connect(freshness.forget, sender=model, dispatch_uid=f'freshness-{model.__name__}-save')
            post_delete.connect(freshness.forget, sender=model, dispatch_uid=f'freshness-{model.__name__}-delete')
        request_started.connect(freshness.forget, dispatch_uid='freshness-request')

        # The medicine withdrawal the handling check reads (farm/handling/withdrawal.py) is the health records'.
        withdrawal.register(provider)
        # What a withdrawal is worked out from: changed only inside the withdrawal guard (farm/withdrawal_gate.py), a
        # treatment's units through their link table too. Conditional, each weighed as the row stands: a unit's loop
        # (whose samples count for a unit without its own) counts when moving it changes a withdrawal of the fish ever
        # in the unit (worked out as the guard works it, rolled back); a system, a unit, a species or a sampling point
        # deleted or restored counts while its withdrawal_blockers(), as they stand with it live, say why (fish it
        # reaches held by a withdrawal; samples on the point).
        deleted = {'is_deleted': lambda stored, new: ' '.join(blockers_while_live(stored))}
        loop = {'system': lambda stored, new: ' '.join(weighed(stored, {'system_id': new.system_id}, [stored.pk]))}
        withdrawal_gate.install({
            Treatment: None, Treatment.units.through: None, FeedingRecord: None, WaterMeasurement: None,
            MedicineWithdrawal: None, StockOperation: None, StockMovement: None, Feed: ('feed_type',),
            Species: ('withdrawal_temperature_c',), SamplingPoint: ('is_active', 'kind', 'unit', 'system', 'equipment'),
            # the degree-days' facts and rules: a temperature probe's closed days and the days closed, the floors that
            # keep an end from moving earlier unasked, and the settings a probe day and the cap are worked out with
            ProbeDay: None, ProbeDayClosing: None, WithdrawalFloor: None,
            PlatformSettings: ('unknown_withdrawal_days', 'sensor_day_hours', 'sensor_hold_seconds',
                               'assumption_cap_days'),
        }, conditional={System: deleted, Tank: {**deleted, **loop}, Species: deleted, SamplingPoint: deleted})
