"""One writer per kind of HR record, read from the code (the architecture audit of 26.11.2026, H-5). A kind of record is
written either by its tab (core.crud saves the form, logs it and runs its `after_save`) or by hr.services, never by both:
two writers of one record keep two copies of its rules, and a fix to one leaves the other open (attendance and a last
day each had a tested service that no page called, beside the tab every page called, with other rules).

The models hr/services.py writes are found, not listed: those it logs (`audit.entity_type_of(Model)`: every service write
is logged with its kind), those it builds (`Model(...)`) and those it writes through a manager
(`Model.objects....create()`). A tab of such a model hands every write it offers to the service
(core.crud.Resource.service_writes and its create_record, change_record and delete_record) and has no `after_save`, which
crud never calls for it. A tab whose model the services do not write keeps crud's own save.

And one Monday: the week a total, a rule or a page counts is hr.rules.monday's, written once."""
import ast
from importlib import import_module
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase

from core.crud import Resource

HR = Path(__file__).resolve().parent.parent
WRITES = {'save', 'create', 'bulk_create', 'bulk_update', 'update', 'delete', 'soft_delete', 'get_or_create',
          'update_or_create'}
HOOKS = (('add', 'create_record'), ('change', 'change_record'), ('delete', 'delete_record'))


def hr_models():
    return {model.__name__ for model in apps.get_app_config('hr').get_models()}


def service_written():
    """The names of the HR models hr/services.py writes."""
    names = hr_models()
    found = set()
    for node in ast.walk(ast.parse((HR / 'services.py').read_text(encoding='utf-8'))):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == 'entity_type_of' and node.args \
                and isinstance(node.args[0], ast.Name):
            found.add(node.args[0].id)
        elif isinstance(func, ast.Name):
            found.add(func.id)
        elif isinstance(func, ast.Attribute) and func.attr in WRITES:
            root = func.value
            while isinstance(root, (ast.Attribute, ast.Call)):
                root = root.value if isinstance(root, ast.Attribute) else root.func
            if isinstance(root, ast.Name):
                found.add(root.id)
    return found & names


def production_modules():
    for path in sorted(HR.rglob('*.py')):
        parts = path.relative_to(HR).parts
        if 'migrations' in parts or 'tests' in parts:
            continue
        yield path.relative_to(HR.parent).as_posix(), ast.parse(path.read_text(encoding='utf-8'))


class OneWriterTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import_module(settings.ROOT_URLCONF)          # declares every tab
        cls.tabs = [tab for tab in Resource.registry if tab.model._meta.app_label == 'hr']

    def test_the_scan_finds_what_the_services_write(self):
        self.assertTrue({'AttendanceRecord', 'Employee', 'LeaveRequest', 'Posting', 'ShiftAssignment'}
                        <= service_written(), service_written())
        self.assertTrue(self.tabs)

    def test_a_record_the_services_write_is_written_only_through_them(self):
        written = service_written()
        for tab in self.tabs:
            with self.subTest(tab=tab.__name__):
                routed = getattr(tab, 'service_writes', False)
                if tab.model.__name__ not in written:
                    self.assertFalse(routed, f'{tab.__name__}: hr.services does not write {tab.model.__name__}')
                    continue
                self.assertTrue(routed, f'{tab.__name__}: hr.services writes {tab.model.__name__}, so the tab hands its '
                                        'writes to it (Resource.service_writes)')
                for action, hook in HOOKS:
                    if tab.allows(action):
                        self.assertIsNot(getattr(tab, hook).__func__, getattr(Resource, hook).__func__,
                                         f'{tab.__name__} offers {action}: its {hook} calls the service')
                self.assertIs(tab.after_save.__func__, Resource.after_save.__func__,
                              f'{tab.__name__}: crud never runs after_save on a tab the service writes')


class OneMondayTests(SimpleTestCase):
    def test_the_week_starts_in_one_place(self):
        found = [path for path, tree in production_modules() for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef) and node.name == 'monday']
        self.assertEqual(found, ['hr/rules.py'])
