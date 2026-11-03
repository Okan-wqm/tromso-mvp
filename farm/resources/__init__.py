"""The farm tabs, each declared once on top of core.crud; importing this package declares them all."""
from .equipment import EquipmentResource
from .feed import FeedResource
from .handling_rule import HandlingRuleResource
from .harvest_plan import HandlingPlanItemResource, ProductionPlanResource
from .production_department import ProductionDepartmentResource
from .site import SiteResource
from .slaughter_facility import SlaughterFacilityResource
from .species import SpeciesResource
from .supplier import SupplierResource
from .system import SystemResource
from .tank import TankResource
from .water_limit import WaterLimitResource

__all__ = ['EquipmentResource', 'FeedResource', 'HandlingPlanItemResource', 'HandlingRuleResource',
           'ProductionDepartmentResource', 'ProductionPlanResource', 'SiteResource', 'SlaughterFacilityResource',
           'SpeciesResource', 'SupplierResource', 'SystemResource', 'TankResource', 'WaterLimitResource']
