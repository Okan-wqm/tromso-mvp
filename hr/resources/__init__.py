"""The HR tabs, each declared once on top of core.crud; importing this package declares them all."""
from .department import OfficeDepartmentResource
from .employee import EmployeeResource
from .scheduling import HolidayResource, SchedulingSettingsResource, ShiftResource

__all__ = ['EmployeeResource', 'HolidayResource', 'OfficeDepartmentResource', 'SchedulingSettingsResource',
           'ShiftResource']
