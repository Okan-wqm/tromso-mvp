"""Cross-review 2 of the withdrawal guard (REVIEW-CROSS-2-health.md):

- the write runs ONCE, in a savepoint: refused and rolled back when the impact is not acknowledged, kept as it is when it
  is, so nothing the first run changed in memory (a unit's status) is lost (1, 5);
- the gate is enforced at the data layer: a change to a withdrawal input outside the guard is refused, whatever writes it
  (save, delete, queryset update, delete or bulk create), and the Setup pages that edit such an input (a feed's type, a
  species' assumed temperature, a sampling point's active/kind/owner) ask through the guard (2, 3);
- any change that moves the end of a held batch's withdrawal earlier is asked, with the old and the new end (4);
- the acknowledgement is an explicit argument of each write (`withdrawal_ack`), never ambient (6);
- the fish's units are locked before the batches in them are read (7);
- an acknowledgement covers the end it was given for: a withdrawal that grows past it is asked again, and
  check_withdrawal no longer calls it acknowledged (8)."""
import io
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.models import AuditLog

from .. import withdrawal_gate as gate
from ..feeding import services as feeding_services
from ..health import services
from ..health.withdrawal import WithdrawalChanged
from ..models import (
    Feed, FeedingRecord, MedicineWithdrawal, SamplingPoint, Species, StockMovement, StockOperation, Tank, Treatment,
    WaterMeasurement, WithdrawalAcknowledgement,
)
from ..stock import read as stock_read, services as stock_services
from .helpers import going_on, point_of
from .test_harvest_inside_withdrawal import HarvestInsideTestCase
from .test_stock import make_unit


def edit_data(form, **changes):
    """What an edit page posts: the bound values of its form (as the page shows them), with `changes`."""
    data = {}
    for name, field in form.fields.items():
        value = form[name].value()
        if isinstance(value, (list, tuple)):
            data[name] = [str(each) for each in value]
        elif isinstance(value, bool):
            if value:
                data[name] = 'on'
        else:
            data[name] = '' if value is None else str(value)
    data.update(changes)
    return data


class OneRunTests(HarvestInsideTestCase):
    def test_an_acknowledged_transfer_keeps_the_new_units_status_and_its_log(self):
        """The review's probe: the first run's in-memory status change was lost on the second run."""
        t3 = make_unit('T-03', self.hall, status=Tank.Status.PREPARING)
        b2 = self.stock(self.t2)
        self.treat(self.medicine(days=7), 6, 6)              # T-01 (self.batch) treated 6 days ago
        self.assertIsNotNone(b2)

        # S-03, rule D: fish moved out of T-01 on a day before the course are out of its reach, so this move frees
        # fish held today, which the guard asks about. (Under the old rule the question came from a harvest of b2 out
        # of T-02, "inside" the withdrawal of the whole batch b2 once 100 of it were in T-01 on the course day: those
        # fish of T-02 were never exposed, and that harvest is no longer inside.)
        def move(**ack):
            return stock_services.record_transfer(self.user, source=self.t1, batch=self.batch, day=self.day(8),
                                                  legs=[(self.t2, 100), (t3, 100)], reason='other', notes='Split',
                                                  ack=True, **ack)

        with self.assertRaises(WithdrawalChanged) as caught:
            move()
        self.assertEqual(Tank.all_objects.get(pk=t3.pk).status, Tank.Status.PREPARING)   # rolled back
        move(withdrawal_ack=caught.exception.change.fingerprint)
        self.assertEqual((Tank.all_objects.get(pk=t3.pk).status, self.fish(t3)), (Tank.Status.ACTIVE, 100))
        self.assertTrue(AuditLog.objects.filter(entity_type='unit', entity_id=str(t3.pk),
                                                action='update').exists())

    def test_the_write_runs_once_when_acknowledged(self):
        treatment = self.treat(self.medicine(days=7), 2, 2)
        with self.assertRaises(WithdrawalChanged) as caught:
            services.void_treatment(self.user, treatment, 'Wrong unit')
        with mock.patch.object(services, 'voided', wraps=services.voided) as runs:
            services.void_treatment(self.user, treatment, 'Wrong unit',
                                    withdrawal_ack=caught.exception.change.fingerprint)
        self.assertEqual(runs.call_count, 1)
        self.assertTrue(Treatment.all_objects.get(pk=treatment.pk).is_deleted)

    def test_an_acknowledgement_of_another_impact_is_refused_and_nothing_is_written(self):
        treatment = self.treat(self.medicine(days=7), 2, 2)
        with self.assertRaises(WithdrawalChanged) as caught:
            services.void_treatment(self.user, treatment, 'Wrong unit', withdrawal_ack='not-what-was-shown')
        self.assertEqual(caught.exception.message_dict, {'withdrawal_ack': [
            'The warnings changed since the form was shown: read them again, and tick the box to go on.']})
        self.assertFalse(Treatment.all_objects.get(pk=treatment.pk).is_deleted)
        self.assertFalse(WithdrawalAcknowledgement.objects.exists())

    def test_the_stored_acknowledgements_are_the_shown_ones_and_logged_critical(self):
        treatment = self.treat(self.medicine(days=7), 2, 2)
        with self.assertRaises(WithdrawalChanged) as caught:
            services.void_treatment(self.user, treatment, 'Wrong unit')
        shown = caught.exception.change
        services.void_treatment(self.user, treatment, 'Wrong unit', withdrawal_ack=shown.fingerprint)
        [row] = WithdrawalAcknowledgement.objects.all()
        self.assertEqual((row.warning, row.batch, row.until), ('released', self.batch, self.day(-6)))
        log = AuditLog.objects.get(entity_type='treatment', entity_id=str(treatment.pk),
                                   severity=AuditLog.Severity.CRITICAL)
        self.assertEqual(log.changes['Withdrawal warnings acknowledged'][1], ' '.join(shown.messages()))


