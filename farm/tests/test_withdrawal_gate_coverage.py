"""Cross-review 3 of the withdrawal gate (REVIEW-CROSS-3-health.md), the reviewer's probes adopted, each asserting the
safe behaviour:

1. a unit's system (the loop whose samples count for a unit without its own) is a withdrawal input: changed only through
   the guard, and the unit's edit page asks; a system, a unit or a species is not deleted or restored while a withdrawal
   holds fish it reaches;
2. a field named by its column (`unit_id`) is the field (`unit`);
3. a treatment's units change from either side of the link, or through the link table, only through the guard;
4. `loaddata` is refused like any other write; a point with samples is not soft deleted by itself; the admin's restore
   says the gate's refusal as a message;
5. a sampling point's edit locks the fish before the point, as a water sample does;
6. the registry covers every column the withdrawal readers read, derived from the queries they run;
7. a lice report's fingerprint at filing is the fingerprint of the scope version it stores."""
import importlib
import inspect
import json
import os
import re
import tempfile
from decimal import Decimal

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core import softdelete
from core.softdelete import plan_delete

from .. import withdrawal_gate as gate
from ..handling import check
from ..health import withdrawal
from ..models import Feed, SamplingPoint, Species, System, Tank, Treatment, WaterMeasurement
from ..stock import services as stock_services
from .helpers import going_on, point_of, role
from .test_harvest_inside_withdrawal import HarvestInsideTestCase
from .test_withdrawal_gate import edit_data


class GateNamesTests(HarvestInsideTestCase):
    def refused(self, write):
        with self.assertRaises(gate.UnguardedWithdrawalWrite), transaction.atomic():
            write()

    def test_an_owner_named_by_its_column_is_the_owner(self):
        point = point_of(self.t1)
        self.refused(lambda: SamplingPoint.objects.filter(pk=point.pk).update(unit_id=self.t2.pk))
        point.unit_id = self.t2.pk
        self.refused(lambda: SamplingPoint.objects.bulk_update([point], ['unit_id']))

    def test_a_treatments_units_from_the_other_side_and_through_the_link_table(self):
        treatment = self.treat(self.medicine(days=7), 9, 9)
        self.refused(lambda: self.t2.treatments.add(treatment))
        self.refused(lambda: Treatment.units.through.objects.create(treatment=treatment, tank=self.t2))
        self.refused(lambda: Treatment.units.through.objects.filter(treatment=treatment).delete())

    def test_loaddata_is_refused_like_any_write(self):
        treatment = self.treat(self.medicine(days=7), 9, 9)
        data = json.loads(serializers.serialize('json', [treatment]))
        data[0]['fields']['end_date'] = self.day(-30).isoformat()       # a course 30 days longer
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'treatment.json')
            with open(path, 'w', encoding='utf-8') as file:
                json.dump(data, file)
            self.refused(lambda: call_command('loaddata', path, verbosity=0))
        self.assertEqual(Treatment.objects.get().end_date, self.day(9))

    def test_a_point_with_samples_is_not_soft_deleted_by_itself(self):
        self.temperature(self.t1, 3, '20')
        point = point_of(self.t1)
        self.refused(lambda: point.soft_delete(self.user))

    def test_the_refusal_is_a_validation_error_so_every_form_and_the_admin_say_it(self):
        self.assertTrue(issubclass(gate.UnguardedWithdrawalWrite, ValidationError))


class LoopTestCase(HarvestInsideTestCase):
    """T-01 takes its water from the loop of RAS 1 (no sample of its own): 2 °C there; the species' assumed 10 °C."""

    def setUp(self):
        super().setUp()
        self.loop = System.objects.create(name='RAS 1', code='R1', site=self.bergen, production_department=self.hall)
        with gate.opened('test fixture: the unit in its loop, the assumed temperature'):
            Tank.all_objects.filter(pk=self.t1.pk).update(system=self.loop)
            Species.objects.filter(pk=self.salmon.pk).update(withdrawal_temperature_c=Decimal(10))
        self.t1.refresh_from_db()
        for days_ago in (5, 4, 3, 2, 1):
            self.temperature(self.loop, days_ago, '2')
        self.treat(self.medicine(degree_days=50), 6, 6)
        [self.before] = self.held()


