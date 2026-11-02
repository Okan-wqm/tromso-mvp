"""The farm tabs, each declared once on top of core.crud; importing this package declares them all."""
from .production_department import ProductionDepartmentResource
from .site import SiteResource
from .system import SystemResource

__all__ = ['ProductionDepartmentResource', 'SiteResource', 'SystemResource']
