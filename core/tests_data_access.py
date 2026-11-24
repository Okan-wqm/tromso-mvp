"""The layering contract, read from the code (the data-layering audit, M-5): who may write, who may read the safety data,
and the one definition of fish present now. An AST scan of the production modules (the apps' `.py` files outside
`migrations/`, `tests/`, `test_*.py`, `tests_*.py`), the same family as core/tests_company_clock.py (a scan with a reviewed
list and its reasons) and core/test_lean_endpoints.py (the list must be exactly what is found), with the ratchet of
scripts/check-ds.mjs: each ceiling is the count found, so a fix must lower it and nothing may raise it. A SimpleTestCase:
no database, about a second.

- **Rule W, writes.** An ORM write (`.save()`, `.create()`, `.bulk_create()`, `.bulk_update()`, `.get_or_create()`,
  `.update_or_create()`, `.delete()`, a queryset's `.update()`) or a `cursor.execute` / `schema_editor.execute` of a
  literal that starts with INSERT, UPDATE, DELETE, TRUNCATE, ALTER, CREATE, DROP or GRANT stands only in (a) an area's
  `services.py` or a declared write-path module (WRITE_PATHS); (b) a model's own `save`/`delete` and the base class's
  soft delete (a model module's method of that name); (c) a management command (each is in the README's table, held by
  core/tests_commands.py); (d) WRITES_ALLOWED, a ceiling and a reason per module. A write in a `read.py`, a `fold.py`,
  a template tag or a view not in (d) fails, naming the call, the line and where the area's writes belong.
- **Rule R, reads of the safety data.** A query of an owned model (OWNED: `Model.objects`, `.all_objects`,
  `._base_manager`) outside its owner's package stands only in READS_ALLOWED, a ceiling per (module, model): a pure
  ratchet over what the audit found; any new module or a higher count fails.
- **Rule P, fish present now.** `Sum('count_delta')` stands only in the stock reader (farm/stock/read.py, `present`) and
  the places of PRESENT_ALLOWED (a different figure, said why).
- **Rule F, feed given.** `Sum('amount_kg')` stands only in the feeding reader (farm/feeding/read.py, `given`).

The scan is by name: it sees the usual spellings (a write through `getattr` or a variable holding a manager is not
seen). It keeps developers inside the layers; the database's roles keep a mistake or a compromise from rewriting
history (H-1)."""
import ast
from collections import Counter
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent
APPS = ('alarms', 'core', 'experiments', 'farm', 'hr', 'inventory', 'knowledge', 'messaging', 'monitoring', 'reports',
        'sensors', 'tasks')

# ---- rule W ------------------------------------------------------------------------------------------------------------
WRITE_CALLS = {'save', 'create', 'bulk_create', 'bulk_update', 'get_or_create', 'update_or_create', 'delete', 'update'}
# A call of these on something that is not a queryset or a model is not a database write.
QUERYSET_HINTS = ('objects', 'all_objects', '_base_manager', 'filter', 'exclude', 'select_for_update', 'all',
                  'select_related', 'prefetch_related', 'order_by', 'only', 'defer', 'annotate')
SQL_WRITES = ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'ALTER', 'CREATE', 'DROP', 'GRANT', 'REVOKE')
# (a) the write paths besides the areas' services.py: each the one writer of what it names.
WRITE_PATHS = {
    'core/crud.py': 'every tab: permission, version, audit, soft delete (core.crud.Resource)',
    'core/softdelete.py': 'the delete plan of every record',
    'core/audit.py': 'the one writer of the activity log',
    'core/accountmail.py': "the account e-mails' outbox (README, Email)",
    'core/erasure.py': "a stranger's address erased from the log (manage.py erase_stranger_address, docs/erasure.md)",
    'farm/feeding/protocols.py': 'the feeding protocols and their tables',
    'farm/feeding/assignments.py': "the protocols' assignments",
    'farm/handling/check.py': 'the handling acknowledgements',
    'farm/health/withdrawal.py': 'the withdrawal acknowledgements and their approvals',
    'farm/water/points.py': 'the sampling points',
    'farm/water/rederive.py': "the pH re-derivation behind the gate, a reason and a log entry per sample",
    'sensors/bindings.py': 'where a channel measures',
    'sensors/credentials.py': "the broker's credentials",
    'sensors/alarms.py': "the sensor rules' events, the sensors' own state (their alarm, logged, is "
                         'alarms.services.open_alarm)',
}
# (b) a model's own methods that write its row: its save and delete, the base class's soft delete and restore, and the
# form key's note (core.models.EntryKey, written by core.crud in the creating transaction).
MODEL_WRITERS = ('save', 'delete', 'soft_delete', '_write', 'restore', 'note')
# (d) {module: (ceiling, reason)}: writes outside (a) to (c), counted per module. Lower a ceiling with a fix, never raise it.
WRITES_ALLOWED = {
    'core/language.py': (1, "a person's language, their own profile's one field (core.language.set_language)"),
    'core/rev.py': (2, "the revision counters' repair (manage.py core_rev_*): the database moves them, these "
                       'restore them'),
    'farm/equipment_types.py': (2, "the equipment types' seed, run by a migration's RunPython on the historical "
                                   'models'),
    'farm/forms/equipment.py': (2, "an equipment's system links saved with the record as one list, inside crud's "
                                   "transaction (form.save_m2m, as Django saves a form's many-to-many; the "
                                   'data-layering audit, L-2)'),
    'hr/roles.py': (1, 'the two role presets of manage.py hr_roles, each logged as the roles tab logs a new role '
                       '(L-3)'),
    'sensors/demo.py': (12, "the development tool's demo configuration (core/management/devtool.py: refused outside "
                            'development)'),
}

