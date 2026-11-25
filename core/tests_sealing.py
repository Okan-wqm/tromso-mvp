"""The seal's registry (core.sealing): every model whose rows lie on a unit or a system, or hang on a batch, a sampling
point, a sensor channel or binding, a stock operation, a health event, a task, a report or an experiment, says how it is
sealed (filtered by the cells, following its parent, or exempt with a written reason). A model added later with such a
link and no declaration fails here and in the system check, so no new table can read past the seal."""
from django.apps import apps
from django.db import models
from django.test import SimpleTestCase, TestCase
from django.test.utils import isolate_apps

from core import sealing
from farm.models import Tank

# The records a sealed cell reaches: a model with a link to one of these (directly or through other models) is keyed.
KEYED = ('farm.Tank', 'farm.System', 'farm.Batch', 'farm.SamplingPoint', 'farm.Equipment', 'farm.StockOperation',
         'farm.HealthEvent', 'sensors.Binding', 'sensors.Channel', 'tasks.Task', 'reports.Report',
         'experiments.Experiment')


class RegistryTests(SimpleTestCase):
    def test_every_keyed_model_declares_its_seal(self):
        self.assertEqual(sealing.undeclared(apps.get_models()), [])

    def test_the_keyed_records_are_the_ones_named(self):
        self.assertEqual(sorted(sealing.KEYED), sorted(KEYED))

    def test_every_filtered_model_is_filtered_by_each_of_its_managers(self):
        """A filtered model's managers (`objects` and `all_objects`) both carry the seal; only Django's base manager,
        which a link to one record follows, does not."""
        unsealed = [f'{seal.model._meta.label}.{manager.name}' for seal in sealing.registry() if seal.filters
                    for manager in seal.model._meta.managers if not isinstance(manager, sealing.SealedMixin)]
        self.assertEqual(unsealed, [])

    def test_an_exempt_model_says_why(self):
        self.assertEqual([seal.model._meta.label for seal in sealing.registry()
                          if seal.mode == sealing.EXEMPT and len(seal.reason) < 20], [])

    @isolate_apps('core')
    def test_a_new_model_on_a_unit_without_a_declaration_fails_the_check(self):
        class Weighing(models.Model):
            unit = models.ForeignKey(Tank, on_delete=models.PROTECT)

        class WeighingNote(models.Model):
            weighing = models.ForeignKey(Weighing, on_delete=models.CASCADE)

        class Plain(models.Model):
            name = models.CharField(max_length=10)

        self.assertEqual(sealing.undeclared([Weighing, WeighingNote, Plain]),
                         ['core.Weighing', 'core.WeighingNote'])
        errors = sealing.check_registry(models=[Weighing])
        self.assertEqual([error.id for error in errors], ['core.E101'])


class ViewerTests(SimpleTestCase):
    """Who is looking: a request's person, someone named by `as_viewer`, the system for a named reason, or nobody (a
    read of a sealed model then fails, it never shows everything)."""

    def setUp(self):
        sealing.leave_process_system()
        self.addCleanup(sealing.enter_process_system, 'tests')

    def test_nobody_looking_fails_closed(self):
        with self.assertRaises(sealing.NoViewer):
            sealing.viewer()

    def test_the_system_reads_everything_for_its_reason(self):
        with sealing.system('the delete plan'):
            self.assertIsNone(sealing.viewer())
            self.assertEqual(sealing.system_reason(), 'the delete plan')
        with self.assertRaises(sealing.NoViewer):
            sealing.viewer()

    def test_a_named_viewer_is_loaded_once(self):
        loads = []

        class Provider:
            @staticmethod
            def load(user):
                loads.append(user)
                return sealing.Viewer(user_id=user.pk, username='kari', team=frozenset({'x'}))

        previous = sealing.provider()
        sealing.register_provider(Provider)
        self.addCleanup(sealing.register_provider, previous)
        user = type('User', (), {'pk': 7, 'is_authenticated': True, 'is_superuser': False,
                                 'get_username': lambda self: 'kari'})()
        with sealing.as_viewer(user):
            first, second = sealing.viewer(), sealing.viewer()
        self.assertIs(first, second)
        self.assertEqual((len(loads), first.user_id, first.sees('water')), (1, 7, frozenset({'x'})))

    def test_an_anonymous_visitor_sees_nothing_sealed(self):
        from django.contrib.auth.models import AnonymousUser
        with sealing.as_viewer(AnonymousUser()):
            self.assertEqual(sealing.viewer(), sealing.NOBODY)

    def test_management_commands_but_runserver_read_as_the_system(self):
        self.assertEqual(sealing.process_reason(['manage.py', 'migrate']), 'command migrate')
        self.assertEqual(sealing.process_reason(['manage.py', 'test', 'core']), 'command test')
        self.assertIsNone(sealing.process_reason(['manage.py', 'runserver']))
        self.assertIsNone(sealing.process_reason(['manage.py']))