class ExplicitAcknowledgementTests(HarvestInsideTestCase):
    def test_there_is_no_ambient_acknowledgement(self):
        self.assertNotIn('farm.middleware.WithdrawalAcknowledgementMiddleware', settings.MIDDLEWARE)
        from ..health import withdrawal
        self.assertFalse(hasattr(withdrawal, 'acknowledging'))

    def test_a_box_posted_to_one_dialog_acknowledges_only_that_write(self):
        treatment = self.treat(self.medicine(days=7), 2, 2)
        with self.assertRaises(WithdrawalChanged) as caught:
            services.void_treatment(self.user, treatment, 'Wrong unit')
        # The box of the void, sent with a last-day change: not that write's acknowledgement.
        response = self.client.post(reverse('farm:treatment_last_day', args=[treatment.pk]), {
            'end_date': self.day(3).isoformat(), 'withdrawal_ack': caught.exception.change.fingerprint})
        self.assertNotEqual(response.status_code, 302)
        self.assertEqual(Treatment.objects.get().end_date, self.day(2))


class EarlierEndTests(HarvestInsideTestCase):
    def test_a_shorter_course_that_still_holds_the_fish_asks_with_the_old_and_new_end(self):
        bath = self.medicine(days=1)
        treatment = self.treat(bath, 3, -5)                  # held until 7 days ahead
        with self.assertRaises(WithdrawalChanged) as caught:
            services.change_last_day(self.user, treatment, self.day(-1))   # until 3 days ahead: still held
        [shorter] = caught.exception.change.released
        self.assertEqual((shorter.batch, shorter.until, shorter.until_after), (self.batch, self.day(-7), self.day(-3)))
        self.assertIn(stock_services.shown_date(self.day(-3)), caught.exception.change.messages()[0])

    def test_a_longer_course_asks_nothing_of_the_fish_held(self):
        treatment = self.treat(self.medicine(days=1), 3, -1)
        services.change_last_day(self.user, treatment, self.day(-5))
        self.assertFalse(WithdrawalAcknowledgement.objects.exists())