# ---- rule R ------------------------------------------------------------------------------------------------------------
# {model: the package that owns it}: its read API is there (read.py, fold.py, services.py and the rest of the package).
OWNED = {
    'StockMovement': 'farm/stock', 'StockOperation': 'farm/stock',
    'FeedingRecord': 'farm/feeding',
    'WaterMeasurement': 'farm/water', 'WaterSample': 'farm/water',
    'Treatment': 'farm/health', 'HealthEvent': 'farm/health', 'WithdrawalAcknowledgement': 'farm/health',
    'Alarm': 'alarms', 'Notification': 'alarms', 'Acknowledgement': 'alarms', 'AlarmClearance': 'alarms',
    'Reading': 'sensors', 'AlarmEvent': 'sensors',
}
# {(module, model): ceiling}: the reads of owned models found outside their owner when the guard came. Lower, never raise.
READS_ALLOWED = {
    ('alarms/sources.py', 'AlarmEvent'): 3,
    ('experiments/read.py', 'FeedingRecord'): 3,
    ('experiments/read.py', 'StockMovement'): 6,
    ('farm/feeding/read.py', 'StockMovement'): 4,
    ('farm/forms/feeding_protocol.py', 'StockMovement'): 2,
    ('farm/forms/health.py', 'HealthEvent'): 3,
    ('farm/forms/stock.py', 'HealthEvent'): 1,
    ('farm/harvest/read.py', 'StockMovement'): 2,
    ('farm/harvest/views.py', 'StockMovement'): 3,
    ('farm/health/read.py', 'StockMovement'): 5,
    ('farm/health/services.py', 'StockOperation'): 2,
    ('farm/health/withdrawal.py', 'FeedingRecord'): 4,
    ('farm/health/withdrawal.py', 'StockMovement'): 6,
    ('farm/management/commands/check_withdrawal.py', 'WithdrawalAcknowledgement'): 1,
    ('farm/models/site.py', 'StockMovement'): 2,
    ('farm/models/stock.py', 'StockMovement'): 2,
    ('farm/models/tank.py', 'StockMovement'): 2,
    ('farm/models/water_point.py', 'WaterMeasurement'): 2,
    ('farm/resources/feed.py', 'FeedingRecord'): 2,
    ('farm/resources/harvest_plan.py', 'StockMovement'): 1,
    ('farm/resources/health_event.py', 'HealthEvent'): 5,
    ('farm/resources/medicine.py', 'Treatment'): 2,
    ('farm/resources/species.py', 'StockMovement'): 2,
    ('farm/stock/integrity.py', 'WithdrawalAcknowledgement'): 2,
    ('farm/stock/services.py', 'HealthEvent'): 2,
    ('farm/stock/views.py', 'HealthEvent'): 4,
    ('inventory/read.py', 'FeedingRecord'): 6,
    ('reports/compute/biomass.py', 'FeedingRecord'): 1,
    ('reports/compute/cleaner.py', 'FeedingRecord'): 1,
    ('reports/compute/lice.py', 'StockOperation'): 2,
    ('reports/compute/lice.py', 'Treatment'): 15,
    ('reports/compute/notices.py', 'HealthEvent'): 2,
    ('reports/compute/notices.py', 'StockOperation'): 3,
    ('reports/compute/slaughter.py', 'StockMovement'): 3,
    ('reports/compute/slaughter.py', 'StockOperation'): 5,
    ('reports/compute/stock.py', 'StockOperation'): 2,
    ('reports/due.py', 'HealthEvent'): 4,
    ('reports/due.py', 'StockMovement'): 4,
    ('reports/forms.py', 'HealthEvent'): 2,
    ('reports/forms.py', 'StockMovement'): 1,
    ('reports/resources.py', 'HealthEvent'): 5,
    ('sensors/read.py', 'WaterMeasurement'): 3,
}

