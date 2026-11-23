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


# The places that read as the system, each with its reason (a figure that must count everything, the delete plan, the
# booking check). Another use of `sealing.system(` fails here: say why in this list, or read as the viewer.
SYSTEM_CALLS = {
    'core/sealing.py': 'the framework itself',
    'core/softdelete.py': 'the delete plan reaches every record its links reach; what the person may not see is counted, '
                          'never named, and a delete that reaches it is refused to them',
    'experiments/read.py': 'the booking check: a booking holds its tank whoever may read it, and is said with its days '
                           'only; the oversee card, which says only the trial, its lead, its approval and its days',
    'experiments/preflight.py': 'the report before confidentiality goes live: counts and names every experiment',
    'reports/compute/__init__.py': 'a regulatory report counts every unit (a legal figure is never partial); who opens '
                                   'it is the right to read reports (owner amendment C1)',
    'reports/compute/common.py': 'the fingerprint of the rows a filed report read, as compute read them',
    'farm/health/withdrawal.py': 'the medicine withdrawal holds fish wherever they went, over every unit '
                                 '(module_reads_as_system); a page shows only what it may of it',
    'farm/stock/read.py': 'the stock fold: a fold over part of a batch’s lines is a wrong figure; what is shown of it is '
                          'narrowed where it is shown',
}
# The places that read with SQL of their own (a cursor, raw()), which the managers' seal does not reach, each with why it
# reads nothing sealed or reads only what the seal already let through. Another one fails here.
RAW_SQL = {
    'alarms/engine.py': 'an advisory lock, no rows',
    'alarms/services.py': 'writes an alarm subject’s state for an alarm the engine raises, as the system (run_alarms)',
    'core/checks.py': 'the database server’s version',
    'core/rev.py': 'the revision counters of core_rev (core-rev): a scope, a key and a number, no row of a record',
    'core/codes.py': 'the next number of a code sequence: a number, no record',
    'core/database.py': 'the catalogue of a table (columns, constraints, indexes, the estimate of a hypertable’s rows); '
                        'its rows are read through the seal (core.dbgrid)',
    'core/erasure.py': 'the erasure of a person’s data by the platform admin’s command, as the system',
    'inventory/services.py': 'an advisory lock, no rows',
    'knowledge/search.py': 'the text search configuration’s stems of the typed words, no rows',
    'sensors/alarms.py': 'the readings of a channel a sensor alarm rule watches, evaluated as the system (run_alarms)',
    'sensors/provider.py': 'the readings of the bindings the sealed Binding manager returned, inside their windows',
    'sensors/read.py': 'the readings and rollups of the channels the sealed managers returned (a channel number is '
                       'never taken from a request without them)',
}


class SystemCallSiteTests(SimpleTestCase):
    def test_only_the_named_places_read_as_the_system(self):
        import pathlib
        import re
        root = pathlib.Path(__file__).resolve().parent.parent
        found = set()
        for path in root.rglob('*.py'):
            relative = path.relative_to(root).as_posix()
            if '/tests' in f'/{relative}' or relative.startswith(('node_modules', '.venv')) or '/migrations/' in relative:
                continue
            if re.search(r'\bsealing\.(system|module_reads_as_system)\(|^\s*with system\(', path.read_text(encoding='utf-8'), re.M):
                found.add(relative)
        found.add('core/sealing.py')
        self.assertEqual(sorted(found), sorted(SYSTEM_CALLS))


class RawSqlSiteTests(SimpleTestCase):
    def test_only_the_named_places_read_with_sql_of_their_own(self):
        import pathlib
        import re
        root = pathlib.Path(__file__).resolve().parent.parent
        found = set()
        for path in root.rglob('*.py'):
            relative = path.relative_to(root).as_posix()
            if '/tests' in f'/{relative}' or relative.startswith(('node_modules', '.venv')) or '/migrations/' in relative                     or '/management/' in relative or relative.split('/')[-1].startswith('test_'):
                continue
            if re.search(r'\.cursor\(\)|\.raw\(|RawSQL\(', path.read_text(encoding='utf-8')):
                found.add(relative)
        self.assertEqual(sorted(found), sorted(RAW_SQL))
