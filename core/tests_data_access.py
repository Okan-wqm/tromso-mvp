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
- **Rule V, the new look's props builders** (an area's `pages.py` and `lists.py`, `config/*_props.py`, and core's
  shared builders, PRESENTATION): they shape what their view read through the area's reader into an island's props, so
  they neither write nor query (no manager, no `get_object_or_404`, no cursor). Every module named like a builder is one
  of them or is listed in NOT_PRESENTATION with its reason.
- **Rule S, one writer per record** (the architecture audit of 26.11.2026, H-5). A kind of record is written by its tab
  (core.crud saves the form) or by its area's service, never by both: two writers keep two copies of its rules. A model
  that declares `service_written = True` (HR's people, placements, plans, leave requests and attendance) is written by
  its app's `services.py` only: every tab of it hands every write it offers to the service
  (`Resource.service_writes`; each hook is read and must call into `services`, itself or through a method of its own
  class), has no `after_save`, and NO other production module (a view, a command, the admin, another app) builds or
  writes it by name; the delete plan's restore refuses it (core.softdelete.restore). The models a `services.py` writes
  are found, not listed: those it logs (`audit.entity_type_of(Model)`), builds (`Model(...)`) or writes through a
  manager, the name resolved by the module's own imports. What is not yet one writer is a ratchet, exact and never
  raised: the tabs crud still saves beside a service that writes their model (SECOND_WRITER_TABS, each with what the
  two writers are; closed by the follow-up listed in the plan) and the modules that build or write an undeclared service-written
  model by name (BUILT_ELSEWHERE, a count and a reason).

The scan is by name: it sees the usual spellings (a write through `getattr` or a variable holding a manager is not
seen). It keeps developers inside the layers; the database's roles keep a mistake or a compromise from rewriting
history (H-1)."""
import ast
import importlib
from collections import Counter
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent
APPS = ('alarms', 'core', 'experiments', 'farm', 'hr', 'inventory', 'knowledge', 'messaging', 'monitoring', 'reports',
        'sensors', 'tasks',
        'config')        # not an app: the project's own pages (the overviews, their props builders, the navigation)

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
    'farm/water/points.py': 'the sampling points',
    'sensors/bindings.py': 'where a channel measures',
    'sensors/credentials.py': "the broker's credentials",
}
# (b) a model's own methods that write its row: its save and delete, the base class's soft delete and restore, and the
# form key's note (core.models.EntryKey, written by core.crud in the creating transaction).
MODEL_WRITERS = ('save', 'delete', 'soft_delete', '_write', 'restore', 'note')
# (d) {module: (ceiling, reason)}: writes outside (a) to (c), counted per module. Lower a ceiling with a fix, never raise it.
WRITES_ALLOWED = {
    'core/language.py': (1, "a person's language, their own profile's one field (core.language.set_language)"),
    'core/readlog.py': (2, 'the read log (core.AccessEvent): who read which confidential record, its one write path, '
                           'called by core.sealing where a read happens (one row, or one statement for a page)'),
    'experiments/roles.py': (1, 'the recommended roles of manage.py experiments_roles (a command, as hr/roles.py)'),
    'core/rev.py': (2, "the revision counters' repair (manage.py core_rev_*): the database moves them, these "
                       'restore them'),
    'farm/equipment_types.py': (2, "the equipment types' seed, run by a migration's RunPython on the historical "
                                   'models'),
    'farm/forms/equipment.py': (2, "an equipment's system links saved with the record as one list, inside crud's "
                                   "transaction (form.save_m2m, as Django saves a form's many-to-many; the "
                                   'data-layering audit, L-2)'),
    'hr/roles.py': (1, 'the two role presets of manage.py hr_roles, each logged as the roles tab logs a new role '
                       '(L-3)'),
    'sensors/demo.py': (7, "the development tool's demo configuration (core/management/devtool.py: refused outside "
                            'development)'),
    # Write paths of their own, counted rather than exempted whole (the landing review, M-2): a new write in the module
    # that answers "may these fish be harvested" fails here until it is reviewed.
    'farm/health/withdrawal.py': (4, 'the withdrawal acknowledgements and their approvals (2), and the what-if of a '
                                     "moved or restored record (2, an UPDATE rolled back: L-7's design takes them off)"),
    'farm/water/rederive.py': (1, 'the pH re-derivation behind the gate, a reason and a log entry per sample'),
    'sensors/alarms.py': (3, "the sensor rules' events opened and closed, the sensors' own state (their alarm, logged, "
                             'is alarms.services.open_alarm)'),
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
    # added on the landing review (m-14): the fish's identity, the handling acknowledgements, the lice counts, the
    # harvests and the water limits
    'Batch': 'farm/stock', 'HandlingAcknowledgement': 'farm/handling', 'LiceCount': 'farm/health',
    'HarvestRecord': 'farm/harvest', 'WaterLimit': 'farm/water',
}
# {(module, model): ceiling}: the reads of owned models found outside their owner when the guard came. Lower, never raise.
READS_ALLOWED = {
    ('alarms/resources.py', 'WaterLimit'): 1,
    ('alarms/sources.py', 'AlarmEvent'): 3,
    ('alarms/sources.py', 'WaterLimit'): 4,
    ('experiments/design.py', 'Batch'): 2,
    ('experiments/read.py', 'Batch'): 3,
    ('experiments/read.py', 'FeedingRecord'): 3,
    ('experiments/read.py', 'StockMovement'): 6,
    ('farm/feeding/read.py', 'Batch'): 4,
    ('farm/feeding/read.py', 'StockMovement'): 4,
    ('farm/feeding/views.py', 'Batch'): 6,
    ('farm/forms/feeding_protocol.py', 'Batch'): 4,
    ('farm/forms/feeding_protocol.py', 'StockMovement'): 2,
    ('farm/forms/harvest.py', 'Batch'): 5,
    ('farm/forms/health.py', 'HealthEvent'): 1,
    ('farm/forms/stock.py', 'HealthEvent'): 1,
    ('farm/handling/check.py', 'Batch'): 3,
    ('farm/harvest/read.py', 'HandlingAcknowledgement'): 1,
    ('farm/harvest/read.py', 'StockMovement'): 2,
    ('farm/harvest/views.py', 'Batch'): 3,
    ('farm/harvest/views.py', 'StockMovement'): 3,
    ('farm/health/read.py', 'StockMovement'): 5,
    ('farm/health/services.py', 'StockOperation'): 2,
    ('farm/health/views.py', 'Batch'): 1,
    ('farm/health/withdrawal.py', 'Batch'): 13,
    ('farm/health/withdrawal.py', 'FeedingRecord'): 4,
    ('farm/health/withdrawal.py', 'HandlingAcknowledgement'): 1,
    ('farm/health/withdrawal.py', 'StockMovement'): 6,
    ('farm/management/commands/check_withdrawal.py', 'Batch'): 2,
    ('farm/management/commands/check_withdrawal.py', 'HandlingAcknowledgement'): 2,
    ('farm/management/commands/check_withdrawal.py', 'WithdrawalAcknowledgement'): 1,
    ('farm/management/commands/fix_seed_size_mix.py', 'Batch'): 4,
    ('farm/models/harvest.py', 'HarvestRecord'): 2,
    ('farm/models/site.py', 'StockMovement'): 2,
    ('farm/models/stock.py', 'StockMovement'): 2,
    ('farm/models/tank.py', 'StockMovement'): 2,
    ('farm/models/water_point.py', 'WaterMeasurement'): 2,
    ('farm/resources/feed.py', 'FeedingRecord'): 2,
    ('farm/resources/feeding_protocol.py', 'Batch'): 3,
    ('farm/resources/harvest_plan.py', 'StockMovement'): 1,
    ('farm/resources/health_event.py', 'HealthEvent'): 5,
    ('farm/resources/medicine.py', 'Treatment'): 2,
    ('farm/resources/species.py', 'StockMovement'): 2,
    ('farm/stock/integrity.py', 'HandlingAcknowledgement'): 2,
    ('farm/stock/integrity.py', 'HarvestRecord'): 2,
    ('farm/stock/integrity.py', 'WithdrawalAcknowledgement'): 2,
    ('farm/stock/services.py', 'HealthEvent'): 2,
    ('farm/water/degree_days.py', 'Batch'): 2,
    ('farm/water/read.py', 'Batch'): 2,
    ('inventory/read.py', 'FeedingRecord'): 6,
    ('reports/compute/biomass.py', 'Batch'): 5,
    ('reports/compute/biomass.py', 'FeedingRecord'): 1,
    ('reports/compute/cleaner.py', 'Batch'): 2,
    ('reports/compute/cleaner.py', 'FeedingRecord'): 1,
    ('reports/compute/lice.py', 'Batch'): 2,
    ('reports/compute/lice.py', 'LiceCount'): 8,
    ('reports/compute/lice.py', 'StockOperation'): 2,
    ('reports/compute/lice.py', 'Treatment'): 15,
    ('reports/compute/notices.py', 'Batch'): 2,
    ('reports/compute/notices.py', 'HealthEvent'): 2,
    ('reports/compute/notices.py', 'StockOperation'): 3,
    ('reports/compute/slaughter.py', 'StockMovement'): 3,
    ('reports/compute/slaughter.py', 'StockOperation'): 5,
    ('reports/compute/smolt.py', 'Batch'): 2,
    ('reports/compute/stock.py', 'Batch'): 1,
    ('reports/compute/stock.py', 'StockOperation'): 2,
    ('reports/due.py', 'Batch'): 2,
    ('reports/due.py', 'HarvestRecord'): 2,
    ('reports/due.py', 'HealthEvent'): 4,
    ('reports/due.py', 'StockMovement'): 4,
    ('reports/forms.py', 'HealthEvent'): 2,
    ('reports/forms.py', 'StockMovement'): 1,
    ('reports/resources.py', 'HealthEvent'): 5,
    ('reports/services.py', 'Batch'): 2,
    ('tasks/forms.py', 'Batch'): 4,
}

# ---- rule P ------------------------------------------------------------------------------------------------------------
GIVEN_HOME = 'farm/feeding/read.py'
PRESENT_HOME = 'farm/stock/read.py'
PRESENT_ALLOWED = {
    'farm/stock/integrity.py': 'every (unit, batch) sum, zero and negative ones too, set against the fold: a check of '
                               'the ledger, not a count of fish now',
    'farm/health/read.py': 'the fish a health event recorded, per event: what was handled, not what is there',
}

# ---- rule S ------------------------------------------------------------------------------------------------------------
SERVICE_WRITES = {'save', 'create', 'bulk_create', 'bulk_update', 'update', 'delete', 'soft_delete', 'get_or_create',
                  'update_or_create'}
HOOKS = (('add', 'create_record'), ('change', 'change_record'), ('delete', 'delete_record'))
# Every way to a model's rows by name: its managers, and the two that pass a sealed or soft-delete manager
# (`_base_manager`, `_default_manager`: the spellings core/tests_sealing.py holds for the sealed models).
ROW_MANAGERS = ('objects', 'all_objects', '_base_manager', '_default_manager')
# {tab: the two writers}: a tab crud saves although its area's service writes the same model too. Found when the guard
# came (the review of wip/hr-one-path, M-2); each is closed by the follow-up listed in the plan. Never add one.
SECOND_WRITER_TABS = {
    'ReportResource': "crud creates and edits a draft's answers; reports.services.submit files it (status, receipt, "
                      'frozen content) and start_correction creates a draft of its own: a second creator',
    'TaskResource': 'crud creates and edits a task; tasks.services moves its status (start, complete, cancel, reopen) and '
                    'materialise creates the tasks of a series: a second creator',
    'ExperimentResource': "crud creates and edits an experiment's own columns (with an after_save); experiments.services "
                          'writes its allocation and status (save_places, randomise, start) and copy creates one: a '
                          'second creator',
    'CardTemplateResource': 'crud creates and edits a template; monitoring.services.copy_template creates its copy: a '
                            'second creator',
}
# {(module, model): (count, reason)}: an undeclared service-written model built or written by name outside its service.
BUILT_ELSEWHERE = {
    ('alarms/engine.py', 'Notification'): (2, "the pass builds the notifications alarms.services.queue_many writes"),
    ('alarms/engine.py', 'Escalation'): (1, "the pass builds the escalations alarms.services writes in one statement"),
    ('alarms/sources.py', 'AlarmSubjectState'): (1, "a subject's state built for the pass; alarms.services writes them"),
    ('farm/forms/feeding.py', 'FeedingRecord'): (1, "the feeding form's empty instance on its unit; the save is the "
                                                    "service's"),
    ('farm/forms/health.py', 'Treatment'): (1, "the treatment form's empty instance; the save is the service's"),
    ('farm/forms/health.py', 'LiceCount'): (1, "the lice count form's empty instance; the save is the service's"),
    ('farm/water/rederive.py', 'WaterMeasurement'): (1, 'the pH re-derivation behind the gate (WRITES_ALLOWED)'),
}


def _models():
    from django.apps import apps
    found = {}
    for model in apps.get_models():
        found.setdefault(model.__name__, []).append(model)
    return found


def _imported(module, tree):
    """{name bound in the module: (the absolute module it comes from, the name there)} for its imports: `from x import
    name as alias` gives alias: (x, name), `from hr import models` gives models: (hr, models), `import hr.models as m`
    gives m: (hr.models, '')."""
    package = module.split('/')[:-1]
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = package[:len(package) - node.level + 1] if node.level else []
            source = '.'.join([*base, *(node.module.split('.') if node.module else [])])
            for alias in node.names:
                found[alias.asname or alias.name] = (source, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    found[alias.asname] = (alias.name, '')
    return found


def _service_forms():
    """{form class: its model} of the model forms whose model declares `service_written`."""
    from django import forms

    from core.datamap import all_model_forms
    return {form: form._meta.model for form in all_model_forms()
            if issubclass(form, forms.ModelForm) and getattr(getattr(form, '_meta', None), 'model', None) is not None
            and getattr(form._meta.model, 'service_written', False)}


def models_written(module, tree, models=None, service_forms=None):
    """Counter of the models a module builds or writes by name, and those it logs (`audit.entity_type_of(Model)`,
    counted 0: a write through a variable is seen by its log entry): {model: n}. What it sees, by the model's name
    imported (an alias too) or through its app's models module (`models.Posting`, `import hr.models as m`):
    `Model(...)`; `Model.<manager>....<write>()` through any manager (`objects`, `all_objects`, `_base_manager`,
    `_default_manager`); `QuerySet(Model)....<write>()`; and `<name>.save()` of a name bound in the same function to a
    model form of a declared model (`form = ShiftAssignmentForm(...)`; crud's own save is core/crud.py's). What it
    does not see: a row held in a variable, a related manager (`person.postings.create()`), a write through
    `getattr`: the model itself refuses those at run time (core.writers)."""
    models = models or _models()
    service_forms = _service_forms() if service_forms is None else service_forms
    forms_by_name = {(form.__module__, form.__name__): model for form, model in service_forms.items()}
    imported = _imported(module, tree)
    found = Counter()

    def of_app(source, model):
        return source.split('.')[0] == model.__module__.split('.')[0] and 'models' in source.split('.')

    def model_named(name):
        source, original = imported.get(name, ('', ''))
        return next((model for model in models.get(original, ()) if of_app(source, model)), None)

    def model_through(chain):
        """The model a chain names through its app's models module: [module alias, Model, ...]; None otherwise."""
        if len(chain) < 2 or chain[0] not in imported:
            return None
        source, original = imported[chain[0]]
        where = f'{source}.{original}' if original else source
        return next((model for model in models.get(chain[1], ()) if where.split('.')[-1] == 'models'
                     and of_app(where, model)), None)

    def form_named(name):
        source, original = imported.get(name, ('', ''))
        return next((model for (form_module, form_name), model in forms_by_name.items()
                     if form_name == original and (form_module == source or form_module.startswith(source + '.'))),
                    None)

    for function in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
        bound = {}                       # name: the declared model of the model form it holds, in this function
        for node in ast.walk(function):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) \
                    and form_named(node.value.func.id):
                bound.update({target.id: form_named(node.value.func.id) for target in node.targets
                              if isinstance(target, ast.Name)})
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'save' \
                    and isinstance(node.func.value, ast.Name) and node.func.value.id in bound:
                found[bound[node.func.value.id]] += 1
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == 'entity_type_of' and node.args:
            argument = node.args[0]
            model = model_named(argument.id) if isinstance(argument, ast.Name) else \
                model_through(_chain(argument)) if isinstance(argument, ast.Attribute) else None
            if model is not None:
                found[model] += 0
        elif isinstance(func, ast.Name) and model_named(func.id):
            found[model_named(func.id)] += 1
        elif isinstance(func, ast.Attribute) and func.attr not in SERVICE_WRITES and model_through(_chain(func)) \
                and len(_chain(func)) == 2:
            found[model_through(_chain(func))] += 1                      # models.Posting(...)
        elif isinstance(func, ast.Attribute) and func.attr in SERVICE_WRITES:
            chain = _chain(func.value)
            if len(chain) > 1 and chain[1] in ROW_MANAGERS and model_named(chain[0]):
                found[model_named(chain[0])] += 1
            elif len(chain) > 2 and chain[2] in ROW_MANAGERS and model_through(chain):
                found[model_through(chain)] += 1
            elif chain[:1] == ['QuerySet']:
                # `QuerySet(Model)...update()`: the rows as stored, past every manager (core/tests_sealing.py reads the
                # same spelling for a sealed model)
                root = func.value
                while isinstance(root, (ast.Attribute, ast.Call)) and not (
                        isinstance(root, ast.Call) and isinstance(root.func, ast.Name)):
                    root = root.value if isinstance(root, ast.Attribute) else root.func
                if isinstance(root, ast.Call) and root.args and isinstance(root.args[0], ast.Name) \
                        and model_named(root.args[0].id):
                    found[model_named(root.args[0].id)] += 1
    return found