class MiddlewareTests(SimpleTestCase):
    def setUp(self):
        sealing.leave_process_system()
        self.addCleanup(sealing.enter_process_system, 'tests')

    def test_a_request_and_its_streamed_answer_read_as_the_person(self):
        from django.contrib.auth.models import AnonymousUser
        from django.http import StreamingHttpResponse
        from django.test import RequestFactory
        seen = []

        def chunks():
            seen.append(sealing.viewer())
            yield b'row'

        def view(request):
            seen.append(sealing.viewer())
            return StreamingHttpResponse(chunks())

        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        response = sealing.SealingMiddleware(view)(request)
        with self.assertRaises(sealing.NoViewer):
            sealing.viewer()                      # the request is over
        self.assertEqual(b''.join(response.streaming_content), b'row')
        self.assertEqual(seen, [sealing.NOBODY, sealing.NOBODY])

    def test_it_comes_after_authentication(self):
        from django.conf import settings
        order = settings.MIDDLEWARE
        self.assertGreater(order.index('core.sealing.SealingMiddleware'),
                           order.index('django.contrib.auth.middleware.AuthenticationMiddleware'))


class AccessLogTests(TestCase):
    def test_a_read_is_logged_for_the_viewer_and_the_log_is_append_only(self):
        from django.contrib.auth import get_user_model
        from django.db import DatabaseError, IntegrityError, transaction

        from core.models import AccessEvent
        user = get_user_model().objects.create_user('kari', 'kari@example.com', 'x')
        with sealing.system('a job'):
            self.assertIsNone(sealing.log_access('view', 'experiment', 'E1'))
        with sealing.as_viewer(user):
            event = sealing.log_access('export', 'experiment', 'E1', part='data', route='experiments:x')
        event.refresh_from_db()
        self.assertEqual((event.user_id, event.user_name, event.kind, event.entity_type, event.entity_id, event.part,
                          event.route), (user.pk, 'kari', 'export', 'experiment', 'E1', 'data', 'experiments:x'))
        for write in (lambda: AccessEvent.objects.filter(pk=event.pk).update(kind='view'),
                      lambda: AccessEvent.objects.filter(pk=event.pk).delete()):
            with self.assertRaises(DatabaseError), transaction.atomic():
                write()
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccessEvent.objects.create(user_name='kari', kind='peek', entity_type='experiment', entity_id='E1')


