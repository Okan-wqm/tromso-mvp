"""A running experiment's tanks: one released, one replaced, each with its reason, the placement only ever shortened, the
diet's assignment row ended and written through the farm's own assignments, the figures bounded by the days; the farm's
`assignments.end`; and the two dialogs."""
from datetime import timedelta

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import IntegrityError, transaction
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import translation

from core.models import AuditLog, Profile
from farm.feeding import assignments
from farm.models import FeedingProtocol, ProtocolAssignment
from farm.stock import services as stock_services
from farm.tests.helpers import may_record
from farm.tests.test_protocols import ProtocolTestCase

from .. import read, services
from ..models import Experiment, ReplicateUnit
from . import D
from .test_overview import RanTrialCase
from .test_pages import person


def message_of(error):
    return error.exception.message_dict[NON_FIELD_ERRORS]


class AmendTestCase(RanTrialCase):
    def setUp(self):
        super().setUp()
        self.version = lambda: Experiment.objects.get(pk=self.trial.pk).version

    def placed(self, tank):
        return ReplicateUnit.objects.get(unit=tank, replicate__group__experiment=self.trial)

    def assignment(self, tank):
        return ProtocolAssignment.objects.get(unit=tank, notes__startswith=self.trial.code)

    def release(self, tank, last_day=None, reason='The pump failed', version=None, **kwargs):
        return services.release_unit(self.user, self.placed(tank), last_day or self.day(1), reason,
                                     self.version() if version is None else version)

    def replace(self, old, new, from_day=None, reason='The pump failed', version=None):
        return services.replace_unit(self.user, self.placed(old), new, from_day or self.today, reason,
                                     self.version() if version is None else version)

    def refused(self, call, *args, **kwargs):
        with self.assertRaises(ValidationError) as caught:
            call(*args, **kwargs)
        return message_of(caught)