class GrownPastTheAcknowledgedEndTests(HarvestInsideTestCase):
    def test_a_withdrawal_grown_past_its_acknowledged_end_is_asked_again_and_not_called_acknowledged(self):
        bath = self.medicine(days=7)
        self.harvest(3)
        treatment = going_on(self.treat, bath, 5, 5)          # acknowledged until 3 days ahead
        with self.assertRaises(WithdrawalChanged) as caught:
            services.change_last_day(self.user, treatment, self.day(4))   # until 4 days ahead
        self.assertEqual([found.until for found in caught.exception.change.harvested], [self.day(-4)])
        # Grown behind the guard's back (a script): the sweep says the acknowledgement does not cover it.
        with gate.opened('test: a write behind the services'):
            Treatment.objects.filter(pk=treatment.pk).update(end_date=self.day(4))
        out = io.StringIO()
        call_command('check_withdrawal', stdout=out)
        self.assertIn(f'Not acknowledged (acknowledged for harvest from {self.day(-3).isoformat()}; now harvest '
                      f'from {self.day(-4).isoformat()}).', out.getvalue())


class DataLayerTests(HarvestInsideTestCase):
    """The withdrawal inputs refuse a change made outside the guard, whatever makes it."""

    def test_the_registry_names_every_withdrawal_input(self):
        self.assertEqual({model.__name__: fields for model, fields in gate.REGISTRY.items()}, {
            'Treatment': None, 'Treatment_units': None, 'FeedingRecord': None, 'WaterMeasurement': None,
            'MedicineWithdrawal': None, 'StockOperation': None, 'StockMovement': None, 'Feed': ('feed_type',),
            'Species': ('withdrawal_temperature_c',),
            'SamplingPoint': ('is_active', 'kind', 'unit', 'system', 'equipment')})
        self.assertEqual({model.__name__: set(rules) for model, rules in gate.CONDITIONAL.items()}, {
            'System': {'is_deleted'}, 'Tank': {'is_deleted', 'system'}, 'Species': {'is_deleted'},
            'SamplingPoint': {'is_deleted'}})

    def test_every_kind_of_write_outside_the_guard_is_refused(self):
        treatment = self.treat(self.medicine(days=7), 9, 9)
        sample = self.temperature(self.t1, 1, '8')
        feed = self.medicated()
        writes = [
            lambda: Treatment.objects.filter(pk=treatment.pk).update(end_date=self.day(8)),
            lambda: Treatment.objects.get(pk=treatment.pk).save(),
            lambda: treatment.units.add(self.t2),
            lambda: WaterMeasurement.objects.filter(pk=sample.pk).delete(),
            lambda: MedicineWithdrawal.objects.filter(medicine=treatment.medicine).update(days=1),
            lambda: MedicineWithdrawal.objects.bulk_create([MedicineWithdrawal(medicine=treatment.medicine,
                                                                               species=self.salmon, days=1)]),
            lambda: FeedingRecord.objects.filter(unit=self.t1).delete(),
            lambda: StockOperation.objects.filter(kind='input').update(date=self.day(9)),
            lambda: StockMovement.objects.filter(unit=self.t1).update(count_delta=1),
            lambda: Feed.objects.filter(pk=feed.pk).update(feed_type='grower'),
            lambda: Species.objects.filter(pk=self.salmon.pk).update(withdrawal_temperature_c=Decimal(40)),
            lambda: SamplingPoint.objects.filter(pk=point_of(self.t1).pk).update(is_active=False),
        ]
        for index, write in enumerate(writes):
            # A refused write spoils its transaction, as it should: each is tried in a savepoint of its own.
            with self.subTest(write=index), self.assertRaises(gate.UnguardedWithdrawalWrite), transaction.atomic():
                write()

    def test_other_fields_and_new_rows_of_the_reference_data_are_free(self):
        feed = self.medicated()
        Feed.objects.filter(pk=feed.pk).update(name='Medisinfor 2')
        Species.objects.filter(pk=self.salmon.pk).update(common_name='Salmon')
        SamplingPoint.objects.filter(pk=point_of(self.t1).pk).update(description='By the outlet')
        Feed.objects.create(name='Grower', code='GR-9', feed_type='grower')

    def medicated(self):
        return Feed.objects.create(name='Medisinfor', code='MED-1', feed_type='medicated')


