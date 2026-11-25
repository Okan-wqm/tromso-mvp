"""The independent security review of the confidentiality branch (F:\\dev\\balik-notes\\exp-access\\REVIEW.md), each
finding as a test: what the review found must stay closed.

F2 the database viewer's every table, a private experiment included; F3 the team is the lead's; F4 the unresolved old
courses as the person may see them; F5 the store's feed book the same for everyone; F6 a sealed tank's notifiable
disease still owed; F7 Oversee keeps the fish of a private experiment, never its science; F8 every read of the platform
admin logged, the change token, a results share, the search, the alarms and their fallback, the delete plan's words;
the lead's on-call number on the Oversee card."""
import uuid
from datetime import timedelta
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core import audit, database, sealing
from core.models import AccessEvent, AuditLog
from core.softdelete import plan_delete
from farm import withdrawal_gate
from farm.models import FeedingRecord, HealthEvent, Site, Tank, Treatment

from farm.tests.helpers import role, rows_data

from .. import read, services
from ..models import Experiment, ExperimentShare, Factor, Member
from . import world
from .test_pages import RESEARCHER


class ReviewCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        world.build_open(cls)
        world.build_sealed(cls)
        cls.keeper = world.person('keeper', *world.area_perms(exclude_apps=('reports',)), 'experiments.oversee_experiment')

    def seen(self, user, model, **lookup):
        with sealing.as_viewer(user):
            return set(model.objects.filter(**lookup).values_list('pk', flat=True))

    def private(self):
        Experiment.objects.filter(pk=self.experiment.pk).update(audience='private')

    def events(self, **lookup):
        return AccessEvent.objects.filter(entity_type='experiment', entity_id=str(self.experiment.pk), **lookup)


class DatabaseViewerTests(ReviewCase):
    def test_no_table_shows_a_private_experiment_to_the_platform_admin(self):
        self.private()
        AuditLog.objects.create(user=self.lead, user_name='lead', action='update', entity_type='experiment',
                                entity_id=str(self.experiment.pk), entity_label='XQZ diet trial', changes={})
        self.client.force_login(self.boss)
        for _label, tables in database.sections():
            for table in tables:
                with self.subTest(table=table.name):
                    response = self.client.get(reverse('core:database_table', args=[table.name]))
                    self.assertEqual(response.status_code, 200)
                    self.assertNotContains(response, 'XQZ')
                    self.assertNotContains(response, str(self.experiment.pk))


class TeamTests(ReviewCase):
    def post(self, user, rows):
        self.client.force_login(user)
        return self.client.post(reverse('experiments:experiment_team', args=[self.experiment.pk]),
                                rows_data('team', rows, record=self.experiment))

    def test_only_the_lead_changes_the_team(self):
        Member.objects.create(experiment=self.experiment, user=self.researcher, role='researcher')
        rows = [{'user': self.researcher.pk, 'role': 'lead'}]
        self.assertEqual(self.post(self.researcher, rows).status_code, 403)
        self.assertEqual(Member.objects.get(experiment=self.experiment, role='lead').user, self.lead)
        self.assertEqual(self.post(self.lead, [{'user': self.lead.pk, 'role': 'lead'}]).status_code, 302)

    def test_the_platform_admin_takes_over_a_leadless_experiment_logged(self):
        with self.assertRaises(CommandError):                       # it has a lead
            call_command('experiments_take_lead', self.experiment.code, '--as', 'root', '--reason', 'Lead left',
                         stdout=StringIO())
        Member.objects.filter(experiment=self.experiment).delete()
        with self.assertRaises(CommandError):                       # not the platform admin
            call_command('experiments_take_lead', self.experiment.code, '--as', 'researcher', '--reason', 'x',
                         stdout=StringIO())
        call_command('experiments_take_lead', self.experiment.code, '--as', 'root', '--reason', 'Lead left',
                     stdout=StringIO())
        self.assertEqual(Member.objects.get(experiment=self.experiment, role='lead').user, self.boss)
        entry = AuditLog.objects.filter(entity_id=str(self.experiment.pk)).latest('created_at')
        self.assertIn('taken over: Lead left', entry.changes['Team'][1])