class ReleaseTests(AmendTestCase):
    def test_a_tank_leaves_with_its_reason_its_diet_row_ends_with_it_and_the_change_is_logged(self):
        before = self.version()
        saved = self.release(self.tanks[1], reason='  The pump failed ')
        self.assertEqual(saved.version, before + 1)
        placement = self.placed(self.tanks[1])
        self.assertEqual((placement.until_on, placement.left_reason, placement.from_on, placement.version, placement.updated_by),
                         (self.day(1), 'The pump failed', self.first, 2, self.user))
        self.assertEqual(self.placed(self.tanks[0]).until_on, self.end)                # the others stay
        row = self.assignment(self.tanks[1])
        self.assertEqual((row.valid_until, row.valid_from, row.version, row.protocol), (self.day(1), self.first, 2,
                                                                                         self.low))
        entry = AuditLog.objects.filter(entity_id=str(self.trial.pk), changes__has_key='Reason it left').get()
        self.assertEqual(entry.changes['Reason it left'], [None, 'T-02: The pump failed'])
        self.assertIn(f'Control R2: T-02 ({self.first.isoformat()} to {self.end.isoformat()})', entry.changes['Places'][0])
        self.assertIn(f'Control R2: T-02 ({self.first.isoformat()} to {self.day(1).isoformat()})',
                      entry.changes['Places'][1])
        ended = AuditLog.objects.get(entity_type='protocol assignment', action='update', entity_id=str(row.pk))
        self.assertEqual(ended.changes, {'Until': [self.end.isoformat(), self.day(1).isoformat()]})

    def test_the_figures_of_what_the_tank_gave_stay_bounded_by_its_last_day(self):
        stock_services.record_weighing(self.user, unit=self.tanks[1], batch=self.batches[1], day=self.day(1),
                                       avg_weight_g=D(80))
        self.release(self.tanks[1], last_day=self.day(1))
        row = self.row(2)
        self.assertEqual([cell.last for cell in row.cells], [self.day(1)])
        self.assertEqual((row.conversion.feed_kg, row.conversion.gain_kg), (26, 30))      # to the weighing of its last day

    def test_what_may_not_be_released_and_nothing_is_written(self):
        cases = [
            (dict(reason=' '), ['Say why: a tank that leaves, or is replaced, is registered with its reason.']),
            (dict(reason='x' * 501), ['The reason is too long.']),
            (dict(last_day=self.first - timedelta(days=1)), [f'The last day comes on or after the first day '
                                                              f'({self.first.isoformat()}).']),
            (dict(last_day=self.end), [f'The tank is booked until {self.end.isoformat()} already: a placement is only '
                                       'ever shortened.']),
            (dict(last_day=self.end + timedelta(days=3)), [f'The tank is booked until {self.end.isoformat()} already: a '
                                                           'placement is only ever shortened.']),
            (dict(last_day=self.day(2)), ['The days before yesterday keep what happened in them: a tank leaves '
                                          'yesterday at the earliest.']),
            (dict(version=99), ['Someone else changed this experiment while you were editing it. The page now shows '
                                'their version; make your changes again.']),
        ]
        for fields, messages in cases:
            with self.subTest(messages=messages):
                self.assertEqual(self.refused(self.release, self.tanks[0], **fields), messages)
        self.assertEqual((self.placed(self.tanks[0]).until_on, self.placed(self.tanks[0]).left_reason),
                         (self.end, ''))
        self.assertEqual(self.assignment(self.tanks[0]).valid_until, self.end)

    def test_only_a_running_experiment_releases_a_tank_and_only_its_own_placements(self):
        other = self.experiment('Other', starts_on=self.today)                        # a draft: nothing to release yet
        foreign = self.placement(self.replicate(self.group(other, 'X'), 1), self.tanks[6])
        self.assertEqual(self.refused(services.release_unit, self.user, foreign, self.today, 'x', other.version),
                         ['The experiment is not running: only a running experiment has tanks to release or '
                          'replace.'])
        Experiment.objects.filter(pk=self.trial.pk).update(status='closed')
        self.assertEqual(self.refused(self.release, self.tanks[0]),
                         ['The experiment is not running: only a running experiment has tanks to release or '
                          'replace.'])

    def test_a_group_without_a_diet_releases_its_tank_and_touches_no_assignment(self):
        other = self.experiment('No diet', starts_on=self.first)
        self.member(other, self.user, 'lead')
        other.hypothesis, other.primary_endpoint = 'Temperature', 'survival'
        other.save()
        self.save([services.FactorRow('Temperature', 'other', '°C')],
                  [self.group_row('Cold', 'control', 1, [services.Cell(label='12')])], trial=other)
        other.refresh_from_db()
        slot = design_slot(other)
        self.stock(self.tanks[6], count=1000, weight='50', days_ago=20)
        services.save_places(self.user, other, [services.Place(slot, [self.tanks[6]])], other.version, 'by hand')
        self.start(trial=other)
        count = ProtocolAssignment.objects.count()
        placement = ReplicateUnit.objects.get(replicate=slot)
        services.release_unit(self.user, placement, self.day(1), 'The pump failed',
                              Experiment.objects.get(pk=other.pk).version)
        self.assertEqual((ReplicateUnit.objects.get(pk=placement.pk).until_on, ProtocolAssignment.objects.count()),
                         (self.day(1), count))

    def test_the_database_never_lets_the_released_placement_grow_back(self):
        self.release(self.tanks[1])
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReplicateUnit.objects.filter(pk=self.placed(self.tanks[1]).pk).update(until_on=self.end)