# ---- rule P ------------------------------------------------------------------------------------------------------------
GIVEN_HOME = 'farm/feeding/read.py'
PRESENT_HOME = 'farm/stock/read.py'
PRESENT_ALLOWED = {
    'farm/stock/integrity.py': 'every (unit, batch) sum, zero and negative ones too, set against the fold: a check of '
                               'the ledger, not a count of fish now',
    'farm/health/read.py': 'the fish a health event recorded, per event: what was handled, not what is there',
}


def production_modules():
    for app in APPS:
        for path in sorted((ROOT / app).rglob('*.py')):
            relative = path.relative_to(ROOT).as_posix()
            parts = relative.split('/')
            if 'migrations' in parts or 'tests' in parts or parts[-1] == 'tests.py' or parts[-1].startswith(
                    ('test_', 'tests_')):
                continue
            yield relative, ast.parse(path.read_text(encoding='utf-8'), relative)


def _chain(node):
    """The names along a call's receiver: ['Task', 'objects', 'filter'] for Task.objects.filter(...).update()."""
    names = []
    while True:
        if isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
            node = node.value
        elif isinstance(node, ast.Name):
            names.append(node.id)
            return names[::-1]
        else:
            return names[::-1]


def _literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant):
        return str(node.values[0].value)
    return None


class _Scan(ast.NodeVisitor):
    def __init__(self, module):
        self.module, self.writes, self.reads, self.present, self.given = module, [], [], [], []

    def visit_Call(self, node):
        func = node.func
        if isinstance(func, ast.Attribute):
            receiver = _chain(func.value)
            if func.attr in WRITE_CALLS and self._is_write(func.attr, receiver, node):
                self.writes.append((node.lineno, '.'.join([*receiver, func.attr])))
            if func.attr == 'execute' and node.args:
                text = _literal(node.args[0])
                if text and text.lstrip().upper().startswith(SQL_WRITES):
                    self.writes.append((node.lineno, f'execute({text.lstrip()[:30]!r})'))
            for index, name in enumerate(receiver):
                if name in OWNED and index + 1 < len(receiver) and receiver[index + 1] in (
                        'objects', 'all_objects', '_base_manager'):
                    self.reads.append((node.lineno, name))
                    break
        if isinstance(func, ast.Name) and func.id == 'Sum' and node.args and isinstance(node.args[0], ast.Constant):
            if node.args[0].value == 'count_delta':
                self.present.append(node.lineno)
            elif node.args[0].value == 'amount_kg':
                self.given.append(node.lineno)
        self.generic_visit(node)

    def _is_write(self, name, receiver, node):
        if name in ('save', 'delete'):
            # A model's save and delete take no positional argument: `assignments.save(user, rows)` or
            # `TeamList.save(user, ...)` is a write path's function called. A form's save is the crud's (core/crud.py);
            # a session, a file or a cache is no row.
            return not node.args and (not receiver or receiver[-1] not in (
                'form', 'session', 'cache', 'storage', 'file', 'formset', 'super'))
        if name == 'update':
            return any(hint in receiver for hint in QUERYSET_HINTS)
        return any(hint in receiver for hint in QUERYSET_HINTS) or (receiver and receiver[-1][:1].isupper()) or (
            len(receiver) >= 2)


def scan():
    """{module: {'writes': [(line, call)], 'reads': Counter(model), 'present': [line]}} of the production modules."""
    found = {}
    for module, tree in production_modules():
        visitor = _Scan(module)
        visitor.visit(tree)
        # (b) the model's own methods: what a model module writes inside them
        model_writes = set()
        if '/models' in f'/{module}':
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in MODEL_WRITERS:
                    model_writes.update(child.lineno for child in ast.walk(node) if isinstance(child, ast.Call))
        writes = [(line, call) for line, call in visitor.writes if line not in model_writes]
        found[module] = {'writes': writes, 'reads': Counter(model for _line, model in visitor.reads),
                         'present': visitor.present, 'given': visitor.given}
    return found


def write_allowed(module):
    parts = module.split('/')
    return (parts[-1] == 'services.py' or module in WRITE_PATHS or 'management' in parts
            and 'commands' in parts)


