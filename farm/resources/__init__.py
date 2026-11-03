"""The farm tabs, each declared once on top of core.crud; importing this package declares them all."""
from .equipment import EquipmentResource
from .feed import FeedResource
from .feeding_protocol import FeedingProtocolResource, ProtocolAssignmentResource
from .health_event import HealthEventResource
from .medicine import MedicineResource
from .production_department import ProductionDepartmentResource
from .site import SiteResource
from .species import SpeciesResource
from .supplier import SupplierResource
from .system import SystemResource
from .tank import TankResource
from .water_limit import WaterLimitResource

__all__ = ['EquipmentResource', 'FeedResource', 'FeedingProtocolResource', 'HealthEventResource', 'MedicineResource',
           'ProductionDepartmentResource', 'ProtocolAssignmentResource', 'SiteResource', 'SpeciesResource',
           'SupplierResource', 'SystemResource', 'TankResource', 'WaterLimitResource']