class ReplaceTests(AmendTestCase):
    def test_a_tank_is_replaced_in_the_same_replicate_with_its_diet_and_the_reason(self):
        saved = self.replace(self.tanks[0], self.tanks[4])
        old, new = self.placed(self.tanks[0]), self.placed(self.tanks[4])
        self.assertEqual((old.until_on, old.left_reason, old.replicate), (self.day(1), 'The pump failed',
                                                                           new.replicate))
        self.assertEqual((new.from_on, new.until_on, new.left_reason, new.replicate.number, new.created_by),
                         (self.today, self.end, '', 1, self.user))
        ended = self.assignment(self.tanks[0])
        fresh = self.assignment(self.tanks[4])
        self.assertEqual((ended.valid_until, fresh.protocol, fresh.valid_from, fresh.valid_until, fresh.created_by),
                         (self.day(1), self.low, self.today, self.end, self.user))
        self.assertEqual(fresh.notes, f'{self.trial.code} · Control')
        self.assertEqual(saved.version, self.version())
        entry = AuditLog.objects.filter(entity_id=str(self.trial.pk), changes__has_key='Reason it left').get()
        self.assertEqual(entry.changes['Reason it left'], [None, 'T-01: The pump failed'])
        self.assertIn('Control R1: T-01', entry.changes['Places'][0])
        self.assertIn(f'Control R1: T-01 ({self.first.isoformat()} to {self.day(1).isoformat()}), T-05 ('
                      f'{self.today.isoformat()} to {self.end.isoformat()})', entry.changes['Places'][1])
        self.assertEqual(AuditLog.objects.filter(entity_type='protocol assignment', action='create',
                                                 entity_id=str(fresh.pk)).count(), 1)

    def test_the_replicate_keeps_its_number_and_the_overview_says_where_the_conversion_has_a_gap(self):
        self.stock(self.tanks[4], count=800, weight='60', days_ago=0)
        self.replace(self.tanks[0], self.tanks[4])
        row = self.row()
        self.assertEqual([cell.unit.code for cell in row.cells], ['T-01', 'T-05'])
        self.assertEqual(row.replicate.number, 1)
        self.assertEqual(row.gap, [])                          # T-01 had no weighing at its last day: no window at all
        self.assertIsNone(row.conversion.biological)
        stock_services.record_weighing(self.user, unit=self.tanks[0], batch=self.batches[0], day=self.day(1),
                                       avg_weight_g=D(75))
        row = self.row()
        self.assertEqual(row.gap, ['T-05'])                    # now T-05 is the one with no weighing at the move
        self.assertEqual(row.conversion.feed_kg, 26)

    def test_what_may_not_be_replaced_and_nothing_is_written(self):
        other = self.experiment('Other', starts_on=self.today)
        self.placement(self.replicate(self.group(other, 'X'), 1), self.tanks[5])          # a draft reserves its tank
        ProtocolAssignment.objects.create(protocol=self.high, unit=self.tanks[6], valid_from=self.day(2))
        ProtocolAssignment.objects.create(protocol=self.high, unit=self.tanks[7], batch=self.batches[2],
                                          valid_from=self.day(2))
        cases = [
            (dict(new=self.tanks[0]), ['The new tank is the one that leaves.']),
            (dict(new=self.p1), ['P-01 is not on the site of the experiment (Bergen).']),
            (dict(new=self.tanks[1]), [f'T-02 is booked by another experiment from {self.first.isoformat()} to '
                                       f'{self.end.isoformat()}.']),
            (dict(new=self.tanks[5]), [f'T-06 is booked by another experiment from {self.today.isoformat()} to '
                                       f'{(self.today + timedelta(days=56)).isoformat()}.']),
            (dict(new=self.tanks[4], from_day=self.day(1)), ['The new tank comes in today at the earliest.']),
            (dict(new=self.tanks[4], from_day=self.end + timedelta(days=1)),
             [f'The new tank comes in on or before the last day of the placement ({self.end.isoformat()}).']),
            (dict(new=self.tanks[4], reason=''), ['Say why: a tank that leaves, or is replaced, is registered with its '
                                                  'reason.']),
            (dict(new=self.tanks[4], version=99), ['Someone else changed this experiment while you were editing it. The '
                                                   'page now shows their version; make your changes again.']),
        ]
        for fields, messages in cases:
            with self.subTest(messages=messages):
                fields = {'old': self.tanks[0], **fields}
                self.assertEqual(self.refused(self.replace, fields.pop('old'), fields.pop('new'), **fields), messages)
        found = self.refused(self.replace, self.tanks[0], self.tanks[6])
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].startswith('T-07 already has the feeding protocol High protein assigned ('))
        found = self.refused(self.replace, self.tanks[0], self.tanks[7])
        self.assertTrue(found[0].startswith(f'T-08 feeds batch {self.batches[2].code} by High protein ('))
        self.assertEqual((self.placed(self.tanks[0]).until_on, ReplicateUnit.objects.filter(
            replicate__group__experiment=self.trial).count()), (self.end, 4))
        self.assertEqual(self.assignment(self.tanks[0]).valid_until, self.end)

    def test_a_replacement_may_be_replaced_again_but_not_on_or_before_the_day_it_came_in(self):
        self.replace(self.tanks[0], self.tanks[4], from_day=self.today)
        later = self.today + timedelta(days=3)
        services.replace_unit(self.user, self.placed(self.tanks[4]), self.tanks[5], later, 'Again',
                              self.version())
        self.assertEqual([(cell.unit.code, cell.first, cell.last) for cell in read.cells(self.trial)
                          if cell.replicate.number == 1 and cell.group.name == 'Control'],
                         [('T-01', self.first, self.day(1)), ('T-05', self.today, later - timedelta(days=1)),
                          ('T-06', later, self.end)])
        self.assertEqual(self.refused(services.replace_unit, self.user, self.placed(self.tanks[5]), self.tanks[6],
                                      later, 'x', self.version()),
                         [f'The new tank comes in after the day the placement began ({later.isoformat()}).'])

    def test_a_protocol_retired_since_is_said_by_the_assignment_rows_and_nothing_is_written(self):
        FeedingProtocol.objects.filter(pk=self.low.pk).update(status='retired')
        found = self.refused(self.replace, self.tanks[0], self.tanks[4])
        self.assertEqual(found, ['T-05: Only an active protocol can be assigned; this one is retired.'])
        self.assertEqual(self.placed(self.tanks[0]).until_on, self.end)


