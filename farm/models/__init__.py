"""Farm module models, ported tab by tab from aquaculture_platform's farm-service.

Differences from the source schema (apply to every model here):
- Single tenant: no tenantId column and no row-level security.
- Satellite monitoring (monitoringRadiusM, monitoringArea, monitoringLocationRevision) is not ported.
- jsonb location/address are flat columns; the source also duplicated city and country.
- Uniqueness rules the source only enforced in service code are database constraints here.
"""
from .equipment import Equipment, EquipmentSystem, EquipmentType, FeederCalibration
from .feed import Feed, FeedSuitability
from .feeding import FeedingRecord
from .feeding_protocol import FeedingProtocol, ProtocolAssignment, ProtocolBand, ProtocolRate
from .handling import HandlingAcknowledgement, HandlingRule, WithdrawalAcknowledgement
from .harvest import HandlingPlanItem, HarvestRecord, ProductionPlan, SlaughterFacility
from .health import HealthEvent, LiceCount, Medicine, MedicineWithdrawal, Treatment
from .production_department import ProductionDepartment
from .site import Site, SiteContact
from .species import Species
from .stock import Batch, DeliveryRecord, EscapeRecord, StockMovement, StockOperation
from .supplier import Supplier, SupplierContact
from .system import System
from .tank import Tank
from .water import WaterLimit, WaterMeasurement
from .water_point import SamplingPoint

__all__ = [
    'Batch', 'DeliveryRecord', 'EscapeRecord', 'Equipment', 'EquipmentSystem', 'EquipmentType', 'Feed', 'FeedSuitability', 'FeederCalibration',
    'FeedingProtocol', 'FeedingRecord', 'HandlingAcknowledgement', 'HandlingPlanItem', 'HandlingRule', 'HarvestRecord',
    'HealthEvent', 'LiceCount', 'Medicine', 'MedicineWithdrawal', 'ProductionDepartment', 'ProductionPlan', 'ProtocolAssignment',
    'ProtocolBand', 'ProtocolRate', 'SamplingPoint', 'Site', 'SiteContact', 'SlaughterFacility', 'Species', 'StockMovement',
    'StockOperation', 'Supplier', 'SupplierContact', 'System', 'Tank', 'Treatment', 'WaterLimit',
    'WaterMeasurement', 'WithdrawalAcknowledgement',
]