class WithdrawalTests(ReviewCase):
    def test_the_unresolved_old_courses_are_the_persons_to_see(self):
        from unittest import mock
        from farm.health import withdrawal
        with withdrawal_gate.opened('test fixture: an old course without a rule'):
            Treatment.objects.filter(pk=self.treatment.pk).update(start_date=self.today - timedelta(days=4),
                                                                    end_date=self.today - timedelta(days=3))
        days = mock.patch.object(withdrawal, 'unknown_withdrawal_days', return_value=1)
        days.start()
        self.addCleanup(days.stop)
        with sealing.system('the test'):
            everything = {batch.pk for batch, _held in withdrawal.unresolved()}
        self.assertIn(self.sealed_batch.pk, everything)
        with sealing.as_viewer(self.researcher):
            shown = [withdrawal.unresolved_text(batch, held) for batch, held in withdrawal.unresolved()]
        self.assertNotIn('XQZ', ' '.join(shown))


class StoreTests(ReviewCase):
    def test_the_feed_book_is_the_same_for_everyone(self):
        from inventory import read as store
        books = {}
        for user in (self.boss, self.lead, self.researcher, self.hr):
            with sealing.as_viewer(user):
                books[user.username] = store._feeding([self.feed.pk])
        self.assertEqual(sum(books['root'][self.feed.pk].values()), 4)          # the open 2.5 kg and X's 1.5 kg
        self.assertTrue(all(book == books['root'] for book in books.values()))


class DueListTests(ReviewCase):
    def test_a_sealed_tanks_notifiable_disease_is_owed_whoever_looks(self):
        from farm.health import diseases
        from reports import due
        Site.objects.filter(pk=self.site.pk).update(reports_from=self.today - timedelta(days=30))
        HealthEvent.objects.filter(pk=self.event.pk).update(diagnosis=diseases.NOTIFIABLE[0], confirmation='suspected')
        with sealing.as_viewer(self.researcher):
            rows = due.due().rows
        self.assertIn(self.event.pk, {row.event.pk for row in rows if row.event is not None})


class OverseeTests(ReviewCase):
    def test_oversee_keeps_the_fish_of_a_private_experiment_never_its_science(self):
        self.private()
        self.assertTrue({tank.pk for tank in self.sealed_tanks} <= self.seen(self.keeper, Tank))
        self.assertIn(self.feeding.pk, self.seen(self.keeper, FeedingRecord))
        self.assertEqual(self.seen(self.keeper, Factor), set())
        self.assertEqual(self.seen(self.keeper, Experiment), set())

    def test_the_sharing_page_says_the_exception(self):
        self.client.force_login(self.lead)
        response = self.client.get(reverse('experiments:experiment_sharing', args=[self.experiment.pk]))
        self.assertContains(response, 'the people whose role holds Oversee')

    def test_the_card_has_the_leads_on_call_number_and_is_logged_against_the_experiment(self):
        Experiment.objects.filter(pk=self.experiment.pk).update(on_call_phone='+47 400 00 000')
        with sealing.as_viewer(self.keeper):
            chip = read.chips(self.sealed_tanks, self.keeper)[self.sealed_tanks[0].pk][0]
        self.assertIn('+47 400 00 000', chip.title)
        self.assertTrue(self.events(kind='oversee', user_name='keeper').exists())


class SupportReadTests(ReviewCase):
    def test_every_read_of_the_platform_admin_is_logged(self):
        AuditLog.objects.create(user=self.lead, user_name='lead', action='update', entity_type='experiment',
                                entity_id=str(self.experiment.pk), entity_label='XQZ diet trial', changes={})
        self.client.force_login(self.boss)
        for url in (reverse('experiments:experiment_list'), reverse('core:activity_log'),
                    reverse('core:database_table', args=['experiments']),
                    reverse('admin:experiments_experiment_changelist'),
                    reverse('admin:experiments_experiment_change', args=[self.experiment.pk])):
            with self.subTest(url=url):
                before = self.events(kind='support').count()
                self.assertEqual(self.client.get(url).status_code, 200)
                self.assertGreater(self.events(kind='support').count(), before)


class TokenTests(ReviewCase):
    def test_a_write_the_person_may_not_see_never_moves_their_token(self):
        with sealing.as_viewer(self.researcher):
            before = audit.revision()
        with sealing.as_viewer(self.lead):
            lead_before = audit.revision()
        audit.record(self.lead, AuditLog.Action.UPDATE, self.experiment, {'Notes': ['a', 'b']})
        with sealing.as_viewer(self.researcher):
            self.assertEqual(audit.revision(), before)
        with sealing.as_viewer(self.lead):
            self.assertNotEqual(audit.revision(), lead_before)