class EndAssignmentTests(ProtocolTestCase):
    """farm/feeding/assignments.end, the row the experiment ends, with the farm's own rule for a row that has started."""

    def setUp(self):
        super().setUp()
        self.protocol = self.make_protocol()

    def end(self, row, day):
        return assignments.end(self.user, row, day)

    def refused(self, row, day):
        with self.assertRaises(ValidationError) as caught:
            self.end(row, day)
        return caught.exception.message_dict['valid_until']

    def test_a_row_is_ended_logged_as_the_dialog_logs_an_edit_and_counted(self):
        row = self.assign(self.protocol, unit=self.t1, days_ago=5)
        ended = self.end(row, self.day(1))
        self.assertEqual((ended.valid_until, ended.version, ended.updated_by), (self.day(1), 2, self.user))
        entry = AuditLog.objects.get(entity_type='protocol assignment', action='update')
        self.assertEqual(entry.changes, {'Until': [None, self.day(1).isoformat()]})
        self.assertEqual(self.end(row, self.day(1)).version, 3)                    # the same day again: counted, not logged
        self.assertEqual(AuditLog.objects.filter(entity_type='protocol assignment', action='update').count(), 1)

    def test_what_a_started_row_may_not_be_ended_to(self):
        row = self.assign(self.protocol, unit=self.t1, days_ago=5, until=self.day(2))
        self.assertEqual(self.refused(row, self.day(6)), ['The last day comes on or after the first day.'])
        self.assertEqual(self.refused(row, self.day(1)),
                         [f'The row ends on {self.day(2).isoformat()} already: it is only ever shortened.'])
        open_row = self.assign(self.protocol, unit=self.t2, days_ago=5)
        self.assertEqual(self.refused(open_row, self.day(3)),
                         ['The days before yesterday keep their protocol: the last day is yesterday at the earliest.'])
        gone = self.assign(self.protocol, unit=self.t1, days_ago=-3)
        gone.soft_delete(self.user)
        self.assertEqual(self.refused(gone, self.today + timedelta(days=5)), ['This assignment was deleted meanwhile.'])

    def test_a_row_that_has_not_started_may_end_any_day_from_its_first(self):
        later = self.assign(self.protocol, unit=self.t1, days_ago=-10)
        self.assertEqual(self.end(later, self.today + timedelta(days=11)).valid_until, self.today + timedelta(days=11))


