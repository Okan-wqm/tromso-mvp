"""The boundary of HR: no pay, bank, tax or identity number anywhere in it, and no payroll in it. A later payroll app owns
what concerns money and points at `hr.Employee`; it is never offered to a team role."""
import re
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.db import models
from django.test import SimpleTestCase

from core.crud import Resource, tab_fields

# What would be money or identity. Whole words of a column or a field name (snake_case parts), case-insensitive.
FORBIDDEN = re.compile(r'(^|_)(salary|salaries|wage|wages|pay|payroll|payslip|rate|bank|iban|swift|account_number|'
                       r'national|nin|ssn|fnr|tax|compensation|bonus|currency|amount|price|cost|birth|birthday|dob|'
                       r'address|phone|email|mobile)(_|$)', re.I)
MONEY_FIELDS = (models.DecimalField, models.FloatField)


def hr_models():
    return list(apps.get_app_config('hr').get_models())


class NoPayTests(SimpleTestCase):
    def test_no_hr_column_is_money_or_identity(self):
        for model in hr_models():
            for field in model._meta.get_fields():
                name = getattr(field, 'name', '')
                self.assertIsNone(FORBIDDEN.search(name), f'{model.__name__}.{name}')
                if isinstance(field, MONEY_FIELDS):
                    # a decimal is allowed for days (leave days a year), never for an amount
                    self.assertIn(name, {'annual_days'}, f'{model.__name__}.{name} is a number that could be money')

    def test_no_hr_form_names_such_a_field(self):
        import importlib
        importlib.import_module(settings.ROOT_URLCONF)
        for resource in Resource.registry:
            if resource.model._meta.app_label != 'hr':
                continue
            for name in tab_fields(resource.form_class.tabs):
                self.assertIsNone(FORBIDDEN.search(name), f'{resource.__name__}: {name}')
            for name in resource.form_class.base_fields:
                self.assertIsNone(FORBIDDEN.search(name), f'{resource.__name__}: {name}')

    def test_no_hr_template_or_source_speaks_of_pay(self):
        root = Path(settings.BASE_DIR)
        words = re.compile(r'\b(salary|salaries|wages?|payroll|payslip|iban|bank account|national id|tax)\b', re.I)
        allowed_files = {'test_boundary.py'}
        for folder in ('hr', 'templates/hr'):
            for path in (root / folder).rglob('*'):
                if not path.is_file() or path.suffix not in {'.py', '.html', '.css'} or path.name in allowed_files:
                    continue
                if 'migrations' in path.parts or '__pycache__' in path.parts:
                    continue
                text = path.read_text(encoding='utf-8')
                found = words.search(text)
                # the docstrings that say there is none are the one place the word may appear
                if found:
                    line = text[:found.start()].count('\n')
                    context = text.splitlines()[line].lower()
                    self.assertTrue(any(mark in context for mark in ('no ', 'never', 'not ', 'nor ', 'without', 'later')),
                                    f'{path.relative_to(root)}:{line + 1}: {context.strip()}')

    def test_hr_imports_nothing_of_payroll(self):
        root = Path(settings.BASE_DIR) / 'hr'
        for path in root.rglob('*.py'):
            if 'tests' in path.parts or 'migrations' in path.parts:
                continue
            text = path.read_text(encoding='utf-8')
            self.assertIsNone(re.search(r'^\s*(from|import)\s+payroll', text, re.M), str(path))

    def test_every_text_column_is_either_masked_or_a_name_or_a_listed_label(self):
        """A free-text column of an hr table holds a person's words or a name: it is on the list below, and a person's
        words are masked in the database viewer (config/database.py)."""
        from config.database import VIEWER
        masked = {table: set(columns) for table, columns in VIEWER.masked.items()}
        listed = {  # model -> {column: what it is}
            'Employee': {'employee_number': 'number', 'first_name': 'name', 'last_name': 'name'},
            'OfficeDepartment': {'name': 'name', 'code': 'code', 'description': 'text about the department'},
            'Posting': {'title': 'job title'},
            'Shift': {'name': 'name', 'code': 'code'},
            'Holiday': {'name': 'name'},
            'LeaveType': {'name': 'name', 'code': 'code'},
            'LeaveRequest': {'reason': 'words', 'decision_note': 'words'},
            'AttendanceRecord': {'note': 'words'},
            'ShiftAssignment': {'note': 'words'},
        }
        words = {'LeaveRequest': {'reason', 'decision_note'}, 'AttendanceRecord': {'note'}, 'ShiftAssignment': {'note'}}
        for model in hr_models():
            columns = {f.name for f in model._meta.fields if isinstance(f, (models.CharField, models.TextField))
                       and not f.choices and f.name not in {'status', 'via', 'rest_rule', 'employment_type'}}
            self.assertLessEqual(columns, set(listed.get(model.__name__, {})), f'{model.__name__}: say what {columns} is')
            for column in words.get(model.__name__, ()):
                self.assertIn(column, masked.get(model._meta.db_table, set()), f'{model._meta.db_table}.{column}')