class LoopTests(LoopTestCase):
    def test_moving_the_unit_out_of_its_loop_outside_the_guard_is_refused(self):
        self.t1.system = None
        with self.assertRaises(gate.UnguardedWithdrawalWrite), transaction.atomic():
            self.t1.save()

    def test_a_loop_change_that_moves_no_withdrawal_is_free_and_one_that_does_is_refused_row_by_row(self):
        with transaction.atomic():
            Tank.objects.filter(pk=self.t2.pk).update(system=self.loop)          # no fish of T-02 is treated
        self.assertEqual(Tank.objects.get(pk=self.t2.pk).system, self.loop)
        with self.assertRaises(gate.UnguardedWithdrawalWrite), transaction.atomic():
            Tank.objects.filter(pk__in=[self.t1.pk, self.t2.pk]).update(system=None)
        self.assertEqual(Tank.objects.get(pk=self.t1.pk).system, self.loop)

    def test_the_units_edit_page_asks_before_moving_it_out_of_its_loop(self):
        self.user.groups.add(role('Unit keeper', 'view_tank', 'change_tank'))
        url = reverse('farm:tank_edit', args=[self.t1.pk])
        data = edit_data(self.client.get(url).context['form'], system='')
        refused = self.client.post(url, data)
        self.assertEqual(refused.status_code, 422)
        change = refused.context['withdrawal_change']
        self.assertEqual([each.batch for each in change.released], [self.batch])
        self.assertEqual(Tank.objects.get(pk=self.t1.pk).system, self.loop)
        self.assertEqual(self.client.post(url, {**data, 'withdrawal_ack': change.fingerprint}).status_code, 302)
        self.assertIsNone(Tank.objects.get(pk=self.t1.pk).system)

    def test_a_system_whose_units_hold_fish_under_a_withdrawal_is_not_deleted(self):
        blockers = System.all_objects.get(pk=self.loop.pk).delete_blockers()
        self.assertTrue(any(self.batch.code in reason for reason in blockers), blockers)
        with self.assertRaises(gate.UnguardedWithdrawalWrite), transaction.atomic():
            softdelete.execute(plan_delete(System.all_objects.get(pk=self.loop.pk)), self.user)
        self.assertEqual(self.held()[0].until, self.before.until)

    def test_a_unit_or_a_species_reaching_held_fish_is_neither_deleted_nor_restored(self):
        for record in (Tank.all_objects.get(pk=self.t1.pk), Species.objects.get(pk=self.salmon.pk)):
            with self.subTest(record=record):
                self.assertTrue(any(self.batch.code in reason for reason in record.delete_blockers()))
                record.is_deleted = True
                with self.assertRaises(gate.UnguardedWithdrawalWrite), transaction.atomic():
                    record.save()

    def test_the_admins_restore_says_the_gates_refusal(self):
        admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(admin)
        with gate.opened('test fixture: a unit deleted behind the rules'):
            Tank.all_objects.filter(pk=self.t1.pk).update(is_deleted=True)
        response = self.client.post(reverse('admin:farm_tank_changelist'), {
            'action': 'restore', '_selected_action': [str(self.t1.pk)]}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'was not restored')
        self.assertTrue(Tank.all_objects.get(pk=self.t1.pk).is_deleted)


class LegitimateFlowTests(HarvestInsideTestCase):
    def test_a_person_removed_sets_the_bookkeeping_to_null(self):
        other = get_user_model().objects.create_user('veli', 'veli@example.com', 'eski-sifre-123')
        with gate.opened('test fixture'):
            sample = WaterMeasurement.objects.create(point=point_of(self.t1), measured_at=self.batch.created_at,
                                                     source='manual', temperature_c=Decimal(9), created_by=other)
        other.delete()
        self.assertIsNone(WaterMeasurement.all_objects.get(pk=sample.pk).created_by_id)

    def test_a_medicine_with_rows_is_deleted_on_its_page(self):
        medicine = self.medicine(days=7)
        with transaction.atomic():
            softdelete.execute(plan_delete(medicine), self.user)

    def test_a_restore_refused_is_a_validation_error(self):
        from ..health import services
        treatment = self.treat(self.medicine(days=1), 9, 9)
        going_on(services.void_treatment, self.user, treatment, 'Wrong unit')
        with self.assertRaises(ValidationError), transaction.atomic():
            softdelete.restore(Treatment.all_objects.get(pk=treatment.pk), self.user)