class AmendPageTests(AmendTestCase):
    def setUp(self):
        super().setUp()
        self.data_url = reverse('experiments:experiment_detail', args=[self.trial.pk]) + '?tab=data'
        self.release_url = reverse('experiments:experiment_release', args=[self.trial.pk, self.placed(self.tanks[1]).pk])
        self.replace_url = reverse('experiments:experiment_replace', args=[self.trial.pk, self.placed(self.tanks[1]).pk])

    def test_the_data_tab_offers_release_and_replace_for_a_running_experiment_to_those_who_may(self):
        page = self.client.get(self.data_url)
        self.assertContains(page, f'href="{self.release_url}"')
        self.assertContains(page, f'href="{self.replace_url}"')
        self.client.force_login(person('reader', 'view_experiment'))
        self.assertNotContains(self.client.get(self.data_url), 'experiment_release')
        self.assertNotContains(self.client.get(self.data_url), self.release_url)
        self.client.force_login(self.user)
        self.release(self.tanks[1])
        page = self.client.get(self.data_url)
        self.assertNotContains(page, f'href="{self.release_url}"')            # it has left: nothing more to do to it

    def test_the_dialogs_show_the_tank_and_the_days_and_ask_for_the_reason(self):
        page = self.client.get(self.release_url, headers={'X-Modal': '1'})
        self.assertContains(page, 'T-02 is in Control R2 from')
        self.assertEqual(page.context['form']['last_day'].value(), self.today)
        self.assertContains(page, 'name="reason"')
        replace = self.client.get(self.replace_url, headers={'X-Modal': '1'})
        self.assertEqual([tank.code for tank in replace.context['form'].fields['new_unit'].queryset][:3],
                         ['T-01', 'T-03', 'T-04'])                            # the one that leaves is not offered
        self.assertEqual(replace.context['form']['from_day'].value(), self.today)

    def test_a_release_and_a_replacement_through_the_dialogs(self):
        version = Experiment.objects.get(pk=self.trial.pk).version
        response = self.client.post(self.release_url, {'version': version, 'last_day': self.day(1).isoformat(),
                                                       'reason': 'Leak'}, headers={'X-Modal': '1'})
        self.assertEqual((response.status_code, response['X-Modal-Redirect']), (204, self.data_url))
        self.assertEqual(self.placed(self.tanks[1]).until_on, self.day(1))
        mine = self.placed(self.tanks[0])
        replace = reverse('experiments:experiment_replace', args=[self.trial.pk, mine.pk])
        version = Experiment.objects.get(pk=self.trial.pk).version
        response = self.client.post(replace, {'version': version, 'new_unit': str(self.tanks[4].pk),
                                              'from_day': self.today.isoformat(), 'reason': 'Pump'})
        self.assertRedirects(response, self.data_url, fetch_redirect_response=False)
        self.assertEqual(self.placed(self.tanks[4]).replicate, mine.replicate)

    def test_what_is_wrong_is_said_in_the_dialog_with_a_422_and_nothing_is_written(self):
        version = Experiment.objects.get(pk=self.trial.pk).version
        response = self.client.post(self.release_url, {'version': version, 'last_day': self.end.isoformat(),
                                                       'reason': 'Leak'})
        self.assertContains(response, 'a placement is only ever shortened', status_code=422)
        response = self.client.post(self.release_url, {'version': version, 'last_day': '', 'reason': ''})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(sorted(response.context['form'].errors), ['last_day', 'reason'])
        response = self.client.post(self.replace_url, {'version': version, 'new_unit': str(self.tanks[2].pk),
                                                       'from_day': self.today.isoformat(), 'reason': 'x'})
        self.assertContains(response, 'T-03 is booked by another experiment from', status_code=422)
        self.assertEqual(self.placed(self.tanks[1]).until_on, self.end)

    def test_the_dialogs_speak_each_language(self):
        self.addCleanup(translation.deactivate)
        for language, words in {'tr': ('Bir tankı serbest bırak', 'Ayrılma gerekçesi', 'Bir tankı değiştir'),
                                'nb': ('Frigi et kar', 'Begrunnelse for at det gikk ut', 'Bytt ut et kar')}.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            release = self.client.get(self.release_url)
            replace = self.client.get(self.replace_url)
            self.assertContains(release, words[0], msg_prefix=language)
            self.assertContains(release, words[1], msg_prefix=language)
            self.assertContains(replace, words[2], msg_prefix=language)
            for page in (release, replace, self.client.get(self.data_url)):
                self.assertNotIn('%(', page.content.decode())

    def test_who_may_amend_and_a_placement_of_another_experiment_is_not_found(self):
        self.client.force_login(person('reader', 'view_experiment'))
        self.assertEqual(self.client.get(self.release_url).status_code, 403)
        self.assertEqual(self.client.post(self.replace_url, {}).status_code, 403)
        self.client.force_login(self.user)
        other = self.experiment('Other')
        wrong = reverse('experiments:experiment_release', args=[other.pk, self.placed(self.tanks[1]).pk])
        self.assertEqual(self.client.get(wrong).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(self.release_url).status_code, 302)


