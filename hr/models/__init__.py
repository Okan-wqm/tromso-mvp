"""The HR area: the people of the company, where they work and, from here on, their time.

Differences from the source platform (docs/aquaculture-platform-bugs.md, "Human resources"):
- No pay, bank or identity number anywhere in `hr`: a later payroll app owns them and only points at `Employee`
  (hr/tests/test_boundary.py fails on such a column).
- A production department is an HR department by itself: it is the farm's own row (`farm.ProductionDepartment`),
  never copied; the office departments (white collar, Finance later) are the only departments HR owns.
- What can be read is never stored: who is present, late, absent or on leave, worked minutes, leave days, balances,
  head counts and the department of a past day.
"""
from .employee import Employee, EmploymentType
from .office_department import OfficeDepartment
from .posting import Posting
from .scheduling import Holiday, SchedulingSettings, Shift

__all__ = ['Employee', 'EmploymentType', 'Holiday', 'OfficeDepartment', 'Posting', 'SchedulingSettings', 'Shift']
