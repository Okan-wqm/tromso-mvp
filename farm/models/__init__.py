"""Farm module models, ported tab by tab from aquaculture_platform's farm-service.

Differences from the source schema (apply to every model here):
- Single tenant: no tenantId column and no row-level security.
- Satellite monitoring (monitoringRadiusM, monitoringArea, monitoringLocationRevision) is not ported.
- jsonb location/address are flat columns; the source also duplicated city and country.
- Uniqueness rules the source only enforced in service code are database constraints here.
"""
from .equipment import Equipment, EquipmentSystem, EquipmentType, FeederCalibration
from .feed import Feed, FeedSuitability
from .production_department import ProductionDepartment
from .site import Site, SiteContact
from .species import Species
from .stock import Batch, StockMovement, StockOperation
from .supplier import Supplier, SupplierContact
from .system import System
from .tank import Tank

__all__ = [
    'Batch', 'Equipment', 'EquipmentSystem', 'EquipmentType', 'Feed', 'FeedSuitability', 'FeederCalibration',
    'ProductionDepartment', 'Site', 'SiteContact', 'Species', 'StockMovement', 'StockOperation', 'Supplier',
    'SupplierContact', 'System', 'Tank',
]