class ShareTests(ReviewCase):
    def give(self, part):
        return ExperimentShare.objects.create(experiment=self.experiment, user=self.researcher, part=part,
                                              reason='Review', valid_until=timezone.now() + timedelta(days=5))

    def test_a_results_share_reads_the_figures_the_team_reads(self):
        self.give('results')
        with sealing.as_viewer(self.lead):
            team = repr(read.overview(self.experiment, self.today))
        with sealing.as_viewer(self.researcher):
            grantee = repr(read.overview(self.experiment, self.today))
        self.assertEqual(team, grantee)

    def test_the_search_finds_by_the_hypothesis_only_who_may_read_the_design(self):
        self.give('water')
        self.client.force_login(self.researcher)
        url = reverse('experiments:experiment_list')
        self.assertContains(self.client.get(url, {'q': 'XQZ diet'}), 'XQZ diet trial')
        self.assertNotContains(self.client.get(url, {'q': 'more protein'}), 'XQZ diet trial')
        self.give('design')
        self.assertContains(self.client.get(url, {'q': 'more protein'}), 'XQZ diet trial')

    def test_the_list_counts_the_groups_and_replicates_only_for_who_reads_the_design(self):
        """L7: the list's counts are read through the design's sealed managers, never a join past them."""
        self.give('water')
        url = reverse('experiments:experiment_list')
        counts = {}
        for user in (self.researcher, self.lead):
            self.client.force_login(user)
            rows = {row.pk: row for row in self.client.get(url).context['objects']}
            counts[user.username] = (rows[self.experiment.pk].group_count, rows[self.experiment.pk].replicate_count)
        self.assertEqual(counts, {'researcher': (0, 0), 'lead': (1, 2)})


class ManyToManyAndKeyTests(ReviewCase):
    """L8: a treatment's units (a table Django makes) and the form keys (core.models.EntryKey, which name a record by
    its model's label) are hidden with the record they are about, from the platform admin too when it is private."""

    def test_a_private_treatments_units_and_a_hidden_records_form_key_are_left_out(self):
        from core.models import EntryKey
        self.private()
        EntryKey.note(uuid.uuid4(), self.treatment)
        through = Treatment.units.through
        with sealing.as_viewer(self.boss):
            units = set(sealing.narrow(through._base_manager.all()).values_list('treatment_id', flat=True))
            keys = set(sealing.narrow(EntryKey._base_manager.all()).values_list('entity_id', flat=True))
        self.assertNotIn(self.treatment.pk, units)
        self.assertNotIn(str(self.treatment.pk), keys)
        with sealing.as_viewer(self.lead):
            self.assertIn(self.treatment.pk, set(sealing.narrow(through._base_manager.all())
                                                 .values_list('treatment_id', flat=True)))


