"""The farm tabs, each declared once on top of core.crud; importing this package declares them all."""
from .department import DepartmentResource
from .site import SiteResource
from .system import SystemResource

__all__ = ['DepartmentResource', 'SiteResource', 'SystemResource']