class LockOrderTests(HarvestInsideTestCase):
    def test_a_point_edit_locks_the_fish_before_the_point(self):
        self.user.groups.add(role('Point keeper', 'view_samplingpoint', 'change_samplingpoint'))
        point = point_of(self.t1)
        url = reverse('farm:samplingpoint_edit', args=[point.pk])
        data = edit_data(self.client.get(url).context['form'], description='By the outlet')
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.client.post(url, data).status_code, 302)
        locks = [query['sql'] for query in queries.captured_queries if 'FOR UPDATE' in query['sql']]
        first_batch = next(index for index, sql in enumerate(locks) if 'FROM "batches"' in sql)
        first_point = next(index for index, sql in enumerate(locks) if 'FROM "water_sampling_points"' in sql)
        self.assertLess(first_batch, first_point, locks)


# ---- 6: the registry covers what the readers read --------------------------------------------------------
# Columns the withdrawal readers read that are not what a withdrawal is worked out from, each with why. Anything else
# they read must be in the gate's registry: a new column a reader starts to read fails here until it is registered or
# said here.
NOT_INPUTS = {
    'id': 'a row\'s identity',
    'code': 'a name shown in the text', 'name': 'a name shown in the text', 'common_name': 'a name shown in the text',
    'version': 'the optimistic lock', 'created_at': 'bookkeeping', 'updated_at': 'bookkeeping',
    'created_by_id': 'bookkeeping', 'updated_by_id': 'bookkeeping', 'deleted_by_id': 'bookkeeping',
    'deleted_at': 'bookkeeping', 'notes': 'free text', 'void_reason': 'free text',
}
# Columns of one table that are not inputs, each with why. A name the readers' code uses for something else (a reading's
# status, a point's kind, a sample's deleted flag) makes a loaded column of that name count as read: said here.
NOT_INPUT_COLUMNS = {
    ('feeds', 'is_deleted'): 'a deleted feed keeps its feedings and their type; no reader filters a feed by it',
    ('feeds', 'status'): 'whether a feed is offered for new feedings, not what a past one was',
    ('species', 'status'): 'whether a species is offered for new batches',
    ('species', 'max_weight_ratio'): 'the size limit: a question when fish arrive and a warning chip, never a withdrawal',
    ('systems', 'status'): 'not read: a loop counts while it is live and has an active middle point',
    ('systems', 'max_biomass_kg'): 'a loop\'s capacity, not its water',
    ('systems', 'site_id'): 'the loop\'s site: a name, the units\' own site gives the clock',
    ('systems', 'production_department_id'): 'a name',
    ('tanks', 'status'): 'not read: the fish in a unit are its stock lines',
    ('tanks', 'kind'): 'the kind of unit, not its water',
    ('tanks', 'water_type'): 'the salinity assumed where none was measured, never the temperature',
    ('tanks', 'volume_m3'): 'a measure', ('tanks', 'water_volume_m3'): 'a measure',
    ('tanks', 'max_biomass_kg'): 'a capacity',
    ('tanks', 'production_department_id'): 'gives the site\'s clock; a unit with stock records stays on its site '
                                           '(Tank.clean)',
}
# Whole tables that are not inputs: the batch and the site are identities and clocks (a site's time zone moves "today"
# for every record alike, never one withdrawal against another); the stock's own rows are registered.
NOT_INPUT_TABLES = {
    'batches': 'the batch is the identity the withdrawal is of; its species is fixed once stocked (the stock service)',
    'sites': 'the site gives the clock and the name',
    'production_departments': 'the department gives the site',
    'medicines': 'a medicine\'s name and how it is given; its withdrawal is its rows (registered)',
    'harvest_records': 'where a harvest went: the facility named in the text, never whether the withdrawal holds it',
    'slaughter_facilities': 'the facility named in the text',
    'equipment': 'a point\'s equipment, loaded with the point (with_owners): the withdrawal reads the middle points of '
                 'units and loops only',
    'feeds': None,                           # registered (feed_type); its other columns are names
    'species': None,                         # registered (withdrawal_temperature_c); others are names
    'tanks': None, 'systems': None, 'water_sampling_points': None,
}
# The code that works a withdrawal out from the rows it reads. A column a query only loads with its row (a unit's
# measures, a feed's energy) is read when this code names its field; a column a query filters, joins or orders by is read
# whatever names it.
READERS = ('farm.health.withdrawal', 'farm.water.degree_days', 'farm.water.read', 'farm.stock.read', 'farm.feeding.read',
           'farm.handling.withdrawal')