class AlarmTests(ReviewCase):
    def rule(self, **fields):
        from alarms.models import RecipientRule
        return RecipientRule.objects.create(level=0, created_by=self.boss, **fields)

    def recipients(self, alarm=None):
        from alarms import routing
        alarm = alarm or self.alarm
        return {user.username: rule for user, rule in routing.Router(timezone.now(), [alarm]).recipients(alarm, 0)}

    def unit_alarms(self):
        """A unit's value that could not be evaluated, and a unit read at its system with no point (alarms 0022): no
        point, no sensor event, the unit only in the subject's key."""
        from alarms import services
        tank, now = self.sealed_tanks[0], timezone.now()
        return services.raise_many([
            (f'system:unit:{tank.pk}:unit_unevaluated', {
                'at': now, 'severity': 'critical', 'summary': f'{tank.code}: the water could not be evaluated',
                'source': 'system', 'parameter': 'unit_unevaluated'}),
            (f'water:unit:{tank.pk}:oxygen:critical', {
                'at': now, 'severity': 'critical', 'summary': f'{tank.code}, from its system: O2 3.1 (critical)',
                'source': 'water_limit', 'parameter': 'oxygen_mg_l'})]).values()

    def sensor_alarm(self):
        """A sensor rule's alarm on X's oxygen channel, bound to X's tank's point (it has no point of its own)."""
        from alarms import sources
        from sensors.models import AlarmEvent, AlarmRule
        rule = AlarmRule.objects.create(channel=self.sealed_channel, kind='no_data', severity='critical')
        event = AlarmEvent.objects.create(rule=rule, channel_no=self.sealed_channel.channel_no, binding=self.binding,
                                          opened_at=timezone.now())
        return sources.mirror(event)

    def test_an_alarm_about_a_unit_with_no_point_is_sealed_with_its_unit(self):
        """Review L2, M1: a unit's own alarm with no point lies on the unit (alarms/place.py), so it does not exist
        for whoever may not see the unit, and its people are the unit's."""
        from alarms.models import Alarm
        made = {alarm.pk for alarm in self.unit_alarms()}
        self.assertEqual(self.seen(self.researcher, Alarm, pk__in=made), set())
        self.assertEqual(self.seen(self.lead, Alarm, pk__in=made), made)
        self.rule(user=self.researcher)
        for alarm in Alarm.objects.filter(pk__in=made):
            self.assertEqual(set(self.recipients(alarm)), {'lead', 'keeper'})

    def test_a_sensor_alarm_on_a_sealed_cell_reaches_the_keepers(self):
        """Review W4: a sensor rule's alarm has no point; its place is its channel's binding when it opened, so with
        nobody on the rules who may see it the keepers of the fish are told."""
        alarm = self.sensor_alarm()
        self.assertEqual(alarm.unit_id, self.sealed_tanks[0].pk)
        self.rule(user=self.researcher)
        found = self.recipients(alarm)
        self.assertEqual(set(found), {'lead', 'keeper'})

    def test_the_attention_snapshot_is_never_served_across_what_people_read(self):
        """Review L3, T2: the snapshot the strip and the overviews count is kept for a while (the cache ON here); a
        copy made for the lead is never served to an outsider, nor an outsider's to the lead, whoever comes first."""
        from django.core.cache import cache
        from django.test.utils import override_settings
        from alarms import read as alarms_read
        sealed = self.sealed_tanks[0].pk

        def units(user):
            with sealing.as_viewer(user):
                alarms, _rungs = alarms_read.snapshot()
            return {unit for _site, _severity, unit in alarms}
        with override_settings(ATTENTION_CACHE_SECONDS=15):
            for first, then in ((self.lead, self.researcher), (self.researcher, self.lead)):
                cache.clear()
                self.addCleanup(cache.clear)
                with self.subTest(first=first.username):
                    self.assertEqual(sealed in units(first), first == self.lead)
                    self.assertEqual(sealed in units(then), then == self.lead)

    def test_a_router_routes_only_the_alarms_it_was_made_for(self):
        """Review L1: a router reads which of its alarms are sealed when it is made; one asked about another alarm
        refuses, never routes it as unsealed."""
        from alarms import routing
        router = routing.Router(timezone.now(), [])
        with self.assertRaises(ValueError):
            router.recipients(self.alarm, 0)

    def test_a_snooze_reminder_reaches_only_who_may_see_the_alarm(self):
        """Review L1: the reminder at a snooze's end (alarms.engine._remind) goes through the same seal."""
        from alarms import engine
        from alarms.models import AlarmShelve, Notification, NotificationKind
        self.rule(user=self.researcher)
        self.rule(user=self.lead)
        now = timezone.now()
        shelve = AlarmShelve.objects.create(alarm=self.alarm, user=self.lead, shelved_at=now - timedelta(hours=2),
                                            until=now - timedelta(minutes=1), reason='Diver in the tank')
        engine._remind([self.alarm], now, engine.Summary(), {self.alarm.pk: shelve})
        told = set(Notification.objects.filter(alarm=self.alarm, kind=NotificationKind.RESUMED)
                   .values_list('recipient__username', flat=True))
        self.assertEqual(told, {'lead'})

    def test_a_sealed_cells_alarm_reaches_only_who_may_see_it(self):
        self.rule(user=self.researcher)
        self.rule(user=self.lead)
        self.assertEqual(set(self.recipients()), {'lead'})

    def test_with_nobody_on_the_rules_who_may_see_it_the_keepers_are_told(self):
        self.rule(user=self.researcher)
        found = self.recipients()
        self.assertEqual(set(found), {'lead', 'keeper'})
        self.assertTrue(all(rule is None for rule in found.values()))


