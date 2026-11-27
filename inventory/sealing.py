"""The store is exempt from the seal (core.sealing): a storage location may name a feeder (a piece of equipment, plant),
and nothing of the store lies on a unit or a system."""
from core.sealing import EXEMPT, declare

REASON = 'The store lies on no unit or system; a location only names the feeder it fills (plant).'


def declare_all():
    from . import models as m
    for model in (m.StorageLocation, m.InventoryOperation, m.InventoryLine, m.ReorderLevel):
        declare(model, mode=EXEMPT, reason=REASON)