class RegistryCoverageTests(LoopTestCase):
    def test_every_column_the_readers_read_is_registered_or_said_not_to_be_an_input(self):
        feed = Feed.objects.create(name='Medisinfor', code='MED-1', feed_type='medicated')
        from ..feeding import services as feeding_services
        going_on(feeding_services.record_feeding, self.user, unit=self.t1, day=self.day(2), feed=feed,
                 amount_kg=Decimal('2'))
        seen = check.assess('harvest', self.t1, self.day(1), self.batch).fingerprint      # under a withdrawal
        stock_services.record_harvest(self.user, unit=self.t1, batch=self.batch, day=self.day(1), count=10,
                                      measured_weight_kg=Decimal('12'), facility=self.facility, handling_ack=seen)
        with CaptureQueriesContext(connection) as queries:
            withdrawal.snapshot({self.batch.pk}, self.today)
            withdrawal.harvests_inside()
        tables = {model._meta.db_table: model for model in apps.get_models(include_auto_created=True)}
        registered = {(model._meta.db_table, model._meta.get_field(name).column)
                      for model, fields in gate.REGISTRY.items() for name in (fields or ())}
        whole = {model._meta.db_table for model, fields in gate.REGISTRY.items() if fields is None}
        conditional = {(model._meta.db_table, model._meta.get_field(name).column)
                       for model, rules in gate.CONDITIONAL.items() for name in rules}
        source = '\n'.join(inspect.getsource(importlib.import_module(name)) for name in READERS)

        def named(table, column):
            field = next(field for field in tables[table]._meta.concrete_fields if field.column == column)
            return re.search(rf'[.\'"]{field.name}\b', source) is not None

        read = set()
        for query in queries.captured_queries:
            loaded, _from, rest = query['sql'].partition(' FROM ')
            decides = set(re.findall(r'"(\w+)"\."(\w+)"', rest))
            read |= {(table, column) for table, column in decides if table in tables}
            # A column only loaded with its row counts when the readers' code names its field.
            read |= {(table, column) for table, column in re.findall(r'"(\w+)"\."(\w+)"', loaded)
                     if table in tables and (table, column) not in decides and named(table, column)}
        said = {table for table, why in NOT_INPUT_TABLES.items() if why}
        missing = sorted((table, column) for table, column in read
                         if table not in whole | said and (table, column) not in registered | conditional
                         and column not in NOT_INPUTS and (table, column) not in NOT_INPUT_COLUMNS)
        self.maxDiff = None
        self.assertEqual(missing, [])


class ScopeVersionSourceTests(HarvestInsideTestCase):
    def test_the_scope_version_has_one_source(self):
        from reports import compute
        from reports.compute import lice, slaughter
        self.assertEqual(compute.SCOPE_VERSIONS, {'sea_lice': lice.SCOPE_VERSION,
                                                  'slaughter_planned': slaughter.SCOPE_VERSION})
        for module in (lice, slaughter):
            self.assertEqual(inspect.signature(module.scope).parameters['version'].default, module.SCOPE_VERSION)