def service_written():
    """{model: the services.py that writes it} for every model its own app's services write."""
    models, service_forms = _models(), _service_forms()
    found = {}
    for module, tree in production_modules():
        if module.endswith('/services.py'):
            for model in models_written(module, tree, models, service_forms):
                if module.split('/')[0] == model.__module__.split('.')[0]:
                    found[model] = module
    return found


def written_elsewhere(owners):
    """{(module, model name): count} of the service-written models built or written by name outside their service."""
    models, service_forms = _models(), _service_forms()
    found = {}
    for module, tree in production_modules():
        for model, count in models_written(module, tree, models, service_forms).items():
            if count and model in owners and owners[model] != module:
                found[(module, model.__name__)] = count
    return found


def calls_a_service(tab, hook, seen=()):
    """Whether a tab's hook calls one of its area's service WRITERS (`services.<writer>(...)`, itself or through a
    method of its own class): a public function of the services module that core/tests_service_rights.py holds as a
    writer (not a question of its NOT_A_WRITER), and never saves the form itself."""
    import inspect
    import textwrap

    from .tests_service_rights import NOT_A_WRITER
    services = importlib.import_module(f'{tab.model._meta.app_label}.services')
    tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(tab, hook))))
    calls = [_chain(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
    if any(chain[-1:] == ['save'] and chain[:1] == ['form'] for chain in calls):
        return False
    for chain in calls:
        if chain[:1] == ['services'] and len(chain) == 2 and not chain[1].startswith('_') \
                and inspect.isfunction(getattr(services, chain[1], None)) \
                and f'{services.__name__}.{chain[1]}' not in NOT_A_WRITER:
            return True
        if chain[:1] == ['cls'] and len(chain) == 2 and chain[1] not in seen and hasattr(tab, chain[1]) \
                and calls_a_service(tab, chain[1], (*seen, hook)):
            return True
    return False


# ---- rule V ------------------------------------------------------------------------------------------------------------
# A props builder is found by what it is, wherever it lives (the landing review, M-3): a function named for what crud and
# the views ask a builder for (a tab's `list_rows`, `list_next_props`, `next_panels`), a function named `*_props`, or one
# that builds with core.listprops (`L.row`, `L.cell`, ...). A view method (get, post, ...) that only hands its rows to a
# builder is no builder.
BUILDER_NAMES = ('list_rows', 'list_next_props', 'next_panels')
VIEW_METHODS = ('get', 'post', 'put', 'patch', 'delete', 'dispatch')
# core's builders shared by every area's (the list, the form, its panels and payload, the page's sayings): every
# function of these modules is one.
SHARED_BUILDERS = ('core/listprops.py', 'core/formprops.py', 'core/formpanels.py', 'core/formpayload.py',
                   'core/pagesays.py')
# {(module, function): reason}: shaped like a builder, not one.
NOT_PRESENTATION = {}
QUERY_CALLS = ('get_object_or_404', 'get_list_or_404')


def _listprops_names(tree):
    """The names a module calls core.listprops by (`from core import listprops as L`, `from . import listprops`)."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module == 'core' or (node.level == 1 and node.module is None)):
            names.update(alias.asname or alias.name for alias in node.names if alias.name == 'listprops')
    return names


def builders(module, tree):
    """[FunctionDef] of the props builders of a module (see above)."""
    listprops = _listprops_names(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name in VIEW_METHODS:
            continue
        builds = any(isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name)
                     and child.value.id in listprops for child in ast.walk(node))
        if module in SHARED_BUILDERS or node.name in BUILDER_NAMES or node.name.endswith('_props') or builds:
            found.append(node)
    return found


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


MANAGERS = ('objects', 'all_objects', '_base_manager')
NOT_SQL_EXECUTE = ('softdelete', 'super')
# The ledger's columns rules P and F look for, however the sum is spelled: Sum('count_delta'), models.Sum(...),
# Sum('movements__count_delta') through a relation, Sum(F('count_delta')).
LEDGER_COLUMNS = {'count_delta': 'present', 'amount_kg': 'given'}
# {module: (ceiling, reason)}: SQL run from a name, not a literal, so rule W cannot read its verb. Lower, never raise.
NON_LITERAL_SQL = {
    'alarms/changes.py': (1, "the worker's look at the sensors' state (CHANNELS: a SELECT)"),
    'core/database.py': (3, "the database viewer's catalogue reads (COLUMNS_SQL, CONSTRAINTS_SQL, INDEXES_SQL)"),
    'core/operations.py': (4, "the migration operations' own DDL (TrackRev, KeepRows), run by migrate"),
    'core/rev.py': (2, "the revision triggers' repair replaying the migration's DDL (manage.py core_rev_*), and the "
                       "TimescaleDB update's look for constraint triggers on hypertables (a SELECT)"),
    'sensors/management/commands/sensors_ingest_role.py': (2, "the ingest role's ALTER ROLE through psycopg's sql "
                                                              'composition (quoted identifiers and literals)'),
    'sensors/read.py': (3, "the readings' SELECTs, built from module constants only"),
}


def _ledger_column(node):
    """The ledger column a Sum(...) call sums, or None."""
    if not node.args:
        return None
    argument = node.args[0]
    if isinstance(argument, ast.Call) and isinstance(argument.func, ast.Name) and argument.func.id == 'F' \
            and argument.args:
        argument = argument.args[0]
    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        column = argument.value.rsplit('__', 1)[-1]
        return column if column in LEDGER_COLUMNS else None
    return None


class _Scan(ast.NodeVisitor):
    def __init__(self, module):
        self.module, self.writes, self.reads, self.present, self.given = module, [], [], [], []
        self.queries = []           # rule V: a manager, a shortcut that queries, a cursor
        self.querysets = set()      # local names that hold a manager's queryset: `qs = X.objects.filter(...)`
        self.sql = []               # SQL run from a name, not a literal

    def visit_Assign(self, node):
        if any(name in MANAGERS for name in _chain(node.value)):
            self.querysets.update(target.id for target in node.targets if isinstance(target, ast.Name))
        self.generic_visit(node)

    def visit_Call(self, node):
        func = node.func
        if isinstance(func, ast.Attribute):
            receiver = _chain(func.value)
            if func.attr in WRITE_CALLS and self._is_write(func.attr, receiver, node):
                self.writes.append((node.lineno, '.'.join([*receiver, func.attr])))
            # an execute of SQL: on a cursor, a connection (Django's or psycopg's), a schema editor; not the delete
            # plan's `softdelete.execute(plan, user)` nor a command's `super().execute(...)`
            if func.attr == 'execute' and node.args and receiver and receiver[-1] not in NOT_SQL_EXECUTE:
                text = _literal(node.args[0])
                if text is None:
                    self.sql.append(node.lineno)
                elif text.lstrip().upper().startswith(SQL_WRITES):
                    self.writes.append((node.lineno, f'execute({text.lstrip()[:30]!r})'))
            if any(name in MANAGERS for name in receiver) or func.attr == 'cursor':
                self.queries.append((node.lineno, '.'.join([*receiver, func.attr])))
            for index, name in enumerate(receiver):
                if name in OWNED and index + 1 < len(receiver) and receiver[index + 1] in (
                        'objects', 'all_objects', '_base_manager'):
                    self.reads.append((node.lineno, name))
                    break
        if isinstance(func, ast.Name) and func.id in QUERY_CALLS:
            self.queries.append((node.lineno, func.id))
        if (isinstance(func, ast.Name) and func.id == 'Sum') or (isinstance(func, ast.Attribute) and func.attr == 'Sum'):
            column = _ledger_column(node)
            if column is not None:
                getattr(self, LEDGER_COLUMNS[column]).append(node.lineno)
        self.generic_visit(node)

    def _is_write(self, name, receiver, node):
        if name in ('save', 'delete'):
            # A model's save and delete take no positional argument: `assignments.save(user, rows)` or
            # `TeamList.save(user, ...)` is a write path's function called. A form's save is the crud's (core/crud.py);
            # a session, a file or a cache is no row.
            return not node.args and (not receiver or receiver[-1] not in (
                'form', 'session', 'cache', 'storage', 'file', 'formset', 'super'))
        held = len(receiver) == 1 and receiver[0] in self.querysets          # a queryset held in a local name
        if name == 'update':
            return held or any(hint in receiver for hint in QUERYSET_HINTS)
        return held or any(hint in receiver for hint in QUERYSET_HINTS) or (receiver and receiver[-1][:1].isupper()) \
            or len(receiver) >= 2


def scan():
    """{module: {'writes': [(line, call)], 'reads': Counter(model), 'present': [line]}} of the production modules."""
    found = {}
    for module, tree in production_modules():
        visitor = _Scan(module)
        visitor.visit(tree)
        # (b) the model's own methods: what a model module writes inside them
        model_writes = set()
        if '/models' in f'/{module}':
            # only a class's own methods of those names (a model's), never a module function that happens to share one
            for model in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
                for method in model.body:
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name in MODEL_WRITERS:
                        model_writes.update(child.lineno for child in ast.walk(method) if isinstance(child, ast.Call))
        writes = [(line, call) for line, call in visitor.writes if line not in model_writes]
        built = []                  # rule V: what the module's props builders query or write
        for builder in builders(module, tree):
            if (module, builder.name) in NOT_PRESENTATION:
                continue
            inner = _Scan(module)
            inner.visit(builder)
            built += [(line, f'{builder.name}: {call}') for line, call in inner.queries + inner.writes]
        found[module] = {'writes': writes, 'reads': Counter(model for _line, model in visitor.reads),
                         'present': visitor.present, 'given': visitor.given, 'queries': visitor.queries,
                         'sql': visitor.sql, 'built': built}
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


class ReadersImportNoViewTests(SimpleTestCase):
    """The data-layering audit, L-10: a reader (`read.py`, `fold.py`) never imports a views module: what it needs from
    another area is that area's reader (the in-force withdrawals: farm.handling.check.in_force_now)."""

    def test_no_reader_imports_a_views_module(self):
        found = {}
        for module, tree in production_modules():
            if not module.endswith(('/read.py', '/fold.py')):
                continue
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.ImportFrom):
                    names = [f'{node.module or ""}.{alias.name}' for alias in node.names]
                elif isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                if any(name.split('.')[-1] == 'views' or '.views.' in f'{name}.' for name in names):
                    found.setdefault(module, []).append(node.lineno)
        self.assertEqual(found, {})


class PropsBuildersOnlyShapeTests(SimpleTestCase):
    """Rule V: the new look's props builders, found by what they are (`builders`), shape what their view read through the
    area's reader; a query or a write in one is a read or a write outside the layers that no page test would see. The
    scan reads the builder's own body by name: a query through a related object or a model method it calls is not seen."""

    def test_no_props_builder_queries_or_writes(self):
        bad = {module: data['built'] for module, data in scan().items() if data['built']}
        self.assertEqual(bad, {}, "A props builder shapes rows its view read: ask the area's read.py in the view and "
                                  'pass the rows in.')

    def test_the_builders_are_found_where_they_live(self):
        found = {(module, node.name) for module, tree in production_modules() for node in builders(module, tree)}
        for expected in (('farm/water/page_next.py', 'page_props'), ('farm/stock/units_next.py', 'units_props'),
                         ('farm/resources/tank.py', 'list_rows'), ('farm/feeding/lists.py', 'assignments'),
                         ('config/production_props.py', 'production_props'), ('core/listprops.py', 'row')):
            with self.subTest(builder=expected):
                self.assertIn(expected, found)
        self.assertEqual(set(NOT_PRESENTATION) - found, set(), 'a listed exception is no builder any more')

    def test_the_scan_sees_a_query_and_a_shortcut(self):
        visitor = _Scan('x/pages.py')
        visitor.visit(ast.parse('Tank.objects.filter(a=1)' + chr(10) + 'get_object_or_404(Tank, pk=1)' + chr(10)
                                + 'connection.cursor()'))
        self.assertEqual([line for line, _call in visitor.queries], [1, 2, 3])

    def test_a_builder_found_by_its_shape_and_its_query_seen(self):
        tree = ast.parse('from core import listprops as L' + chr(10) + 'def rows(units):' + chr(10)
                         + '    return [L.row(u.pk, {}) for u in Tank.objects.all()]' + chr(10)
                         + 'def get(request):' + chr(10) + '    return L.page(Tank.objects.all())')
        self.assertEqual([node.name for node in builders('x/anything.py', tree)], ['rows'])


class ScannerSpellingTests(SimpleTestCase):
    """What the name-based scan sees (the landing review, m-11, m-12): the counter-examples it was shown to miss."""

    def scanned(self, *lines):
        visitor = _Scan('x/views.py')
        visitor.visit(ast.parse(chr(10).join(lines)))
        return visitor

    def test_a_sum_of_the_ledger_however_spelled(self):
        found = self.scanned("models.Sum('count_delta')", "Sum('movements__count_delta')", "Sum(F('count_delta'))",
                             "Sum('feedings__amount_kg')", "Sum('weight_g')")
        self.assertEqual((found.present, found.given), ([1, 2, 3], [4]))

    def test_a_queryset_held_in_a_name_and_written(self):
        found = self.scanned('rows = Task.objects.filter(a=1)', 'rows.update(b=2)', 'rows.delete()',
                             'other = {}', 'other.update(c=3)')
        self.assertEqual([line for line, _call in found.writes], [2, 3])

    def test_sql_from_a_name_is_counted(self):
        found = self.scanned('cursor.execute(statement)', "cursor.execute('SELECT 1')", 'softdelete.execute(plan, user)')
        self.assertEqual(found.sql, [1])

    def test_a_model_module_function_named_like_a_model_method_is_not_exempt(self):
        tree = ast.parse('def note(row):' + chr(10) + '    Other.objects.create(row=row)' + chr(10) + 'class M:'
                         + chr(10) + '    def save(self):' + chr(10) + '        Log.objects.create(row=self)')
        visitor = _Scan('x/models/m.py')
        visitor.visit(tree)
        exempt = {child.lineno for model in ast.walk(tree) if isinstance(model, ast.ClassDef) for method in model.body
                  if isinstance(method, ast.FunctionDef) and method.name in MODEL_WRITERS
                  for child in ast.walk(method) if isinstance(child, ast.Call)}
        self.assertEqual([line for line, _call in visitor.writes if line not in exempt], [2])


class NonLiteralSqlTests(SimpleTestCase):
    def test_sql_run_from_a_name_is_listed_with_its_reason(self):
        counts = {module: len(data['sql']) for module, data in scan().items() if data['sql']}
        self.assertEqual(counts, {module: ceiling for module, (ceiling, _why) in NON_LITERAL_SQL.items()},
                         'SQL run from a name: rule W cannot read its verb. Use a literal, or list it with its reason.')


class OneWriterTests(SimpleTestCase):
    """Rule S. The tabs are the declared ones (the URL configuration declares every Resource)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from importlib import import_module

        from django.conf import settings

        from core.crud import Resource
        import_module(settings.ROOT_URLCONF)
        cls.Resource = Resource
        cls.owners = service_written()
        cls.declared = {model for models in _models().values() for model in models
                        if getattr(model, 'service_written', False)}

    def test_the_scan_finds_what_the_services_write(self):
        names = {model.__name__ for model in self.owners}
        self.assertTrue({'AttendanceRecord', 'Employee', 'LeaveRequest', 'Posting', 'ShiftAssignment', 'StockOperation',
                         'Task', 'Report'} <= names, names)
        self.assertEqual({model.__name__ for model in self.declared},
                         {'AttendanceRecord', 'Employee', 'LeaveRequest', 'Posting', 'ShiftAssignment'})

    def test_a_declared_model_is_written_by_its_service(self):
        for model in self.declared:
            with self.subTest(model=model.__name__):
                self.assertIn(model, self.owners, f'{model.__name__} says service_written and no services.py of its app '
                                                  'writes it')

    def test_a_tab_of_a_declared_model_hands_every_write_to_the_service(self):
        Resource = self.Resource
        for tab in Resource.registry:
            with self.subTest(tab=tab.__name__):
                if tab.model not in self.declared:
                    self.assertFalse(tab.service_writes, f'{tab.__name__}: {tab.model.__name__} does not declare '
                                                         'service_written')
                    continue
                self.assertTrue(tab.service_writes, f'{tab.__name__}: {tab.model.__name__} is written by its service '
                                                    'only, so the tab hands its writes to it (Resource.service_writes)')
                for action, hook in HOOKS:
                    if tab.allows(action):
                        self.assertIsNot(getattr(tab, hook).__func__, getattr(Resource, hook).__func__,
                                         f'{tab.__name__} offers {action}: its {hook} calls the service')
                        self.assertTrue(calls_a_service(tab, hook), f'{tab.__name__}.{hook} calls no service')
                self.assertIs(tab.after_save.__func__, Resource.after_save.__func__,
                              f'{tab.__name__}: crud never runs after_save on a tab the service writes')

    def test_nothing_else_builds_or_writes_a_declared_model(self):
        found = {key: count for key, count in written_elsewhere(self.owners).items()
                 if key[1] in {model.__name__ for model in self.declared}}
        self.assertEqual(found, {}, 'A model that declares service_written is written by its services.py only: call the '
                                    'service (a command acts as a person who may).')

    def test_the_tabs_crud_still_saves_beside_a_service_are_the_listed_ones(self):
        found = {tab.__name__ for tab in self.Resource.registry
                 if tab.model in self.owners and not tab.service_writes}
        self.assertEqual(found, set(SECOND_WRITER_TABS), 'A tab whose model its service writes too: hand its writes to '
                                                         'the service (service_writes); a closed one leaves the list.')
        for tab, why in SECOND_WRITER_TABS.items():
            self.assertTrue(why.strip(), tab)

    def test_what_is_built_outside_its_service_is_listed_with_its_reason(self):
        declared = {model.__name__ for model in self.declared}
        found = {key: count for key, count in written_elsewhere(self.owners).items() if key[1] not in declared}
        self.assertEqual(found, {key: count for key, (count, _why) in BUILT_ELSEWHERE.items()},
                         'A service-written model built or written by name outside its service: lower a count with a '
                         'fix, never raise it.')

    def test_the_scan_sees_a_second_writer_in_any_module(self):
        """The mutation the review ran: a write of a person in a view."""
        tree = ast.parse('from .models import Employee' + chr(10) + 'def sneaky(pk, day):' + chr(10)
                         + '    Employee.objects.filter(pk=pk).update(left_on=day)')
        self.assertEqual({model.__name__: count for model, count in models_written('hr/views.py', tree).items()},
                         {'Employee': 1})
        elsewhere = ast.parse('from hr.models import ShiftAssignment' + chr(10) + 'ShiftAssignment(day=None)')
        self.assertEqual({model.__name__ for model in models_written('tasks/views.py', elsewhere)}, {'ShiftAssignment'})
        for spelling in ('Employee._base_manager.filter(pk=1).update(left_on=None)',
                         'Employee._default_manager.filter(pk=1).delete()',
                         'QuerySet(Employee).filter(pk=1).update(left_on=None)'):
            past = ast.parse('from hr.models import Employee' + chr(10) + spelling)
            self.assertEqual({model.__name__: count for model, count in models_written('core/admin.py', past).items()},
                             {'Employee': 1}, spelling)
        other = ast.parse('class Report:' + chr(10) + '    pass' + chr(10) + 'Report()')
        self.assertEqual(models_written('sensors/demo.py', other), Counter())

    def test_the_scan_sees_a_model_through_its_models_module_or_an_alias(self):
        """N-2 a, b: the spellings a command most likely uses (the seed imports `models`)."""
        for source in ('from ... import models' + chr(10) + 'models.Posting.objects.create(title="x")',
                       'from hr import models' + chr(10) + 'models.Posting(title="x")',
                       'import hr.models as m' + chr(10) + 'm.Posting.objects.filter(pk=1).update(title="x")',
                       'from hr.models import Employee as Person' + chr(10) + 'Person.objects.create(last_name="x")',
                       'from hr.models import Employee as Person' + chr(10) + 'Person(last_name="x")'):
            with self.subTest(source=source):
                found = {model.__name__ for model in models_written('hr/management/commands/seed_hr_demo.py',
                                                                    ast.parse(source))}
                self.assertEqual(len(found), 1, found)
                self.assertTrue(found <= {'Posting', 'Employee'})

    def test_a_form_of_a_declared_model_is_saved_by_crud_only(self):
        """N-2 d: `form.save()` of a model form whose model declares service_written, outside core/crud.py."""
        source = chr(10).join(['from hr.forms.roster import ShiftAssignmentForm', 'def view(request):',
                               '    form = ShiftAssignmentForm(request.POST)', '    form.save()'])
        self.assertEqual({model.__name__ for model in models_written('hr/views.py', ast.parse(source))},
                         {'ShiftAssignment'})

    def test_a_hook_that_asks_a_question_and_saves_the_form_calls_no_writer(self):
        """N-2 e: a hook passes only by calling one of the service's writers (not a question of NOT_A_WRITER)."""
        from core.crud import Resource
        from hr import services
        from hr.models import ShiftAssignment
        self.assertTrue(services.own_employee)
        declared = list(Resource.registry)
        try:
            class Probe(Resource):
                model = ShiftAssignment
                service_writes = True

                @classmethod
                def create_record(cls, request, form):
                    services.own_employee(request.user)
                    return form.save()
        finally:
            Resource.registry[:] = declared
        self.assertFalse(calls_a_service(Probe, 'create_record'))
