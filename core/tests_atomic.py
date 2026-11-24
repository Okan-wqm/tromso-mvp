"""The data-layering audit, L-13: the helpers that write inside their caller's transaction check that one is open
(core.atomic.required) and refuse in autocommit, where their locks would end at their first statement."""
import ast
from pathlib import Path

from django.db import TransactionManagementError
from django.test import SimpleTestCase

from . import atomic

ROOT = Path(__file__).resolve().parent.parent
# (module, function): the helpers that write inside their caller's transaction, as their docstrings say.
INSIDE_THE_CALLERS = {('experiments/services.py', 'move_span'), ('core/softdelete.py', 'execute'),
                      ('tasks/services.py', 'withdraw'), ('farm/stock/services.py', 'voided')}


class InsideTheCallersTests(SimpleTestCase):
    def test_outside_a_transaction_it_refuses_and_says_whose(self):
        with self.assertRaisesMessage(TransactionManagementError, 'tasks.services.withdraw'):
            atomic.required('tasks.services.withdraw')

    def test_each_helper_checks_first(self):
        for module, name in sorted(INSIDE_THE_CALLERS):
            with self.subTest(helper=f'{module}:{name}'):
                tree = ast.parse((ROOT / module).read_text(encoding='utf-8'))
                function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
                calls = [ast.unparse(node.func) for node in ast.walk(function) if isinstance(node, ast.Call)]
                self.assertIn('atomic.required', calls)