# The places that read past the seal, each named by its call site (the file and the function it is in, review T3): a
# new use in a file already listed fails here as surely as one in a new file. Say why in the list, or read as the viewer.
# Reading as the system (`sealing.system(`, `reads_as_system`): a figure that must count everything, the delete plan,
# the booking check.
SYSTEM_CALLS = {
    'core/softdelete.py:plan_delete': 'the delete plan reaches every record its links reach; what the person may not '
                                      'see is counted, never named, and a delete that reaches it is refused to them',
    'experiments/read.py:booked': 'the booking check: a booking holds its tank whoever may read it, and is said with '
                                  'its days only',
    'experiments/read.py:cards': 'the oversee card, which says only the trial, its lead, its approval, its days and '
                                 'its care instructions',
    'experiments/preflight.py:report': 'the report before confidentiality goes live: counts and names every experiment',
    'reports/compute/__init__.py:compute': 'a regulatory report counts every unit (a legal figure is never partial); '
                                           'who opens it is the right to read reports (owner amendment C1)',
    'reports/compute/common.py:fingerprint': 'the fingerprint of the rows a filed report read, as compute read them',
    'farm/health/withdrawal.py:Reader': 'the medicine withdrawal holds fish wherever they went, over every unit '
                                        '(reads_as_system on its reader); what is printed is read as the person',
    'farm/health/withdrawal.py:_harvest_lines': 'the withdrawal’s facts: the harvests of every unit',
    'farm/health/withdrawal.py:_reached': 'the withdrawal’s facts: where the treated fish went',
    'farm/health/withdrawal.py:guarded_ceiling': 'the withdrawal guard’s ceiling over every unit',
    'inventory/read.py:_feeding': 'the store’s book: feed drawn per site and day is a stock figure, every feeding '
                                  'counts',
    'inventory/read.py:overview': 'the store’s book, its overview',
    'inventory/read.py:undelivered': 'the store’s book, the feed not yet delivered',
    'inventory/views.py:_feeding_days': 'the store’s feeding per site, feed and day, the same figure as the book',
    'reports/due.py:due': 'the regulatory due list: a duty is owed whoever looks (a sealed tank’s notifiable '
                          'disease too)',
    'reports/due.py:no_longer_match': 'the due list’s duties that no longer match, over every unit',
    'experiments/sealing.py:keepers': 'the alarms’ fallback: who keeps the fish of a sealed cell (its lead, the '
                                      'Oversee holders), asked by the alarm loop',
    'farm/stock/read.py:ledger': 'the stock fold: a fold over part of a batch’s lines is a wrong figure; what is '
                                 'shown of it is narrowed where it is shown',
    'farm/stock/read.py:spans': 'the stock fold’s spans, over every line of a batch',
}
# Reading with SQL of its own (a cursor, raw(), RawSQL), which the managers' seal does not reach: each reads nothing
# sealed or only what the seal already let through. Management commands read as the system and are not listed.
RAW_SQL = {
    'alarms/changes.py:token': 'the count and the sum of the transaction ids of sensors_channel_state: two numbers, no '
                               'row (the alarm worker’s look, as the system)',
    'alarms/engine.py:_lock': 'an advisory lock, no rows',
    'alarms/outbox.py:_claim': 'an advisory lock per notification, no rows',
    'alarms/outbox.py:_release': 'an advisory lock per notification, no rows',
    'alarms/services.py:_set_open': 'writes an alarm subject’s state for an alarm the engine raises, as the system',
    'alarms/worker.py:Worker._finish': 'the worker’s advisory lock, no rows',
    'alarms/worker.py:Worker._holds': 'the worker’s backend pid, no rows',
    'alarms/worker.py:Worker._lead': 'the worker’s advisory lock and backend pid, no rows',
    'alarms/worker.py:Worker._session': 'the worker’s application name, no rows',
    'core/checks.py:plain_private_values': 'a deployment check over the log’s private values, as the system',
    'core/codes.py:next_code': 'the next number of a code sequence: a number, no record',
    'core/database.py:Table.counts': 'the estimate of a hypertable’s rows; its rows are counted through the seal',
    'core/database.py:Table.structure': 'the catalogue of a table (columns, constraints, indexes)',
    'core/database.py:hypertables': 'the names of the hypertables',
    'core/erasure.py:_attempt': 'the erasure of a person’s data by the platform admin’s command, as the system',
    'core/rev.py:ensure': 'the revision counters of core_rev: a scope, a key and a number, no row of a record',
    'core/rev.py:mark_built': 'the revision counters of core_rev',
    'core/rev.py:missing': 'the revision counters of core_rev',
    'core/rev.py:rebuild': 'the revision counters of core_rev',
    'core/rev.py:rev': 'the revision counters of core_rev',
    'core/rev.py:settle': 'the revision counters of core_rev',
    'core/rev.py:stamp': 'the revision counters of core_rev',
    'inventory/services.py:item_for': 'an advisory lock, no rows',
    'knowledge/search.py:parse': 'the text search configuration’s stems of the typed words, no rows',
    'sensors/alarms.py:_extremes': 'the readings of a channel a sensor alarm rule watches, evaluated as the system',
    'sensors/provider.py:SensorSource.values_at': 'the readings of the bindings the sealed Binding manager returned, '
                                                  'inside their windows',
    'sensors/read.py:_raw_rows': 'the readings of the channels the sealed managers returned',
    'sensors/read.py:chart_rows': 'the readings and rollups of the channels the sealed managers returned',
    'sensors/read.py:replay_rows': 'the readings of the channels the sealed managers returned',
    'sensors/read.py:value_at': 'the reading of a channel the sealed managers returned',
}
# Reading the activity log past its seal (AuditLog._base_manager; its `objects` leaves out what the person may not see,
# review L5).
LOG_PAST_THE_SEAL = {
    'core/audit.py:revision': 'the change token: it reads the entries’ stamps itself (`_left_out`), never the seal, '
                              'so a poll costs two indexed queries',
}


