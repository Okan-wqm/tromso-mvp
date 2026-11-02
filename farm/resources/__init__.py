"""The farm tabs, each declared once on top of core.crud; importing this package declares them all."""
from .equipment import EquipmentResource
from .production_department import ProductionDepartmentResource
from .site import SiteResource
from .species import SpeciesResource
from .system import SystemResource
from .tank import TankResource

__all__ = ['EquipmentResource', 'ProductionDepartmentResource', 'SiteResource', 'SpeciesResource',
           'SystemResource', 'TankResource']
