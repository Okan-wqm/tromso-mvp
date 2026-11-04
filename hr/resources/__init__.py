"""The HR tabs, each declared once on top of core.crud; importing this package declares them all."""
from .department import OfficeDepartmentResource
from .employee import EmployeeResource

__all__ = ['EmployeeResource', 'OfficeDepartmentResource']