def outside(found):
    """{module: count} of the writes outside (a) to (c)."""
    return {module: len(data['writes']) for module, data in found.items() if data['writes'] and not write_allowed(module)}


def foreign_reads(found):
    """{(module, model): count} of the reads of owned models outside their owner's package."""
    reads = {}
    for module, data in found.items():
        for model, count in data['reads'].items():
            if not module.startswith(OWNED[model] + '/') and module != OWNED[model] + '.py':
                reads[(module, model)] = count
    return reads


class WriteLayerTests(SimpleTestCase):
    def test_every_write_outside_the_write_paths_is_listed_with_its_reason(self):
        found = scan()
        counts = outside(found)
        new = {module: [f'{line}: {call}' for line, call in found[module]['writes']]
               for module in counts if module not in WRITES_ALLOWED}
        self.assertEqual(new, {}, 'A write outside the write paths: move it into the area\'s services.py (or crud), '
                                  'or list it in WRITES_ALLOWED with its reason in review.')
        over = {module: (counts.get(module, 0), ceiling) for module, (ceiling, _why) in WRITES_ALLOWED.items()
                if counts.get(module, 0) != ceiling}
        self.assertEqual(over, {}, '(found, ceiling): a ceiling is the count found; lower it after a fix, never raise it.')

    def test_no_reader_template_tag_or_fold_writes(self):
        found = scan()
        bad = {module: data['writes'] for module, data in found.items() if data['writes']
               and (module.endswith(('/read.py', '/fold.py')) or '/templatetags/' in module)}
        self.assertEqual(bad, {})

    def test_every_listed_write_path_exists_and_has_a_reason(self):
        for module, reason in {**WRITE_PATHS, **{key: why for key, (_n, why) in WRITES_ALLOWED.items()}}.items():
            with self.subTest(module=module):
                self.assertTrue((ROOT / module).is_file())
                self.assertTrue(reason.strip())


class ReadLayerTests(SimpleTestCase):
    def test_reads_of_the_safety_data_outside_their_owner_only_shrink(self):
        reads = foreign_reads(scan())
        new = {key: count for key, count in reads.items() if key not in READS_ALLOWED}
        self.assertEqual(new, {}, 'A read of safety data outside its owner: use the owner\'s read.py.')
        changed = {key: (reads.get(key, 0), ceiling) for key, ceiling in READS_ALLOWED.items()
                   if reads.get(key, 0) != ceiling}
        self.assertEqual(changed, {}, '(found, ceiling): lower the ceiling after a fix, never raise it.')

    def test_every_owner_exists(self):
        for model, owner in OWNED.items():
            with self.subTest(model=model):
                self.assertTrue((ROOT / owner).is_dir() or (ROOT / f'{owner}.py').is_file())


class FishPresentNowTests(SimpleTestCase):
    def test_fish_present_now_is_summed_by_the_stock_reader_only(self):
        found = scan()
        elsewhere = {module: data['present'] for module, data in found.items()
                     if data['present'] and module != PRESENT_HOME and module not in PRESENT_ALLOWED}
        self.assertEqual(elsewhere, {}, "Fish present now is farm.stock.read.present: ask it, never sum the ledger.")
        self.assertTrue(found[PRESENT_HOME]['present'])
        for module in PRESENT_ALLOWED:
            with self.subTest(module=module):
                self.assertTrue(found[module]['present'], f'{module} sums no more: take it off PRESENT_ALLOWED.')


class FeedGivenTests(SimpleTestCase):
    def test_feed_given_is_summed_by_the_feeding_reader_only(self):
        found = scan()
        elsewhere = {module: data['given'] for module, data in found.items() if data['given'] and module != GIVEN_HOME}
        self.assertEqual(elsewhere, {}, 'Feed given is farm.feeding.read.given: use it, never sum amount_kg.')
        self.assertTrue(found[GIVEN_HOME]['given'])


class HealthEventsOfAUnitTests(SimpleTestCase):
    """The data-layering audit, L-9: which health events concern a unit (of its site, naming it or no unit) is written in
    farm/health/read.py only (`concerns`, `concerning`): no other module spells the "names no unit" half."""

    def test_the_rule_is_spelled_by_the_health_reader_only(self):
        spelled = {}
        for module, tree in production_modules():
            lines = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.keyword)
                     and node.arg in ('units__isnull', 'health_event__units__isnull')]
            if lines:
                spelled[module] = lines
        self.assertEqual(set(spelled), {'farm/health/read.py'})
