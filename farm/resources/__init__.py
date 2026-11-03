"""The farm tabs, each declared once on top of core.crud; importing this package declares them all."""
from .equipment import EquipmentResource
from .feed import FeedResource
from .feeding_protocol import FeedingProtocolResource, ProtocolAssignmentResource
from .handling_rule import HandlingRuleResource
from .harvest_plan import HandlingPlanItemResource, ProductionPlanResource
from .health_event import HealthEventResource
from .medicine import MedicineResource
from .production_department import ProductionDepartmentResource
from .site import SiteResource
from .slaughter_facility import SlaughterFacilityResource
from .species import SpeciesResource
from .supplier import SupplierResource
from .system import SystemResource
from .tank import TankResource
from .water_limit import WaterLimitResource

__all__ = ['EquipmentResource', 'FeedResource', 'FeedingProtocolResource', 'HandlingPlanItemResource',
           'HandlingRuleResource', 'HealthEventResource', 'MedicineResource', 'ProductionDepartmentResource',
           'ProductionPlanResource', 'ProtocolAssignmentResource', 'SiteResource', 'SlaughterFacilityResource',
           'SpeciesResource',
           'SupplierResource', 'SystemResource', 'TankResource', 'WaterLimitResource']