def call_sites(found, skip_management=False):
    """{'file:function'} of the project's code (no tests, migrations or tools) where `found(node, imported)` is true for a
    node; `imported`: the names the module imports from core.sealing."""
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    sites = set()
    for path in root.rglob('*.py'):
        relative = path.relative_to(root).as_posix()
        if ('/tests' in f'/{relative}' or relative.startswith(('node_modules', '.venv', 'static', 'scripts'))
                or '/migrations/' in relative or relative.split('/')[-1].startswith(('test_', 'tests_'))
                or relative == 'core/sealing.py' or (skip_management and '/management/' in relative)):
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        imported = {alias.asname or alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                    and node.module == 'core.sealing' for alias in node.names}

        def walk(node, where):
            for child in ast.iter_child_nodes(node):
                inner = where
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    inner = f'{where}.{child.name}' if where else child.name
                if found(child, imported):
                    sites.add(f'{relative}:{where or "<module>"}')
                walk(child, inner)
        walk(tree, '')
    return sites


def _called(node):
    """(owner name or '', attribute or function name) of a call, or None."""
    import ast
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute):
        return (func.value.id if isinstance(func.value, ast.Name) else '<expr>'), func.attr
    if isinstance(func, ast.Name):
        return '', func.id
    return None


def reads_as_system(node, imported):
    called = _called(node)
    if called is None:
        return False
    owner, name = called
    if name not in ('system', 'reads_as_system'):
        return False
    return owner in ('sealing', 'core_sealing') or (owner == '' and name in imported)


def reads_with_sql(node, imported):
    called = _called(node)
    if called is None:
        return False
    owner, name = called
    return (owner != '' and name in ('cursor', 'raw')) or (owner == '' and name == 'RawSQL')


def reads_the_log_past_its_seal(node, imported):
    import ast
    return (isinstance(node, ast.Attribute) and node.attr in ('_base_manager', '_default_manager')
            and isinstance(node.value, ast.Name) and node.value.id == 'AuditLog')


class SystemCallSiteTests(SimpleTestCase):
    def test_only_the_named_places_read_as_the_system(self):
        self.assertEqual(sorted(call_sites(reads_as_system)), sorted(SYSTEM_CALLS))


class RawSqlSiteTests(SimpleTestCase):
    def test_only_the_named_places_read_with_sql_of_their_own(self):
        self.assertEqual(sorted(call_sites(reads_with_sql, skip_management=True)), sorted(RAW_SQL))


class LogReadSiteTests(SimpleTestCase):
    def test_only_the_named_places_read_the_activity_log_past_its_seal(self):
        self.assertEqual(sorted(call_sites(reads_the_log_past_its_seal)), sorted(LOG_PAST_THE_SEAL))

    def test_a_new_site_in_a_listed_file_is_found(self):
        """T3: a site is a function, not a file: a second system read in a file already listed is a new site."""
        import ast
        tree = ast.parse('from core import sealing\ndef listed():\n    with sealing.system("x"):\n        pass\n'
                         'def another():\n    with sealing.system("y"):\n        pass\n')
        calls = [node for node in ast.walk(tree) if reads_as_system(node, set())]
        self.assertEqual(len(calls), 2)