class DeletePlanTests(ReviewCase):
    def test_the_plan_never_says_how_many_records_the_person_may_not_see(self):
        with sealing.as_viewer(self.staff):
            plan = plan_delete(self.hall)
        self.assertFalse(plan.can_delete)
        restricted = [str(blocker) for blocker in plan.blockers if 'may not see' in str(blocker)]
        self.assertEqual(len(restricted), 1)
        self.assertFalse(any(character.isdigit() for character in restricted[0]))


class ResearcherRoleTests(ReviewCase):
    def test_a_member_with_change_rights_is_not_the_lead(self):
        member = world.person('member', *[f'experiments.{code}' for code in RESEARCHER if 'experiment' in code])
        member.groups.add(role('Extra', 'view_experiment'))
        Member.objects.create(experiment=self.experiment, user=member, role='researcher')
        self.client.force_login(member)
        response = self.client.post(reverse('experiments:experiment_team', args=[self.experiment.pk]),
                                    rows_data('team', [{'user': member.pk, 'role': 'lead'}], record=self.experiment))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(services.is_lead(self.lead, self.experiment))


class VoidedParentTests(ReviewCase):
    def test_a_voided_open_harvest_keeps_its_record_for_whoever_has_work_hidden(self):
        """W1: a child sealed with its parent (`via`) is hidden when the parent is hidden, not when it is voided: the
        record of a voided harvest on an open tank stays readable to a person from whom X is hidden."""
        from decimal import Decimal
        from farm.handling import check
        from farm.models import HarvestRecord
        from farm.stock import services as stock_services
        day = self.today - timedelta(days=1)
        with withdrawal_gate.opened('test: an open harvest written and voided'):
            harvest = stock_services.record_harvest(
                self.boss, unit=self.open_tank, batch=self.open_batch, day=day, count=10,
                measured_weight_kg=Decimal('0.6'), facility=self.facility,
                handling_ack=check.assess('harvest', self.open_tank, day, self.open_batch).fingerprint)
            stock_services.void(self.boss, harvest, 'Typed on the wrong day', ack=True)
        self.assertTrue(type(harvest).all_objects.get(pk=harvest.pk).is_deleted)
        with sealing.as_viewer(self.researcher):
            self.assertTrue(HarvestRecord.all_objects.filter(operation=harvest.pk).exists())


class SealingStartsWithTheStartTests(ReviewCase):
    """W3, the coordinator's decision of 2026-11-25: a draft seals nothing; sealing starts when the experiment starts;
    days already passed are sealed only by a person who holds Oversee."""

    def test_a_draft_placed_on_a_tank_hides_nothing_of_it(self):
        from ..models import ExperimentGroup, Replicate, ReplicateUnit
        draft = Experiment.objects.create(code='E-DRAFT-1', name='Draft on the open tank', site=self.site,
                                          species=self.salmon, duration_days=30,
                                          starts_on=self.today - timedelta(days=10))
        group = ExperimentGroup.objects.create(experiment=draft, name='Only group')
        replicate = Replicate.objects.create(group=group, number=1)
        ReplicateUnit.objects.create(replicate=replicate, unit=self.open_tank, from_on=self.today - timedelta(days=10),
                                     until_on=self.today + timedelta(days=20))
        self.assertEqual(draft.status, 'draft')
        self.assertEqual(self.seen(self.researcher, Tank, pk=self.open_tank.pk), {self.open_tank.pk})
        self.assertEqual(len(self.seen(self.researcher, FeedingRecord, unit=self.open_tank)), 1)

    def test_sealing_days_already_passed_needs_oversee(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        Experiment.objects.filter(pk=self.experiment.pk).update(audience='open')
        self.assertLess(self.experiment.starts_on, self.today)
        with self.assertRaises(ValidationError):
            services.set_audience(self.lead, self.experiment, 'sealed')
        self.lead.user_permissions.add(Permission.objects.get(content_type__app_label='experiments',
                                                              codename='oversee_experiment'))
        lead = get_user_model().objects.get(pk=self.lead.pk)            # the rights read afresh
        self.assertEqual(services.set_audience(lead, self.experiment, 'sealed').audience, 'sealed')