def design_slot(trial):
    from ..models import Replicate
    return Replicate.objects.get(group__experiment=trial)


class ReleaseRaceTests(TransactionTestCase):
    """Two people release two different tanks of one running experiment with the same form: the experiment's lock makes them take
    turns, so the second finds the version moved and is refused, and no change is lost."""

    serialized_rollback = True

    def setUp(self):
        from django.contrib.auth import get_user_model
        from farm.models import ProductionDepartment, Site
        from farm.stock import services as stock_services
        from farm.tests.helpers import make_species
        from farm.tests.test_stock import make_unit
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'x')
        may_record(self.user, 'add_experiment', 'change_experiment')  # the services ask who may (L-6)
        site = Site.objects.create(name='Bergen', code='BG')
        hall = ProductionDepartment.objects.create(site=site, name='Hall A', code='HA')
        self.tanks = [make_unit(f'T-0{n}', hall) for n in (1, 2)]
        self.today = stock_services.local_today(self.tanks[0])
        first = self.today - timedelta(days=3)
        self.trial = Experiment.objects.create(code='E-2026-001', name='One', site=site, species=make_species(),
                                               duration_days=56, starts_on=first)
        group = self.trial.groups.create(name='A', role='control')
        for number, tank in enumerate(self.tanks, start=1):
            group.replicates.create(number=number).placements.create(unit=tank, from_on=first,
                                                                     until_on=first + timedelta(days=56))
        Experiment.objects.filter(pk=self.trial.pk).update(
            status='running', hypothesis='h', primary_endpoint='bfcr', allocation_method='manual', allocation_note='x')
        self.trial.refresh_from_db()

    def test_two_releases_with_one_version_one_wins_and_nothing_is_lost(self):
        import threading
        from django.db import connection
        results, gate = [], threading.Barrier(2)
        placements = list(ReplicateUnit.objects.order_by('unit__code'))

        def release(placement):
            gate.wait()
            try:
                services.release_unit(self.user, placement, self.today - timedelta(days=1), 'Pump', self.trial.version)
                results.append('ok')
            except ValidationError as error:
                results.append(error.messages[0])
            finally:
                connection.close()

        threads = [threading.Thread(target=release, args=(placement,)) for placement in placements]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(result == 'ok' for result in results), [False, True])
        self.assertIn('Someone else changed this experiment', [r for r in results if r != 'ok'][0])
        self.assertEqual((Experiment.objects.get().version, ReplicateUnit.objects.exclude(left_reason='').count()),
                         (self.trial.version + 1, 1))


class CopyRaceTests(TransactionTestCase):
    """One copy form sent twice at once makes one copy (cross review of the merge, finding 2): the source is locked
    before the form's key is looked up, as every write path takes its locks first, so the second sending waits for the
    first and finds its copy instead of failing on the key."""

    serialized_rollback = True

    def setUp(self):
        from django.contrib.auth import get_user_model
        from farm.models import Site
        from farm.tests.helpers import make_species
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'x')
        may_record(self.user, 'add_experiment', 'change_experiment')  # the services ask who may (L-6)
        self.trial = Experiment.objects.create(code='E-2026-001', name='One', site=Site.objects.create(name='Bergen',
                                                                                                      code='BG'),
                                               species=make_species(), duration_days=56)

    def test_two_sendings_at_once_make_one_copy(self):
        import threading
        import time
        import uuid
        from unittest import mock

        from django.db import connection

        from core import codes
        token, results, gate = uuid.uuid4(), [], threading.Barrier(2)
        numbered = codes.next_code

        def slow_number(*args, **kwargs):
            time.sleep(0.5)                  # both sendings are past their first look before either has a copy
            return numbered(*args, **kwargs)

        def send():
            gate.wait()
            try:
                results.append(services.copy(self.user, self.trial, 'Repeat', token=token).pk)
            except Exception as error:      # noqa: BLE001 - the outcome is what the test is about
                results.append(f'{type(error).__name__}: {str(error)[:80]}')
            finally:
                connection.close()

        with mock.patch.object(services, 'next_code', slow_number):
            threads = [threading.Thread(target=send) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(30)
        self.assertEqual(Experiment.objects.filter(copied_from=self.trial).count(), 1)
        self.assertEqual(len(set(results)), 1, results)