class ReferenceDataPageTests(HarvestInsideTestCase):
    """The review's probes: a feed's type, a species' assumed temperature and a sampling point changed on their Setup
    pages are asked through the guard."""

    def setUp(self):
        super().setUp()
        from .helpers import role
        self.user.groups.add(role('Setup keeper', 'view_feed', 'change_feed', 'view_species', 'change_species',
                                  'view_samplingpoint', 'change_samplingpoint', 'view_supplier'))

    def edit(self, url_name, obj, **changes):
        url = reverse(url_name, args=[obj.pk])
        form = self.client.get(url).context['form']
        return url, edit_data(form, **changes)

    def assertAskedThenSaved(self, url, data):
        refused = self.client.post(url, data)
        self.assertEqual(refused.status_code, 422)
        change = refused.context['withdrawal_change']
        self.assertTrue(change.warnings)
        self.assertContains(refused, 'name="withdrawal_ack"', status_code=422)
        self.assertEqual(self.client.post(url, {**data, 'withdrawal_ack': change.fingerprint}).status_code, 302)
        self.assertTrue(WithdrawalAcknowledgement.objects.exists())

    def test_a_feed_made_not_medicated_while_it_holds_fish(self):
        feed = Feed.objects.create(name='Medisinfor', code='MED-1', feed_type='medicated')
        going_on(feeding_services.record_feeding, self.user, unit=self.t1, day=self.day(1), feed=feed,
                 amount_kg=Decimal('2'))
        self.assertTrue(self.held())
        url, data = self.edit('farm:feed_edit', feed, feed_type='grower')
        self.assertAskedThenSaved(url, data)
        self.assertEqual(Feed.objects.get(pk=feed.pk).feed_type, 'grower')

    def test_a_species_assumed_temperature_raised_while_it_holds_fish(self):
        self.treat(self.medicine(degree_days=100), 6, 6)     # no samples: the past days at the assumed temperature
        with gate.opened('test fixture'):
            Species.objects.filter(pk=self.salmon.pk).update(withdrawal_temperature_c=Decimal(1))
        self.salmon.refresh_from_db()
        url, data = self.edit('farm:species_edit', self.salmon, withdrawal_temperature_c='40')
        self.assertAskedThenSaved(url, data)

    def test_a_middle_point_made_inactive_that_brings_a_harvest_inside(self):
        bath = self.medicine(degree_days=55)
        for days_ago in (5, 4, 3):
            self.temperature(self.t1, days_ago, '20')
        self.treat(bath, 6, 6)
        self.harvest(1)
        point = point_of(self.t1)
        url, data = self.edit('farm:samplingpoint_edit', point)
        data.pop('is_active', None)                          # unticked
        self.assertAskedThenSaved(url, data)
        self.assertFalse(SamplingPoint.all_objects.get(pk=point.pk).is_active)


class LockTests(HarvestInsideTestCase):
    def test_a_batch_that_arrived_before_the_units_were_locked_is_locked_too(self):
        """The units are locked, then the batches in them are read again: one that arrived between the first read and
        the lock is locked too (cross-review 2, 7)."""
        b2 = self.stock(self.t1, count=100)
        real = stock_read.Presence.of_units
        calls = []

        def stale_first(unit_ids):
            calls.append(1)
            presence = real(unit_ids)
            if len(calls) == 1:                              # the first read misses B-2
                presence.batches = {unit: {each for each in batches if each != b2.pk}
                                    for unit, batches in presence.batches.items()}
            return presence

        with mock.patch.object(stock_read.Presence, 'of_units', side_effect=stale_first), \
                CaptureQueriesContext(connection) as queries:
            self.treat(self.medicine(days=1), 9, 9)
        locks = [query['sql'] for query in queries.captured_queries
                 if 'FOR UPDATE' in query['sql'] and '"batches"' in query['sql']]
        self.assertTrue(any(b2.pk.hex in sql for sql in locks), locks)


class RefusalTests(HarvestInsideTestCase):
    def test_the_refusal_crosses_a_process_boundary(self):
        """The parallel test runner and any worker pickle an exception: the refusal and what it found survive it."""
        import pickle
        treatment = self.treat(self.medicine(days=7), 2, 2)
        with self.assertRaises(WithdrawalChanged) as caught:
            services.void_treatment(self.user, treatment, 'Wrong unit')
        copied = pickle.loads(pickle.dumps(caught.exception))
        self.assertEqual((copied.message_dict, copied.change.fingerprint),
                         (caught.exception.message_dict, caught.exception.change.fingerprint))
