"""Harvest and handling: the handling check (fasting, and the medicine withdrawal asked before a harvest only, the
acknowledgement and the critical log entry), the harvest's record, the Harvested list with the book against the scale, the plans and
the fasts they ask for, and every new tab created, read, edited and deleted through its pages, each checked
against the stored rows."""
import uuid
from datetime import datetime, time as clock, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import translation

from core import access, database, navigation, softdelete
from core.models import AuditLog, Profile

from ..handling import check, fasting, withdrawal
from ..handling.withdrawal import WithdrawalBlock
from ..models import (
    HandlingAcknowledgement, HandlingPlanItem, HandlingRule, HarvestRecord, ProductionPlan, SlaughterFacility, Species,
    StockMovement, StockOperation, Supplier, Tank, WaterMeasurement,
)
from ..models.site import zone_of
from ..stock import integrity, services
from .helpers import WINDOW_WAY_OUT, correction_window, make_facility, point_of, role
from .test_feeding import FeedingTestCase
from .test_protocols import ProtocolTestCase
from farm import withdrawal_gate

HARVEST_KEEPER = ('view_harvestrecord', 'view_handlingplanitem', 'add_handlingplanitem', 'change_handlingplanitem',
                  'delete_handlingplanitem', 'view_productionplan', 'add_productionplan', 'change_productionplan',
                  'delete_productionplan', 'view_slaughterfacility', 'add_slaughterfacility',
                  'change_slaughterfacility', 'delete_slaughterfacility', 'view_handlingrule', 'add_handlingrule',
                  'change_handlingrule', 'delete_handlingrule', 'view_supplier', 'delete_supplier')
HOURS = Decimal('0.1')


def no_provider():
    return mock.patch.object(withdrawal, '_providers', [])


def provider(*blocks):
    """A fake health provider: these blocks for any unit and day."""
    return mock.patch.object(withdrawal, '_providers',
                             [lambda units, day: {unit.pk: list(blocks) for unit in units}])


class HarvestTestCase(FeedingTestCase):
    """10,000 salmon of 50 g in T-01 (500 kg), stocked 20 days ago; the starting rules of migration 0017."""

    def setUp(self):
        super().setUp()
        self.user.groups.add(role('Harvest keeper', *HARVEST_KEEPER))
        self.facility = make_facility()
        self.boat = Supplier.objects.create(name='Brønnbåt AS', code='BB', supplies=['transport'])
        patcher = no_provider()
        patcher.start()
        self.addCleanup(patcher.stop)

    def fed(self, days_ago, at=None, unit=None):
        return self.record(days_ago=days_ago, unit=unit, time=at)

    def harvest(self, count=10000, kilos='520', days_ago=0, **fields):
        return services.record_harvest(self.user, unit=fields.pop('unit', self.t1), batch=fields.pop('batch', self.batch),
                                       day=self.day(days_ago), count=count, measured_weight_kg=Decimal(kilos),
                                       facility=fields.pop('facility', self.facility), **fields)

    def assess(self, kind='harvest', days_ago=0, unit=None, batch=None):
        return check.assess(kind, unit or self.t1, self.day(days_ago), batch)

    def rule(self, kind, hours, species=None):
        HandlingRule.objects.filter(kind=kind, species=species).update(min_fasting_hours=hours)
        return HandlingRule.objects.update_or_create(kind=kind, species=species, is_deleted=False,
                                                     defaults={'min_fasting_hours': hours})[0]


# ---- the handling check ---------------------------------------------------------------------------------
class FastingTests(HarvestTestCase):
    def test_the_starting_rules_are_written_with_their_sources(self):
        self.assertEqual(sorted(HandlingRule.objects.filter(species__isnull=True).values_list('kind', 'min_fasting_hours')),
                         [('grading', 24), ('harvest', 72), ('transport', 24), ('treatment', 24)])
        for rule in HandlingRule.objects.all():
            self.assertTrue(rule.note.startswith('Starting value: check it with your veterinarian.'), rule.kind)

    def test_hours_from_a_feeding_with_its_time_to_the_start_of_the_day(self):
        self.fed(1, at=clock(18, 0))
        result = self.assess()
        [warning] = result.warnings
        self.assertEqual((warning.warning, warning.fasted_hours, warning.required_hours, warning.rule.kind),
                         ('fasting', Decimal('6.0'), 72, 'harvest'))
        # One line says it (M-05): the warning, with the feeding's own time; the notes do not repeat the feeding.
        self.assertEqual(warning.message(), f'Last fed {services.shown_date(self.day(1))} 18:00 in T-01, 6.0 h before '
                                            f'{services.shown_date(self.today)}: the harvest rule asks for 72 h.')
        self.assertFalse([note for note in result.notes if 'Last fed' in note])

    def test_a_feeding_without_a_time_counts_from_the_end_of_its_day(self):
        self.fed(3)
        result = self.assess()
        self.assertEqual(result.warnings[0].fasted_hours, Decimal('48.0'))
        self.assertIn(f'Last fed {services.shown_date(self.day(3))} (no time recorded: counted from the end of the '
                      'day) in T-01, 48.0 h before', result.warnings[0].message())
        self.assertEqual(self.assess('transport').warnings, [])            # 48 h against the transport rule's 24

    def test_a_feeding_on_the_day_itself_gives_no_fast(self):
        self.fed(0, at=clock(6, 0))
        self.assertEqual(self.assess('transport').warnings[0].fasted_hours, 0)

    def test_no_feeding_and_no_rule_are_said_not_warned(self):
        result = self.assess()
        self.assertEqual(result.warnings, [])
        self.assertIn(f'No feeding of these fish is recorded in the 31 days before {services.shown_date(self.today)}: '
                      'the fast is not checked.', result.notes)
        HandlingRule.objects.filter(kind='harvest').delete()
        self.fed(1, at=clock(18, 0))
        result = self.assess()
        self.assertEqual(result.warnings, [])
        self.assertIn('No handling rule for harvest: the fast is not checked (Reference data › Handling rules).',
                      result.notes)

    def test_a_grading_takes_the_longer_of_the_grading_and_the_transport_rule(self):
        self.fed(2)                                                          # 24 h before today
        self.rule('grading', 20)
        self.rule('transport', 30)
        [warning] = self.assess('grading').warnings
        self.assertEqual((warning.required_hours, warning.rule.kind), (30, 'transport'))
        self.rule('transport', 10)
        self.assertEqual(self.assess('grading').warnings, [])               # 24 h ≥ 20 h of the grading rule
        self.rule('grading', 36)
        self.assertEqual(self.assess('grading').warnings[0].rule.kind, 'grading')

    def test_a_species_rule_wins_over_the_rule_for_every_species(self):
        self.fed(4)                                                          # 72 h before today
        self.assertEqual(self.assess().warnings, [])
        own = self.rule('harvest', 96, species=self.salmon)
        [warning] = self.assess().warnings
        self.assertEqual((warning.rule, warning.required_hours), (own, 96))
        trout = self.stock(self.t2, count=10000, species=self.trout)
        self.fed(4, unit=self.t2)
        self.assertEqual(self.assess(unit=self.t2, batch=trout).warnings, [])    # trout: the general 72 h

    def test_the_fish_are_followed_into_the_unit_they_were_moved_to(self):
        self.fed(1, at=clock(20, 0))                                         # fed in T-01 last night
        services.record_transfer(self.user, source=self.t1, batch=self.batch, day=self.today,
                                 legs=[(self.t2, 10000)], reason='density',
                                 handling_ack=self.assess('transport').fingerprint)
        warning = self.assess(unit=self.t2, batch=self.batch).warnings[0]
        self.assertEqual(warning.fasted_hours, Decimal('4.0'))               # T-02's own records know nothing

    def test_a_treatment_checks_the_fast_and_no_withdrawal(self):
        block = WithdrawalBlock(self.batch, self.day(-10), False, '', None)
        self.fed(1, at=clock(12, 0))
        with provider(block):
            result = self.assess('treatment')
        self.assertEqual([warning.warning for warning in result.warnings], ['fasting'])


class WithdrawalTests(HarvestTestCase):
    def test_with_no_provider_it_is_not_checked_and_said(self):
        result = self.assess()
        self.assertIsNone(withdrawal.blocks(self.t1, self.today))
        self.assertIn('Medicine withdrawal not checked: the health records are not in yet.', result.notes)
        self.assertEqual(result.warnings, [])

    def test_a_providers_blocks_in_force_are_warnings_and_clear_ones_are_not(self):
        until = self.day(-14)
        held = WithdrawalBlock(self.batch, until, False, 'Treated with Slice until 20 Oct.', None)
        about = WithdrawalBlock(self.batch, until, True, '', None)
        unknown = WithdrawalBlock(self.batch, None, False, 'No temperature recorded.', None)
        clear = WithdrawalBlock(self.batch, self.today, False, '', None)
        # Which fish are in the unit is the provider's to say: the check warns of every block it gives for the unit
        # that is in force, of whichever batch (test_withdrawal_shared_unit.py).
        with provider(held, about, unknown, clear):
            messages = self.assess().messages()
        self.assertEqual(messages, [
            f'Not suitable for harvest — medicine withdrawal of {self.batch.code}: harvest from '
            f'{services.shown_date(until)}. Treated with Slice until 20 Oct.',
            f'Not suitable for harvest — medicine withdrawal of {self.batch.code}: harvest from about '
            f'{services.shown_date(until)}.',
            f'Not suitable for harvest — medicine withdrawal of {self.batch.code}: end unknown. No temperature '
            'recorded.'])
        with provider():
            self.assertIn('No medicine withdrawal in force.', self.assess().notes)

    def test_live_fish_moved_or_graded_are_not_asked_for_a_withdrawal(self):
        held = WithdrawalBlock(self.batch, self.day(-14), False, 'Treated with Slice until 20 Oct.', None)
        unknown = WithdrawalBlock(self.batch, None, False, 'No temperature recorded.', None)
        with provider(held, unknown):
            self.assertEqual(len(self.assess('harvest').warnings), 2)              # the same blocks and batch
            for kind in ('transport', 'grading', 'treatment'):
                with self.subTest(kind=kind):
                    result = self.assess(kind)
                    self.assertEqual(result.warnings, [])
                    self.assertEqual(result.fingerprint, '')
                    self.assertFalse([note for note in result.notes if 'withdrawal' in note.lower()])
        with no_provider():
            for kind in ('transport', 'grading'):
                self.assertFalse([note for note in self.assess(kind).notes if 'withdrawal' in note.lower()])
            self.assertIn('Medicine withdrawal not checked: the health records are not in yet.',
                          self.assess('harvest').notes)

    def test_only_the_harvest_box_speaks_of_a_medicine_withdrawal(self):
        words = 'Fish under a medicine withdrawal must not go to food. Going on is stored'
        for name, speaks in (('farm:stock_harvest', True), ('farm:stock_transfer', False),
                             ('farm:stock_grading', False)):
            with self.subTest(dialog=name):
                form = self.client.get(reverse(name, args=[self.t1.pk])).context['form']
                text = str(form.fields['handling_ack'].help_text)
                self.assertEqual(words in text, speaks)
                self.assertIn('Going on is stored with what is shown here and logged as critical.', text)

    def test_the_dialog_shows_the_blocks_and_the_drawer_and_row_badge_too(self):
        held = WithdrawalBlock(self.batch, self.day(-14), False, '', None)
        with provider(held):
            form = self.client.get(reverse('farm:stock_harvest', args=[self.t1.pk]))
            page = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        self.assertContains(form, f'Not suitable for harvest — medicine withdrawal of {self.batch.code}: harvest from')
        self.assertContains(form, 'name="handling_ack"')
        self.assertContains(page, 'Withdrawal</span>')
        self.assertContains(page, 'If the fish were harvested today:')
        self.assertContains(page, f'Not suitable for harvest — medicine withdrawal of {self.batch.code}: harvest from')


class AcknowledgementTests(HarvestTestCase):
    def test_going_on_needs_the_box_then_stores_what_was_shown_and_logs_it_critical(self):
        self.fed(1, at=clock(18, 0))
        until = self.day(-14)
        block = WithdrawalBlock(self.batch, until, True, 'Slice, last day 20 Oct.', None)
        with provider(block):
            self.assertEqual(self.refused(self.harvest), {'handling_ack': [
                'Tick the box to go on despite these warnings.']})
            seen = self.assess().fingerprint
            operation = self.harvest(handling_ack=seen)
        rows = list(HandlingAcknowledgement.objects.filter(operation=operation).order_by('warning'))
        self.assertEqual([(row.warning, row.withdrawal_until, row.withdrawal_approximate, row.withdrawal_reason,
                           row.fasted_hours, row.required_hours, row.rule) for row in rows], [
            ('fasting', None, False, '', Decimal('6.0'), 72, HandlingRule.objects.get(kind='harvest')),
            ('withdrawal', until, True, 'Slice, last day 20 Oct.', None, None, None)])
        self.assertEqual(rows[0].last_fed_at.isoformat(), f'{self.day(1).isoformat()}T18:00:00+00:00')
        self.assertEqual((rows[0].kind, rows[0].operation.created_by), ('harvest', self.user))
        entry = AuditLog.objects.get(entity_type='stock operation', action='create', entity_id=str(operation.pk))
        self.assertEqual(entry.severity, 'critical')
        self.assertIn('Not suitable for harvest — medicine withdrawal of', entry.changes['Handling warnings acknowledged'][1])
        self.assertIn('the harvest rule asks for 72 h.', entry.changes['Handling warnings acknowledged'][1])
        stocked = AuditLog.objects.get(entity_type='stock operation', action='create', changes__Operation=[
            None, {'msgid': 'Stocking'}])
        self.assertEqual(stocked.severity, 'normal')
        self.assertStockAddsUp()

    def test_changed_warnings_are_asked_again_at_the_save(self):
        self.fed(3)
        seen = self.assess().fingerprint                                     # 48 h shown
        self.fed(1, at=clock(18, 0))                                         # a feeding recorded meanwhile
        self.assertEqual(self.refused(self.harvest, handling_ack=seen), {'handling_ack': [
            'The warnings changed since the form was shown: read them again, and tick the box to go on.']})
        self.harvest(handling_ack=self.assess().fingerprint)
        self.assertEqual(HandlingAcknowledgement.objects.get().fasted_hours, Decimal('6.0'))

    def test_the_error_is_reported_on_the_field_the_caller_names(self):
        """Another form's box (an experiment's start) has its own name; the default is the stock forms'."""
        from types import SimpleNamespace
        shown = SimpleNamespace(warnings=['a warning'], fingerprint='abc')
        for field, call in (('handling_ack', lambda seen: check.require_acknowledged(shown, seen)),
                            ('start_ack', lambda seen: check.require_acknowledged(shown, seen, field='start_ack'))):
            with self.assertRaises(ValidationError) as caught:
                call('')
            self.assertEqual(list(caught.exception.message_dict), [field])
            with self.assertRaises(ValidationError) as caught:
                call('stale')
            self.assertEqual(caught.exception.message_dict[field],
                             ['The warnings changed since the form was shown: read them again, and tick the box to go on.'])
            call('abc')                                                       # exactly what was shown: goes on
        check.require_acknowledged(SimpleNamespace(warnings=[], fingerprint='x'), '', field='start_ack')

    def test_without_warnings_nothing_is_asked_or_stored(self):
        operation = self.harvest()
        self.assertFalse(HandlingAcknowledgement.objects.exists())
        self.assertEqual(AuditLog.objects.get(entity_id=str(operation.pk)).severity, 'normal')

    def test_through_the_dialogs_of_a_harvest_a_transfer_and_a_grading(self):
        self.fed(1, at=clock(22, 0))
        url = reverse('farm:stock_harvest', args=[self.t1.pk])
        form = self.client.get(url).context['form']
        fingerprint = form.handling.fingerprint
        data = {'token': str(uuid.uuid4()), 'batch': str(self.batch.pk), 'date': self.today.isoformat(),
                'count': '100', 'measured_weight_kg': '5.5', 'facility': str(self.facility.pk), 'notes': ''}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'Tick the box to go on despite these warnings.', status_code=422)
        self.assertContains(response, f'value="{fingerprint}"', status_code=422)
        self.assertEqual(self.client.post(url, {**data, 'handling_ack': fingerprint}).status_code, 302)
        self.assertEqual(HandlingAcknowledgement.objects.get().operation.kind, 'harvest')
        transfer = reverse('farm:stock_transfer', args=[self.t1.pk])
        moved = {'token': str(uuid.uuid4()), 'batch': str(self.batch.pk), 'date': self.today.isoformat(),
                 'reason': 'density', 'notes': '', 'rows-TOTAL_FORMS': '1', 'rows-INITIAL_FORMS': '0',
                 'rows-MIN_NUM_FORMS': '1', 'rows-MAX_NUM_FORMS': '12', 'rows-0-unit': str(self.t2.pk),
                 'rows-0-count': '100'}
        self.assertEqual(self.client.post(transfer, moved).status_code, 422)
        seen = self.client.get(transfer).context['form'].handling.fingerprint
        self.assertEqual(self.client.post(transfer, {**moved, 'handling_ack': seen}).status_code, 302)
        grading = reverse('farm:stock_grading', args=[self.t1.pk])
        graded = {**moved, 'token': str(uuid.uuid4()), 'remainder_avg_weight_g': '50', 'rows-0-avg_weight_g': '60',
                  'rows-0-size_class': 'Large'}
        self.assertEqual(self.client.post(grading, graded).status_code, 422)
        seen = self.client.get(grading).context['form'].handling.fingerprint
        self.assertEqual(self.client.post(grading, {**graded, 'handling_ack': seen}).status_code, 302)
        self.assertEqual(sorted(HandlingAcknowledgement.objects.values_list('operation__kind', flat=True)),
                         ['grading', 'harvest', 'transfer'])
        self.assertEqual(AuditLog.objects.filter(severity='critical').count(), 3)

    def test_the_shape_of_a_row_is_a_database_check(self):
        operation = self.harvest()
        for fields in ({'warning': 'withdrawal', 'fasted_hours': 1},
                       {'warning': 'fasting', 'fasted_hours': 80, 'required_hours': 72,
                        'rule': HandlingRule.objects.first(), 'last_fed_at': operation.created_at},
                       {'warning': 'fasting', 'fasted_hours': 1, 'required_hours': 72},
                       {'warning': 'other'}):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                HandlingAcknowledgement.objects.create(operation=operation, **fields)


# ---- the harvest ---------------------------------------------------------------------------------------
class HarvestRecordTests(HarvestTestCase):
    def test_a_harvest_names_where_its_fish_went_and_logs_it(self):
        operation = self.harvest(transport=self.boat, vessel=' MS Ronja ', notes='Into the wellboat')
        record = HarvestRecord.objects.get()
        self.assertEqual((record.operation, record.facility, record.transport, record.vessel),
                         (operation, self.facility, self.boat, 'MS Ronja'))
        entry = AuditLog.objects.get(entity_id=str(operation.pk))
        self.assertEqual((entry.changes['Slaughter facility'], entry.changes['Transport'],
                          entry.changes['Wellboat or vehicle']),
                         ([None, 'Fjord Slakteri (M123)'], [None, 'Brønnbåt AS (BB)'], [None, 'MS Ronja']))
        services.void(self.user, operation, 'Wrong unit')
        self.assertEqual((HarvestRecord.objects.count(), HarvestRecord.all_objects.count()), (0, 1))
        self.assertStockAddsUp()

    def test_the_facility_must_be_active_and_take_the_species_and_the_transport_carry(self):
        self.facility.status = SlaughterFacility.Status.INACTIVE
        self.facility.save()
        self.assertEqual(self.refused(self.harvest), {'facility': [
            'Choose an active slaughter facility that takes Atlantic salmon (SAL).']})
        trout_only = make_facility('Trout Slakteri', 'T1')
        trout_only.species.set([self.trout])
        self.assertIn('facility', self.refused(self.harvest, facility=trout_only))
        mill = Supplier.objects.create(name='Mill', code='ML', supplies=['feed'])
        self.assertEqual(self.refused(self.harvest, facility=make_facility('Open', 'O1'), transport=mill),
                         {'transport': ['Choose a supplier of wellboat and transport.']})
        self.assertFalse(StockOperation.objects.filter(kind='harvest').exists())

    def test_check_stock_finds_a_harvest_without_its_record_and_a_record_on_another_operation(self):
        operation = self.harvest(count=10)
        HarvestRecord.objects.filter(operation=operation).delete()
        weighing = services.record_weighing(self.user, unit=self.t1, batch=self.batch, day=self.today,
                                            avg_weight_g=Decimal(51))
        HarvestRecord.objects.create(operation=weighing, facility=self.facility)
        self.assertEqual(integrity.problems(), [
            f'Harvest {operation.pk} of {self.today} has no harvest record (slaughter facility).',
            f'Weighing {weighing.pk} has a harvest record.'])

    def test_the_dialog_says_round_weight_and_the_drawer_shows_the_book_and_the_difference(self):
        url = reverse('farm:stock_harvest', args=[self.t1.pk])
        form = self.client.get(url)
        self.assertContains(form, 'Round weight (kg)')
        self.assertEqual(list(form.context['form'].fields['facility'].queryset), [self.facility])
        self.assertContains(form, 'Medicine withdrawal not checked: the health records are not in yet.')
        data = {'token': str(uuid.uuid4()), 'batch': str(self.batch.pk), 'date': self.today.isoformat(),
                'count': '10000', 'measured_weight_kg': '520', 'facility': str(self.facility.pk),
                'transport': str(self.boat.pk), 'vessel': 'MS Ronja', 'notes': ''}
        self.assertEqual(self.client.post(f'{url}?unit={self.t1.pk}', data, headers={'X-Modal': '1'}).status_code, 204)
        page = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        self.assertContains(page, '520 kg weighed · book 500 kg · +20 kg (+4.0 %)')
        self.assertContains(page, 'To Fjord Slakteri (M123) · Brønnbåt AS · MS Ronja')


class HarvestedPageTests(HarvestTestCase):
    url = reverse('farm:harvests')

    def setUp(self):
        super().setUp()
        self.other = make_facility('Nord Slakteri', 'N9')
        self.second = self.stock(self.t2, count=2000, weight='100')    # 200 kg in T-02
        self.harvest(count=4000, kilos='210', days_ago=2)                   # book 200 kg
        self.harvest(count=5800, kilos='300', days_ago=1, everything=True, facility=self.other,
                     transport=self.boat)                                   # 200 fish lost; book 290 + 10
        self.voided = self.harvest(count=500, kilos='50', unit=self.t2, batch=self.second)
        services.void(self.user, self.voided, 'Typed into the wrong unit')

    def rows(self, **query):
        return [row['harvest'] for row in self.client.get(self.url, query).context['rows']]

    def test_every_harvest_with_the_book_against_the_scale(self):
        response = self.client.get(self.url)
        rows = [row['harvest'] for row in response.context['rows']]
        self.assertEqual([(row.fish, row.weighed_kg, row.book.kg, row.book.difference_kg, row.avg_weight_g)
                          for row in rows],
                         [(5800, Decimal('300.000'), Decimal(290), Decimal(10), Decimal('300') * 1000 / 5800),
                          (4000, Decimal('210.000'), Decimal(200), Decimal(10), Decimal('52.5'))])
        last = rows[0]
        self.assertEqual((last.loss.count_delta, last.loss_book.kg, last.record.facility, last.record.transport),
                         (-200, Decimal(10), self.other, self.boat))
        html = response.content.decode()
        for text in ('2 harvests · 510 kg round weight, 490 kg in the book', '+10 kg', '+5.0 %', '+3.4 %',
                     '−200 fish', 'Nord Slakteri', 'Brønnbåt AS', 'Per batch', 'Per site', 'Bergen'):
            self.assertIn(text, html)
        self.assertEqual([(total.label, total.fish, total.weighed_kg, total.book_kg, total.difference_kg)
                          for total in response.context['by_batch']],
                         [(self.batch.code, 9800, Decimal(510), Decimal(490), Decimal(20))])
        self.assertEqual([total.label for total in response.context['by_site']], ['Bergen'])

    def test_filters_and_voided_harvests(self):
        self.assertEqual([row.fish for row in self.rows(facility=self.other.pk)], [5800])
        self.assertEqual([row.fish for row in self.rows(**{'from': self.day(1).isoformat()})], [5800])
        self.assertEqual([row.fish for row in self.rows(to=self.day(2).isoformat())], [4000])
        self.assertEqual([row.fish for row in self.rows(batch=self.second.pk)], [])
        self.assertEqual([row.fish for row in self.rows(voided='1', batch=self.second.pk)], [500])
        self.assertEqual(len(self.rows(site=self.bergen.pk, unit=self.t1.pk, species=self.salmon.pk,
                                       department=self.hall.pk)), 2)
        self.assertEqual(len(self.rows(site='nonsense', unit='x')), 2)
        response = self.client.get(self.url, {'voided': '1'})
        self.assertContains(response, 'voided by ali: Typed into the wrong unit')
        self.assertEqual(response.context['by_batch'][0].fish, 9800)          # a voided harvest counts nowhere
        empty = self.client.get(self.url, {'facility': self.other.pk, 'to': self.day(3).isoformat()})
        self.assertContains(empty, 'No harvest matches these filters.')

    def test_only_the_page_is_built_and_the_totals_count_every_harvest(self):
        """The data-layering audit, L-12: the page is cut in the database and only its rows are built (records, plans,
        acknowledgements); the totals still count every live harvest the filters choose."""
        from unittest import mock

        from ..harvest import read as harvest_read, views as harvest_views
        built = []
        real = harvest_read.harvests

        def spy(*args, **kwargs):
            rows = real(*args, **kwargs)
            built.append(len(rows))
            return rows
        with mock.patch.object(harvest_views, 'PAGE_SIZE', 1), mock.patch.object(harvest_read, 'harvests', spy):
            response = self.client.get(self.url)
        self.assertEqual(built, [1])
        self.assertEqual([row['harvest'].fish for row in response.context['rows']], [5800])
        self.assertEqual(response.context['by_batch'][0].fish, 9800)
        self.assertEqual(response.context['count_line'], '2 harvests')

    def test_the_page_speaks_each_language(self):
        for language, words in {'tr': ('Hasat edilenler', 'Canlı ağırlık'), 'nb': ('Høstet', 'Rund vekt')}.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            response = self.client.get(self.url)
            for word in words:
                self.assertContains(response, word, msg_prefix=language)


# ---- plans ---------------------------------------------------------------------------------------------
class PlanItemTests(HarvestTestCase):
    list_url = reverse('farm:handlingplanitem_list')

    def data(self, **fields):
        return {'kind': 'harvest', 'date': self.day(-5).isoformat(), 'unit': str(self.t1.pk),
                'batch': str(self.batch.pk), 'planned_count': '9000', 'planned_kg': '4500', 'facility':
                str(self.facility.pk), 'transport': str(self.boat.pk), 'vessel': 'MS Ronja', 'notes': 'Week 46',
                'cancelled_reason': '', **fields}

    def test_a_planned_harvest_created_read_edited_cancelled_and_deleted_through_the_pages(self):
        form = self.client.get(reverse('farm:handlingplanitem_create'), {'kind': 'harvest', 'unit': self.t1.pk,
                                                                         'planned_count': '9000'})
        self.assertEqual((form.context['form']['unit'].value(), form.context['form']['planned_count'].value()),
                         (str(self.t1.pk), '9000'))
        self.assertNotIn('destination_unit', form.context['form'].fields)
        response = self.client.post(reverse('farm:handlingplanitem_create'), self.data())
        item = HandlingPlanItem.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual((item.kind, item.date, item.unit, item.batch, item.planned_count, item.planned_kg,
                          item.facility, item.transport, item.vessel, item.notes, item.created_by),
                         ('harvest', self.day(-5), self.t1, self.batch, 9000, Decimal('4500.000'), self.facility,
                          self.boat, 'MS Ronja', 'Week 46', self.user))
        listed = self.client.get(self.list_url)
        self.assertEqual([(row['item'], row['status']) for row in listed.context['objects']], [(item, 'planned')])
        self.assertContains(listed, 'Fasting before the harvest of')
        self.assertContains(listed, 'Record harvest')
        edit = reverse('farm:handlingplanitem_edit', args=[item.pk])
        cleared = self.data(planned_count='', planned_kg='', transport='', vessel='', notes='', version='1')
        self.client.post(edit, cleared)
        item.refresh_from_db()
        self.assertEqual((item.planned_count, item.planned_kg, item.transport, item.vessel, item.notes, item.version),
                         (None, None, None, '', '', 2))
        self.client.post(edit, {**cleared, 'cancelled_reason': 'Prices fell', 'version': '2'})
        item.refresh_from_db()
        self.assertEqual((item.cancelled_reason, item.status_on(self.today)), ('Prices fell', 'cancelled'))
        self.client.post(edit, {**cleared, 'version': '3'})
        self.assertEqual(HandlingPlanItem.objects.get().status_on(self.today), 'planned')
        logged = AuditLog.objects.filter(entity_type='planned harvest or transport').values_list('action', flat=True)
        self.assertEqual(sorted(logged), ['create', 'update', 'update', 'update'])
        self.client.post(reverse('farm:handlingplanitem_delete', args=[item.pk]))
        self.assertTrue(HandlingPlanItem.all_objects.get().is_deleted)

    def test_a_planned_transport_and_the_rules_of_a_plan(self):
        response = self.client.post(reverse('farm:handlingplanitem_create'), self.data(
            kind='transport', destination_unit=str(self.t2.pk), facility=''))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(HandlingPlanItem.objects.get().destination_unit, self.t2)
        self.stock(self.t2, count=100)
        refused = self.client.post(reverse('farm:handlingplanitem_create'), self.data(batch=str(self.batch.pk),
                                                                                    unit=str(self.t2.pk)))
        self.assertEqual(refused.context['form'].errors['batch'], [f'No fish of {self.batch.code} are in T-02 now.'])
        late = self.client.post(reverse('farm:handlingplanitem_create'), self.data(date=self.day(40).isoformat()))
        self.assertEqual(late.context['form'].errors['date'], [f'A plan can be dated at most 31 days back. {WINDOW_WAY_OUT}'])
        with correction_window(60):
            late = self.client.post(reverse('farm:handlingplanitem_create'), self.data(date=self.day(61).isoformat()))
            self.assertEqual(late.context['form'].errors['date'], [f'A plan can be dated at most 60 days back. {WINDOW_WAY_OUT}'])
        none = self.client.post(reverse('farm:handlingplanitem_create'), self.data(facility=''))
        self.assertIn('facility', none.context['form'].errors)
        with self.assertRaises(IntegrityError), transaction.atomic():
            HandlingPlanItem.objects.create(kind='harvest', date=self.today, unit=self.t1, batch=self.batch)
        with self.assertRaises(IntegrityError), transaction.atomic():
            HandlingPlanItem.objects.create(kind='transport', date=self.today, unit=self.t1, batch=self.batch,
                                            destination_unit=self.t1)

    def test_recorded_from_the_plan_it_is_done_and_a_void_plans_it_again(self):
        item = HandlingPlanItem.objects.create(kind='harvest', date=self.today, unit=self.t1, batch=self.batch,
                                               planned_count=9000, planned_kg=Decimal(450), facility=self.facility,
                                               vessel='MS Ronja')
        row = self.client.get(self.list_url).context['objects'][0]
        url = row['record_url']
        self.assertTrue(url.startswith(f'{reverse("farm:stock_harvest", args=[self.t1.pk])}?plan={item.pk}'))
        form = self.client.get(url).context['form']
        self.assertEqual((form['count'].value(), form['facility'].value(), form['vessel'].value(),
                          form['plan_item'].value()), (9000, self.facility.pk, 'MS Ronja', item.pk))
        data = {'token': str(uuid.uuid4()), 'batch': str(self.batch.pk), 'date': self.today.isoformat(),
                'count': '9000', 'measured_weight_kg': '470', 'facility': str(self.facility.pk), 'transport': '',
                'vessel': 'MS Ronja', 'notes': '', 'plan_item': str(item.pk)}
        response = self.client.post(url, data)
        self.assertEqual(response['Location'], self.list_url)
        item.refresh_from_db()
        operation = StockOperation.objects.get(kind='harvest')
        self.assertEqual((item.operation, item.status_on(self.today)), (operation, 'done'))
        row = self.client.get(self.list_url).context['objects'][0]
        self.assertEqual((row['actual_count'], row['actual_kg']), (9000, Decimal(470)))
        self.assertEqual(self.client.get(self.url_harvested()).context['rows'][0]['harvest'].plan, item)
        self.assertIn('plan_item', self.refused(self.harvest, count=10, plan_item=item))
        services.void(self.user, operation, 'Postponed')
        item.refresh_from_db()
        self.assertEqual(item.status_on(self.today), 'planned')
        item.cancelled_reason = 'Postponed to spring'
        item.save()
        self.assertEqual(self.refused(self.harvest, count=10, plan_item=item), {'plan_item': ['This plan is cancelled.']})
        self.assertEqual(item.status_on(self.today + timedelta(days=1)), 'cancelled')
        transport = HandlingPlanItem.objects.create(kind='transport', date=self.today, unit=self.t1, batch=self.batch)
        self.assertEqual(self.refused(self.harvest, count=10, plan_item=transport), {'plan_item': [
            'A planned transport is recorded as a transfer.']})
        services.record_transfer(self.user, source=self.t1, batch=self.batch, day=self.today, legs=[(self.t2, 10)],
                                 reason='density', plan_item=transport)
        transport.refresh_from_db()
        self.assertEqual(transport.operation.kind, 'transfer')
        self.assertStockAddsUp()

    def url_harvested(self):
        return reverse('farm:harvests')

    def test_a_done_plan_is_not_cancelled_and_an_overdue_one_says_so(self):
        item = HandlingPlanItem.objects.create(kind='harvest', date=self.day(2), unit=self.t1, batch=self.batch,
                                               facility=self.facility)
        self.assertEqual(item.status_on(self.today), 'overdue')
        operation = self.harvest(count=10, plan_item=item)
        item.refresh_from_db()
        item.cancelled_reason = 'Too late'
        with self.assertRaises(ValidationError) as caught:
            item.full_clean()
        self.assertEqual(caught.exception.message_dict['cancelled_reason'],
                         ['It is done: void the operation that recorded it first.'])
        self.assertEqual(item.operation, operation)

    def test_check_stock_finds_a_plan_fulfilled_by_other_fish(self):
        item = HandlingPlanItem.objects.create(kind='harvest', date=self.today, unit=self.t1, batch=self.batch,
                                               facility=self.facility)
        operation = self.harvest(count=10, plan_item=item)
        HandlingPlanItem.objects.filter(pk=item.pk).update(unit=self.t2)
        self.assertEqual(integrity.problems(), [f'Plan item {item.pk} names other fish than the harvest that '
                                                f'fulfils it.'])
        self.assertTrue(operation.pk)


class FastsTests(HarvestTestCase):
    def test_a_planned_harvest_asks_its_unit_to_fast_from_the_start_of_its_day_less_the_rule(self):
        on = self.day(-5)
        item = HandlingPlanItem.objects.create(kind='harvest', date=on, unit=self.t1, batch=self.batch,
                                               facility=self.facility)
        days = fasting.fasts([self.t1], self.today, self.day(-10))
        self.assertEqual(sorted(day for _unit, day in days), [on - timedelta(days=n) for n in (3, 2, 1, 0)])
        self.assertEqual(fasting.fasting_on(self.t1, on - timedelta(days=4)), None)
        self.assertEqual(fasting.fasting_on(self.t1, on - timedelta(days=3)),
                         f'Fasting before the harvest of {services.shown_date(on)}: from '
                         f'{services.shown_date(on - timedelta(days=3))} 00:00 (72 h).')
        self.assertIsNone(fasting.fasting_on(self.t2, on))
        transport = HandlingPlanItem.objects.create(kind='transport', date=on - timedelta(days=1), unit=self.t1,
                                                    batch=self.batch)
        self.assertEqual(fasting.fasts([self.t1], on, on)[(self.t1.pk, on)].item, item)
        self.rule('transport', 96)                                           # it starts first: it wins
        self.assertEqual(fasting.fasts([self.t1], on - timedelta(days=2), on - timedelta(days=2))[
            (self.t1.pk, on - timedelta(days=2))].item, transport)
        item.cancelled_reason = 'Postponed'
        item.save()
        self.assertIsNone(fasting.fasting_on(self.t1, on))

    def test_the_feeding_dialog_says_the_day_is_a_fasting_day(self):
        HandlingPlanItem.objects.create(kind='harvest', date=self.day(-1), unit=self.t1, batch=self.batch,
                                        facility=self.facility)
        response = self.client.get(reverse('farm:feeding_record', args=[self.t1.pk]))
        self.assertContains(response, 'Fasting before the harvest of')
        self.assertContains(response, 'A feeding can still be recorded.')


class PurgingBase(HarvestTestCase):
    """A harvest's fast in degree-days (purging) beside, or instead of, its hours: the 10,000 salmon of T-01 were last
    fed 4 days ago at 18:00, so the full days since are 3 days ago to yesterday; the feeding day and the harvest's own
    day are not counted."""

    def setUp(self):
        super().setUp()
        self.purge(degrees=60)

    def purge(self, hours=None, degrees=None, species=None):
        """The harvest rule (for every species, or a species): its hours and degree-days."""
        HandlingRule.objects.filter(kind='harvest', species=species).delete()
        return HandlingRule.objects.create(kind='harvest', species=species, min_fasting_hours=hours,
                                           min_fasting_degree_days=degrees)

    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def temperature(self, days_ago, value, unit=None):
        site = (unit or self.t1).production_department.site
        moment = datetime.combine(self.day(days_ago), clock(12), tzinfo=zone_of(site))
        return WaterMeasurement.objects.create(point=point_of(unit or self.t1), measured_at=moment, source='manual',
                                               temperature_c=Decimal(value), created_by=self.user)

    def warm(self, *days_ago, value='10'):
        for each in days_ago:
            self.temperature(each, value)


class PurgingTests(PurgingBase):
    def test_degree_days_alone_add_up_the_full_days_between_the_feeding_and_the_harvest(self):
        self.fed(4, at=clock(18, 0))
        self.warm(3, 2, 1)                                      # 10 °C a day: 30 degree-days
        self.warm(4, 0, value='30')                             # the feeding day and the harvest day: not counted
        result = self.assess()
        [warning] = result.warnings
        self.assertEqual((warning.warning, warning.fasted_degree_days, warning.required_degree_days,
                          warning.required_hours, warning.rule.kind),
                         ('fasting', Decimal('30.0'), Decimal('60.0'), None, 'harvest'))
        self.assertEqual(warning.fasted_hours, Decimal('78.0'))              # 18:00 four days ago to today's start
        self.assertEqual(warning.message(),
                         f'Last fed {services.shown_date(self.day(4))} 18:00 in T-01, 30 degree-days before '
                         f'{services.shown_date(self.today)}: the harvest rule asks for 60 degree-days. Days counted: 3 days from water samples.')
        self.assertFalse([note for note in result.notes if 'Last fed' in note or 'asks for' in note])   # one line
        # Reached exactly: no warning; one degree-day short: a warning.
        self.purge(degrees=30)
        self.assertEqual(self.assess().warnings, [])
        self.purge(degrees=Decimal('30.1'))
        self.assertEqual(len(self.assess().warnings), 1)

    def test_hours_and_degree_days_each_have_to_be_reached_and_the_later_decides(self):
        self.purge(hours=72, degrees=60)
        self.fed(5, at=clock(6, 0))                              # 114 h before today's start
        self.warm(4, 3, 2, 1)                                    # 40 degree-days
        [warning] = self.assess().warnings
        self.assertEqual((warning.fasted_hours, warning.fasted_degree_days), (Decimal('114.0'), Decimal('40.0')))
        self.assertTrue(warning.message().endswith(
            'the harvest rule asks for 72 h and 60 degree-days. Days counted: 4 days from water samples.'), warning.message())
        self.assertIn('114.0 h and 40 degree-days before', warning.message())
        self.purge(hours=72, degrees=40)                          # the degrees reached, the hours too: clear
        self.assertEqual(self.assess().warnings, [])
        # Hours decide when the degrees are reached first: 52 h against 72 h, 20 degree-days against 20.
        self.purge(hours=72, degrees=20)
        self.fed(3, at=clock(20, 0))                              # the latest feeding
        [warning] = self.assess().warnings
        self.assertEqual((warning.fasted_hours, warning.fasted_degree_days), (Decimal('52.0'), Decimal('20.0')))
        self.assertEqual((warning.required_hours, warning.required_degree_days), (72, Decimal('20.0')))

    def test_days_work_like_hours(self):
        # A rule typed as 3 days is 72 hours: the same warning, and the fast is the same.
        self.purge(hours=3 * 24)
        self.fed(3, at=clock(20, 0))                             # 52 h
        [warning] = self.assess().warnings
        self.assertIn('52.0 h before', warning.message())
        self.assertTrue(warning.message().endswith('the harvest rule asks for 72 h.'))

    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def test_a_day_without_a_measured_temperature_counts_at_the_assumed_one_or_as_zero_and_says_so(self):
        self.fed(4, at=clock(18, 0))
        self.warm(3, 1)                                          # the middle day, 2 days ago, was not measured
        [warning] = self.assess().warnings
        self.assertEqual(warning.fasted_degree_days, Decimal('20.0'))
        self.assertEqual(warning.accrual.missing, 1)
        self.assertTrue(warning.message().endswith(
            '1 day without a measured water temperature is counted as 0 °C: set the species’ assumed temperature '
            'in Reference data › Species.'), warning.message())
        Species.objects.filter(pk=self.salmon.pk).update(withdrawal_temperature_c=Decimal('8.0'))
        result = self.assess()
        [warning] = result.warnings
        self.assertEqual(warning.fasted_degree_days, Decimal('28.0'))
        self.assertTrue(warning.message().endswith(
            '1 day without a measured water temperature is counted at the assumed 8.0 °C (the species’ setting in '
            'Reference data).'), warning.message())
        # Exactly as the same day measured at that value would.
        self.temperature(2, '8')
        measured = self.assess().warnings[0]
        self.assertEqual((measured.fasted_degree_days, measured.accrual.missing), (Decimal('28.0'), 0))

    def test_a_transfer_and_a_grading_are_checked_on_hours_alone(self):
        self.fed(4, at=clock(18, 0))
        for kind in ('transport', 'grading'):
            with self.subTest(kind=kind):
                result = self.assess(kind)
                self.assertEqual(result.warnings, [])                    # 78 h against 24 h
                self.assertFalse([note for note in result.notes if 'degree-day' in note])
        self.rule('transport', 100)
        [warning] = self.assess('transport').warnings
        self.assertEqual((warning.required_hours, warning.required_degree_days, warning.fasted_degree_days),
                         (100, None, None))
        self.assertEqual(warning.message(), f'Last fed {services.shown_date(self.day(4))} 18:00 in T-01, 78.0 h before '
                                            f'{services.shown_date(self.today)}: the transport rule asks for 100 h.')

    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def test_going_on_stores_the_degree_days_and_a_new_temperature_asks_again(self):
        self.fed(4, at=clock(18, 0))
        self.warm(3, 2, 1)
        seen = self.assess().fingerprint
        self.assertEqual(self.refused(self.harvest, handling_ack=''), {
            'handling_ack': ['Tick the box to go on despite these warnings.']})
        self.temperature(0, '9')                                 # today's, not counted: the warning is the same
        self.assertEqual(self.assess().fingerprint, seen)
        WaterMeasurement.objects.filter(temperature_c=Decimal('10')).update(temperature_c=Decimal('11'))
        self.assertNotEqual(self.assess().fingerprint, seen)
        self.assertEqual(self.refused(self.harvest, handling_ack=seen), {'handling_ack': [
            'The warnings changed since the form was shown: read them again, and tick the box to go on.']})
        operation = self.harvest(handling_ack=self.assess().fingerprint)
        [row] = HandlingAcknowledgement.objects.filter(operation=operation)
        self.assertEqual((row.warning, row.fasted_hours, row.required_hours, row.fasted_degree_days,
                          row.required_degree_days, row.rule.kind),
                         ('fasting', Decimal('78.0'), None, Decimal('33.0'), Decimal('60.0'), 'harvest'))
        entry = AuditLog.objects.get(entity_type='stock operation', action='create', entity_id=str(operation.pk))
        self.assertEqual(entry.severity, 'critical')
        self.assertIn('33 degree-days before', entry.changes['Handling warnings acknowledged'][1])
        self.assertIn('the harvest rule asks for 60 degree-days.', entry.changes['Handling warnings acknowledged'][1])

    def test_the_shape_of_a_fasting_row_with_degree_days_is_a_database_check(self):
        operation = self.harvest()
        rule = HandlingRule.objects.get(kind='harvest')
        moment = operation.created_at
        ok = {'warning': 'fasting', 'last_fed_at': moment, 'rule': rule, 'fasted_hours': Decimal(78)}
        # Degrees unmet, hours not asked; hours met and degrees unmet; hours unmet and degrees met: each a warning.
        for fields in ({'fasted_degree_days': Decimal(30), 'required_degree_days': Decimal(60)},
                       {'required_hours': 72, 'fasted_degree_days': Decimal(30), 'required_degree_days': Decimal(60)},
                       {'required_hours': 100, 'fasted_degree_days': Decimal(60), 'required_degree_days': Decimal(60)}):
            with self.subTest(fields=fields), transaction.atomic():
                HandlingAcknowledgement.objects.create(operation=operation, **ok, **fields).delete()
        for fields in ({},                                                                  # nothing asked
                       {'required_hours': 72},                                              # met: not a warning
                       {'fasted_degree_days': Decimal(30)},                                 # degrees without the asked
                       {'required_degree_days': Decimal(60)},                               # ... or the fasted
                       {'fasted_degree_days': Decimal(60), 'required_degree_days': Decimal(60)},
                       {'required_degree_days': Decimal(60), 'fasted_degree_days': Decimal(-1)}):
            with self.subTest(refused=fields), self.assertRaises(IntegrityError), transaction.atomic():
                HandlingAcknowledgement.objects.create(operation=operation, **ok, **fields)


class PurgingFastsTests(PurgingBase):
    """When feeding must stop for a planned harvest whose rule asks for degree-days: counted back from the planned day, a
    past day at its measured temperature (or the species' assumed one, else 0), a day not over or still to come at the
    mean of the last 7 measured days, else the species' assumed temperature."""

    def plan(self, days_ahead, **fields):
        return HandlingPlanItem.objects.create(kind='harvest', date=self.day(-days_ahead), unit=self.t1,
                                               batch=self.batch, facility=self.facility, **fields)

    def fast(self, item):
        return fasting.fast_of(item)

    def test_the_first_fasting_day_is_found_backwards_through_projected_and_measured_days(self):
        self.warm(1, 2, 3, 4, 5)                                 # 10 °C a day measured; so the mean of the last 7 is 10
        item = self.plan(5)                                      # the harvest is in 5 days: 60 degree-days is 6 days
        fast = self.fast(item)
        # The days counted are 4, 3, 2, 1 days ahead and today (projected at 10, today has none yet): 50, and yesterday:
        # 60, so the fast starts yesterday and every day from then to the harvest is a fasting day.
        self.assertEqual(fast.first_day, self.day(1))
        self.assertTrue(fast.start.projected)
        self.assertEqual(fast.why(), f'Fasting before the harvest of {services.shown_date(item.date)}: from '
                                     f'{services.shown_date(self.day(1))} 00:00 (60 degree-days). Projected at the '
                                     'mean water temperature of the last days measured. Days counted: 1 day from water samples, 5 days projected.')
        days = fasting.fasts([self.t1], self.day(3), item.date)
        self.assertEqual(sorted(day for _unit, day in days),
                         [self.day(1) + timedelta(days=n) for n in range(0, 7)])
        self.assertEqual(fasting.fasting_on(self.t1, self.day(2)), None)
        self.assertEqual(fasting.fasting_on(self.t1, self.day(1)), fast.why())
        # A planned harvest in 2 days: tomorrow and today projected, then 4 measured days back: 60 by 4 days ago.
        near = self.plan(2)
        self.assertEqual(self.fast(near).first_day, self.day(4))

    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def test_a_past_day_without_a_measurement_counts_at_the_assumed_temperature_or_zero(self):
        self.purge(degrees=45)
        self.warm(1, 3, 4, 5, 6, 7)                              # 2 days ago was not measured
        item = self.plan(0)                                      # a harvest today: the days counted are all past
        fast = self.fast(item)
        # Yesterday 10, 2 days ago 0 (nothing assumed), then 10 a day: 40 by 5 days ago, 50 by 6 days ago.
        self.assertEqual((fast.first_day, fast.start.missing, fast.start.assumed), (self.day(6), 1, None))
        self.assertIn('1 day without a measured water temperature is counted as 0 °C: set the species’ assumed '
                      'temperature in Reference data › Species.', fast.why())
        Species.objects.filter(pk=self.salmon.pk).update(withdrawal_temperature_c=Decimal('8.0'))
        fast = self.fast(item)
        # 2 days ago counts 8: 10, 18, 28, 38, 48 by 5 days ago, so the fast starts a day later.
        self.assertEqual((fast.first_day, fast.start.missing, fast.start.assumed), (self.day(5), 1, Decimal('8.0')))
        self.assertIn('1 day without a measured water temperature is counted at the assumed 8.0 °C (the species’ '
                      'setting in Reference data).', fast.why())
        self.temperature(2, '8')                                 # measured at that value: the same day, and no missing
        measured = self.fast(item)
        self.assertEqual((measured.first_day, measured.start.missing), (self.day(5), 0))

    @withdrawal_gate.opened('test fixture: withdrawal inputs written straight in the database')
    def test_no_temperature_at_all_leaves_the_hours_alone_and_says_degree_days_are_unknown(self):
        item = self.plan(3)
        fast = self.fast(item)                                   # degree-days only: nothing can be counted ahead
        self.assertIsNone(fast.first_day)
        self.assertTrue(fast.start.unknown)
        self.assertEqual(fast.why(), f'Fasting before the harvest of {services.shown_date(item.date)}: 60 degree-days. '
                                     'Degree-days unknown: no temperature.')
        self.assertEqual(fasting.fasts([self.t1], self.today, item.date), {})
        self.purge(hours=72, degrees=60)                          # with hours too: the hours alone apply
        fast = self.fast(item)
        self.assertEqual(fast.first_day, item.date - timedelta(days=3))
        self.assertTrue(fast.why().endswith('(72 h and 60 degree-days). Degree-days unknown: no temperature.'),
                        fast.why())
        self.assertEqual(sorted(day for _unit, day in fasting.fasts([self.t1], self.today, item.date)),
                         [item.date - timedelta(days=n) for n in (3, 2, 1, 0)])
        # The species' assumed temperature is what days ahead are projected at, when none was measured.
        Species.objects.filter(pk=self.salmon.pk).update(withdrawal_temperature_c=Decimal('15.0'))
        fast = self.fast(item)
        self.assertFalse(fast.start.unknown)
        self.assertTrue(fast.start.projected_at_assumed)
        self.assertEqual(fast.first_day, item.date - timedelta(days=4))         # 4 days at 15 °C is 60
        self.assertIn('Projected at the assumed 15.0 °C (the species’ setting in Reference data): no water '
                      'temperature was measured in the last 30 days.', fast.why())

    def test_the_later_of_the_hours_and_the_degree_days_starts_the_fast(self):
        self.warm(1, 2, 3, 4, 5, 6, 7, value='5')
        item = self.plan(0)
        self.purge(hours=72, degrees=20)                          # 20 degree-days at 5 °C: 4 days; the hours: 3 days
        self.assertEqual(self.fast(item).first_day, self.day(4))
        self.purge(hours=120, degrees=20)                         # 5 days of hours decide
        self.assertEqual(self.fast(item).first_day, self.day(5))
        self.purge(hours=None, degrees=20)
        self.assertEqual(self.fast(item).first_day, self.day(4))

    def test_a_degree_days_rule_that_the_water_never_reaches_starts_the_day_the_fish_came_and_says_so(self):
        self.warm(*range(1, 70), value='0')
        item = self.plan(0)
        fast = self.fast(item)
        self.assertTrue(fast.start.unreached)
        # Looked for back to the day the fish came (20 days ago), never further: no water before it was theirs.
        self.assertEqual(fast.first_day, self.day(20))
        self.assertIn('The degree-days are not reached since the fish came (20 days) at these temperatures.',
                      fast.why())
        self.assertEqual(fast.start.missing, 0)

    def test_the_meal_board_gives_no_ration_from_that_day(self):
        self.warm(1, 2, 3, 4, 5)
        self.plan(5)
        response = self.client.get(reverse('farm:feeding_record', args=[self.t1.pk]))
        self.assertContains(response, 'Fasting before the harvest of')
        self.assertContains(response, '(60 degree-days)')


class EarliestTests(PurgingBase):
    """The earliest suitable harvest date: the later of the end of the medicine withdrawal and the first day the purge can
    be complete from the last feeding, and which decides."""

    def setUp(self):
        super().setUp()
        self.purge(hours=72)                                     # a plain 72 h purge
        self.fed(1, at=clock(18, 0))                             # last fed yesterday at 18:00: complete from 3 days ahead

    def block(self, days_ahead, **fields):
        return WithdrawalBlock(self.batch, None if days_ahead is None else self.day(-days_ahead),
                               fields.pop('approximate', False), fields.pop('reason', ''), None)

    def earliest(self, *blocks):
        with provider(*blocks):
            return check.earliest(self.t1, self.batch)

    def test_the_purge_decides_when_it_ends_after_the_withdrawal_and_says_when_feeding_must_stop(self):
        found = self.earliest(self.block(1))                     # the withdrawal ends tomorrow
        self.assertEqual((found.decides, found.day, found.until), ('purging', self.day(-3), self.day(-1)))
        self.assertEqual(found.stop_by, self.day(1))             # fed yesterday, the last day it may be
        self.assertEqual(found.text(), f'Earliest suitable harvest date: {services.shown_date(self.day(-3))}. '
                                       f'Purging decides: feeding must stop by {services.shown_date(self.day(1))}.')
        self.assertTrue(found.holds(self.day(-2)))
        self.assertFalse(found.holds(self.day(-3)))

    def test_the_medicine_withdrawal_decides_when_it_ends_after_the_purge(self):
        found = self.earliest(self.block(10))
        self.assertEqual((found.decides, found.day, found.stop_by), ('withdrawal', self.day(-10), None))
        self.assertEqual(found.text(), f'Earliest suitable harvest date: {services.shown_date(self.day(-10))}. '
                                       f'Medicine withdrawal decides: harvest from '
                                       f'{services.shown_date(self.day(-10))}.')
        approximate = self.earliest(self.block(10, approximate=True))
        self.assertIn('Medicine withdrawal decides: harvest from about', approximate.text())
        # A tie goes to the withdrawal: food safety first.
        self.assertEqual(self.earliest(self.block(3)).decides, 'withdrawal')

    def test_an_unknown_withdrawal_end_has_no_date(self):
        found = self.earliest(self.block(None))
        self.assertEqual((found.decides, found.day, found.unknown), ('withdrawal', None, True))
        self.assertEqual(found.text(), 'Earliest suitable harvest date: not known. Medicine withdrawal decides: end '
                                       'unknown.')
        self.assertTrue(found.holds(self.day(-400)))

    def test_with_nothing_holding_the_fish_there_is_no_date(self):
        found = self.earliest(self.block(-5))                    # a block that ended 5 days ago is not in force
        self.assertEqual(found.decides, 'purging')               # the 72 h purge still holds: fed yesterday
        self.purge(hours=1)                                      # 6 h have gone since the last feeding: complete
        found = self.earliest()
        self.assertEqual((found.decides, found.text(), found.holds(self.today)), ('', '', False))
        HandlingRule.objects.filter(kind='harvest').delete()     # no rule: no purge to wait for
        self.assertEqual(self.earliest().decides, '')

    def test_degree_days_decide_the_purge_day_through_the_projection(self):
        self.purge(degrees=30)
        self.warm(1, 2, 3, 4, 5)
        found = self.earliest()
        # Last fed yesterday: the days counted from the day after it, today (no sample yet, projected at 10 °C), and
        # the next two days: 30 degree-days are complete by the start of the 4th day after today... exactly 3 days ahead.
        self.assertEqual((found.decides, found.day), ('purging', self.day(-3)))
        self.assertEqual(found.stop_by, self.day(1))

    def test_the_harvest_dialog_and_the_drawer_say_it_and_a_harvest_before_it_still_goes_on_when_acknowledged(self):
        with provider(self.block(10)):
            form = self.client.get(reverse('farm:stock_harvest', args=[self.t1.pk]))
            drawer = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
            self.assertContains(form, f'Earliest suitable harvest date: {services.shown_date(self.day(-10))}.')
            self.assertContains(form, f'Medicine withdrawal decides: harvest from '
                                      f'{services.shown_date(self.day(-10))}.')
            self.assertContains(drawer, 'Earliest suitable harvest date:')
            self.assertIsNotNone(form.context['form'].handling.earliest)
            fingerprint = self.assess().fingerprint
            operation = self.harvest(handling_ack=fingerprint)
        self.assertEqual(AuditLog.objects.get(entity_type='stock operation', entity_id=str(operation.pk),
                                              action='create').severity, 'critical')

    def test_a_transfer_and_a_grading_do_not_say_it(self):
        with provider(self.block(10)):
            for kind in ('transport', 'grading'):
                result = self.assess(kind)
                self.assertIsNone(result.earliest)
                self.assertFalse([note for note in result.notes if 'Earliest suitable' in note])

    def test_the_plan_pages_show_it_and_mark_a_plan_dated_before_it(self):
        early = HandlingPlanItem.objects.create(kind='harvest', date=self.day(-1), unit=self.t1, batch=self.batch,
                                                facility=self.facility)
        late = HandlingPlanItem.objects.create(kind='harvest', date=self.day(-20), unit=self.t1, batch=self.batch,
                                               facility=self.facility)
        with provider(self.block(10)):
            page = self.client.get(reverse('farm:handlingplanitem_list'))
            rows = {row['item'].pk: row for row in page.context['objects']}
            self.assertTrue(rows[early.pk]['earliest'].holds(early.date))
            self.assertFalse(rows[late.pk]['earliest'].holds(late.date))
            self.assertContains(page, f'Earliest suitable harvest date: {services.shown_date(self.day(-10))}.')
            self.assertContains(page, 'class="row-sub over-text">Earliest suitable harvest date', count=1)
            plans = self.client.get(reverse('farm:productionplan_list'))
            self.assertContains(plans, f'Earliest suitable harvest date: {services.shown_date(self.day(-10))}.')

    def test_the_texts_are_in_turkish_and_norwegian(self):
        self.addCleanup(translation.activate, 'en')
        words = {'tr': ('En erken uygun hasat tarihi: ', 'İlaç bekleme süresi belirler: ',
                        'Arındırma belirler: yemleme en geç '),
                 'nb': ('Tidligste egnede høstedato: ', 'Tilbakeholdelsestiden avgjør: høsting fra ',
                        'Rensingen avgjør: fôringen må stoppe senest ')}
        for language, (earliest, withdrawal_decides, purging_decides) in words.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            with provider(self.block(10)):
                page = self.client.get(reverse('farm:stock_harvest', args=[self.t1.pk]))
            self.assertContains(page, earliest, msg_prefix=language)
            self.assertContains(page, withdrawal_decides, msg_prefix=language)
            with provider(self.block(1)):
                page = self.client.get(reverse('farm:stock_harvest', args=[self.t1.pk]))
            self.assertContains(page, purging_decides, msg_prefix=language)
            self.assertNotContains(page, 'Earliest suitable', msg_prefix=language)


class ForecastTests(HarvestTestCase):
    """One band at FCR 1.00 and 1 % of the body weight a day at 10 °C: the fish grow 1 % a day from 50 g."""

    def setUp(self):
        super().setUp()
        self.protocol = ProtocolTestCase.make_protocol(self, bands=((0, None, None),), columns=('10',), sfr=(('1.00',),))
        self.plan = ProductionPlan.objects.create(batch=self.batch, target_weight_g=Decimal(55))

    def row(self):
        return self.client.get(reverse('farm:productionplan_list')).context['objects'][0]

    def test_the_day_the_target_is_reached_on_the_ration_at_the_temperature_held(self):
        ProtocolTestCase.assign(self, self.protocol, unit=self.t1)
        ProtocolTestCase.water(self, '10')
        row = self.row()                                                     # 50 × 1.01^10 = 55.2 g ≥ 55 g
        self.assertEqual((row['forecast'].now_g, row['forecast'].day, row['forecast'].temperature_c),
                         (Decimal(50), self.day(-10), Decimal('10.0')))
        self.assertIn(f'date={self.day(-10).isoformat()}', row['plan_harvest_url'])
        self.assertContains(self.client.get(reverse('farm:productionplan_list')), 'at 10.0 °C held')
        HandlingPlanItem.objects.create(kind='transport', date=self.day(-5), unit=self.t1, batch=self.batch)
        self.assertEqual(self.row()["forecast"].day, self.day(-12))          # its fast: the day before and the day

    def test_it_stops_where_the_ration_stops_and_says_why(self):
        self.assertEqual(self.row()['forecast'].why, 'No protocol is assigned to these fish.')
        ProtocolTestCase.assign(self, self.protocol, unit=self.t1)
        self.assertEqual(self.row()['forecast'].why, 'No temperature recorded here yet: record one.')


class ProductionPlanTests(HarvestTestCase):
    list_url = reverse('farm:productionplan_list')

    def test_a_target_created_read_edited_and_deleted_through_the_pages(self):
        listed = self.client.get(self.list_url)
        self.assertContains(listed, 'Set target')
        self.assertEqual(listed.context['objects'][0]['forecast'].now_g, Decimal(50))
        create = reverse('farm:productionplan_create')
        self.assertEqual(self.client.get(create, {'batch': self.batch.pk}).context['form']['batch'].value(),
                         str(self.batch.pk))
        self.client.post(create, {'batch': str(self.batch.pk), 'target_weight_g': '5000', 'notes': 'Superior'})
        plan = ProductionPlan.objects.get()
        self.assertEqual((plan.batch, plan.target_weight_g, plan.notes), (self.batch, Decimal('5000.0000'),
                                                                          'Superior'))
        twice = self.client.post(create, {'batch': str(self.batch.pk), 'target_weight_g': '4000', 'notes': ''})
        self.assertIn('batch', twice.context['form'].errors)
        row = self.client.get(self.list_url).context['objects'][0]
        self.assertIn('planned_kg=50000.000', row['plan_harvest_url'])
        self.assertIn('planned_count=10000', row['plan_harvest_url'])
        edit = reverse('farm:productionplan_edit', args=[plan.pk])
        self.client.post(edit, {'target_weight_g': '4500.5', 'notes': '', 'version': '1'})
        plan.refresh_from_db()
        self.assertEqual((plan.batch, plan.target_weight_g, plan.notes), (self.batch, Decimal('4500.5000'), ''))
        self.assertIn('target_weight_g', self.client.post(edit, {'target_weight_g': '0', 'version': '2'})
                      .context['form'].errors)
        self.harvest()                                                       # the batch leaves the stock
        self.assertContains(self.client.get(self.list_url), 'No longer in stock')
        self.client.post(reverse('farm:productionplan_delete', args=[plan.pk]))
        self.assertFalse(ProductionPlan.objects.exists())
        self.assertEqual(sorted(AuditLog.objects.filter(entity_type='production plan').values_list('action', flat=True)),
                         ['create', 'delete', 'update'])


# ---- reference data ------------------------------------------------------------------------------------
class SlaughterFacilityTests(HarvestTestCase):
    list_url = reverse('farm:slaughterfacility_list')

    def data(self, **fields):
        return {'name': 'Hav Slakteri', 'approval_number': 'h77', 'operator': '', 'status': 'active',
                'address': 'Kaien 1', 'municipality': 'Austevoll', 'latitude': '60.1', 'longitude': '5.2',
                'species': [str(self.salmon.pk)], 'capacity_tonnes_per_day': '120.5', 'notes': 'Pumps from boat',
                **fields}

    def test_created_read_edited_and_deleted_through_the_pages_every_field_clearable(self):
        operator = Supplier.objects.create(name='Hav AS', code='HAV', supplies=['slaughter'])
        create = reverse('farm:slaughterfacility_create')
        self.assertEqual(list(self.client.get(create).context['form'].fields['operator'].queryset), [operator])
        self.client.post(create, self.data(operator=str(operator.pk)))
        facility = SlaughterFacility.objects.get(name='Hav Slakteri')
        self.assertEqual((facility.approval_number, facility.operator, facility.address, facility.municipality,
                          facility.latitude, facility.longitude, list(facility.species.all()),
                          facility.capacity_tonnes_per_day, facility.notes, facility.status),
                         ('H77', operator, 'Kaien 1', 'Austevoll', Decimal('60.100000'), Decimal('5.200000'),
                          [self.salmon], Decimal('120.5'), 'Pumps from boat', 'active'))
        listed = self.client.get(self.list_url)
        self.assertContains(listed, 'Approval number H77')
        self.assertEqual([item.name for item in self.client.get(self.list_url, {'species': self.salmon.pk})
                          .context['objects']], ['Hav Slakteri'])
        edit = reverse('farm:slaughterfacility_edit', args=[facility.pk])
        self.client.post(edit, {'name': 'Hav Slakteri', 'approval_number': 'H77', 'status': 'inactive', 'version': '1'})
        facility.refresh_from_db()
        self.assertEqual((facility.operator, facility.address, facility.municipality, facility.latitude,
                          facility.longitude, list(facility.species.all()), facility.capacity_tonnes_per_day,
                          facility.notes, facility.status), (None, '', '', None, None, [], None, '', 'inactive'))
        self.client.post(reverse('farm:slaughterfacility_delete', args=[facility.pk]))
        self.assertTrue(SlaughterFacility.all_objects.get(pk=facility.pk).is_deleted)
        self.assertEqual(sorted(AuditLog.objects.filter(entity_type='slaughter facility').values_list(
            'action', flat=True)), ['create', 'delete', 'update'])

    def test_the_rules_of_a_facility(self):
        create = reverse('farm:slaughterfacility_create')
        self.assertIn('approval_number', self.client.post(create, self.data(approval_number='M-1234'))
                      .context['form'].errors)
        self.assertEqual(self.client.post(create, self.data(approval_number='m123')).context['form']
                         .errors['approval_number'], ['Another slaughter facility already has this approval number.'])
        self.assertEqual(self.client.post(create, self.data(name='FJORD SLAKTERI')).context['form'].errors['name'],
                         ['Another slaughter facility already has this name.'])
        self.assertIn('longitude', self.client.post(create, self.data(longitude='')).context['form'].errors)
        self.assertIn('operator', self.client.post(create, self.data(operator=str(self.boat.pk)))
                      .context['form'].errors)
        self.assertIn('capacity_tonnes_per_day', self.client.post(create, self.data(capacity_tonnes_per_day='0'))
                      .context['form'].errors)

    def test_a_facility_harvests_went_to_is_set_inactive_not_deleted_and_its_suppliers_stay(self):
        operator = Supplier.objects.create(name='Fjord AS', code='FJ', supplies=['slaughter'])
        self.facility.operator = operator
        self.facility.save()
        self.harvest(count=10, transport=self.boat)
        plan = softdelete.plan_delete(self.facility)
        self.assertEqual(plan.blockers, ['1 harvest record still belongs to it. Set it inactive instead.'])
        self.client.post(reverse('farm:slaughterfacility_delete', args=[self.facility.pk]))
        self.assertFalse(SlaughterFacility.objects.get().is_deleted)
        self.assertEqual(softdelete.plan_delete(operator).blockers, ['1 slaughter facility still belongs to it.'])
        self.assertEqual(softdelete.plan_delete(self.boat).blockers, ['1 harvest record still belongs to it.'])
        self.boat.supplies = ['feed']
        with self.assertRaisesMessage(ValidationError, 'It carried 1 harvest: keep “Wellboat and transport” ticked.'):
            self.boat.full_clean()
        operator.supplies = ['feed']
        with self.assertRaisesMessage(ValidationError, 'It operates 1 slaughter facility: keep “Slaughter and '
                                                       'processing” ticked.'):
            operator.full_clean()

    def test_deleting_a_species_keeps_the_link_rows(self):
        self.facility.species.set([self.trout])
        plan = softdelete.plan_delete(self.trout)
        self.assertEqual(plan.unlinked, [self.facility])


class HandlingRuleTests(HarvestTestCase):
    list_url = reverse('farm:handlingrule_list')

    def post(self, rule=None, **fields):
        """What the rule dialog posts: an amount with its unit, the degree-days, the note."""
        data = {'kind': 'harvest', 'species': '', 'fasting_amount': '', 'fasting_unit': 'hours',
                'min_fasting_degree_days': '', 'note': '', **fields}
        if rule is None:
            return self.client.post(reverse('farm:handlingrule_create'), data)
        data.setdefault('version', str(HandlingRule.all_objects.get(pk=rule.pk).version))
        return self.client.post(reverse('farm:handlingrule_edit', args=[rule.pk]), data)

    def test_created_read_edited_and_deleted_through_the_pages(self):
        self.post(species=str(self.salmon.pk), fasting_amount='96', note='The vet, Nov 2026')
        rule = HandlingRule.objects.get(species=self.salmon)
        self.assertEqual((rule.kind, rule.min_fasting_hours, rule.min_fasting_degree_days, rule.note),
                         ('harvest', 96, None, 'The vet, Nov 2026'))
        listed = self.client.get(self.list_url, {'species': self.salmon.pk})
        self.assertEqual(list(listed.context['objects']), [rule])
        self.assertContains(listed, '4 days (96 h)')
        self.assertEqual(len(self.client.get(self.list_url, {'species': 'none'}).context['objects']), 4)
        self.assertContains(self.client.get(self.list_url), 'the starting values are to be checked with your '
                                                            'veterinarian')
        self.post(rule, kind='grading', species=str(self.salmon.pk), fasting_amount='0')
        rule.refresh_from_db()
        self.assertEqual((rule.kind, rule.min_fasting_hours, rule.note), ('grading', 0, ''))
        same = self.post(rule, kind='grading', species='', fasting_amount='5')
        self.assertEqual(same.context['form'].errors['species'],
                         ['There is already a rule for this handling and species.'])
        self.assertIn('fasting_amount', self.post(rule, kind='grading', fasting_amount='721').context['form'].errors)
        general = HandlingRule.objects.get(kind='treatment', species__isnull=True)
        self.post(general, kind='treatment', fasting_amount='12')
        general.refresh_from_db()
        self.assertEqual((general.min_fasting_hours, general.note), (12, ''))
        self.client.post(reverse('farm:handlingrule_delete', args=[rule.pk]))
        self.assertFalse(HandlingRule.objects.filter(pk=rule.pk).exists())
        with self.assertRaises(IntegrityError), transaction.atomic():
            HandlingRule.objects.create(kind='harvest', min_fasting_hours=1)
        self.assertEqual(softdelete.plan_delete(self.salmon).cascade, [])
        HandlingRule.objects.create(kind='harvest', species=self.trout, min_fasting_hours=1)
        self.assertEqual([str(record) for record in softdelete.plan_delete(self.trout).cascade],
                         ['Harvest · Rainbow trout'])

    def test_a_fast_is_typed_in_hours_or_days_and_stored_in_hours(self):
        # 5 days is 120 hours, shown back as 5 days.
        self.post(species=str(self.salmon.pk), fasting_amount='5', fasting_unit='days')
        rule = HandlingRule.objects.get(species=self.salmon)
        self.assertEqual(rule.min_fasting_hours, 120)
        edit = self.client.get(reverse('farm:handlingrule_edit', args=[rule.pk])).context['form']
        self.assertEqual((edit['fasting_amount'].value(), edit['fasting_unit'].value()), (5, 'days'))
        self.assertContains(self.client.get(self.list_url, {'species': self.salmon.pk}), '5 days (120 h)')
        # Edited in hours that are not whole days: kept as hours; whole days come back as days.
        self.post(rule, species=str(self.salmon.pk), fasting_amount='36', fasting_unit='hours')
        rule.refresh_from_db()
        self.assertEqual(rule.min_fasting_hours, 36)
        edit = self.client.get(reverse('farm:handlingrule_edit', args=[rule.pk])).context['form']
        self.assertEqual((edit['fasting_amount'].value(), edit['fasting_unit'].value()), (36, 'hours'))
        self.assertContains(self.client.get(self.list_url, {'species': self.salmon.pk}), '36 h')
        self.post(rule, species=str(self.salmon.pk), fasting_amount='48', fasting_unit='hours')     # whole days
        rule.refresh_from_db()
        edit = self.client.get(reverse('farm:handlingrule_edit', args=[rule.pk])).context['form']
        self.assertEqual((rule.min_fasting_hours, edit['fasting_amount'].value(), edit['fasting_unit'].value()),
                         (48, 2, 'days'))
        self.post(rule, species=str(self.salmon.pk), fasting_amount='1', fasting_unit='days')
        self.assertContains(self.client.get(self.list_url, {'species': self.salmon.pk}), '1 day (24 h)')
        # 0 is hours, never "0 days"; 30 days is the most (720 hours).
        self.post(rule, species=str(self.salmon.pk), fasting_amount='0', fasting_unit='days')
        edit = self.client.get(reverse('farm:handlingrule_edit', args=[rule.pk])).context['form']
        self.assertEqual((edit['fasting_amount'].value(), edit['fasting_unit'].value()), (0, 'hours'))
        self.post(rule, species=str(self.salmon.pk), fasting_amount='30', fasting_unit='days')
        self.assertEqual(HandlingRule.objects.get(pk=rule.pk).min_fasting_hours, 720)
        for amount, unit in (('31', 'days'), ('721', 'hours')):
            response = self.post(rule, species=str(self.salmon.pk), fasting_amount=amount, fasting_unit=unit)
            self.assertEqual(response.context['form'].errors['fasting_amount'], ['At most 720 hours (30 days).'])
        self.assertEqual(HandlingRule.objects.get(pk=rule.pk).min_fasting_hours, 720)

    def test_degree_days_are_the_harvests_alone_and_a_rule_needs_one_thing_or_the_other(self):
        # Degree-days only, hours only, and both, for a harvest.
        self.post(species=str(self.salmon.pk), min_fasting_degree_days='60')
        only = HandlingRule.objects.get(species=self.salmon)
        self.assertEqual((only.min_fasting_hours, only.min_fasting_degree_days), (None, Decimal('60.0')))
        edit = self.client.get(reverse('farm:handlingrule_edit', args=[only.pk])).context['form']
        self.assertEqual((edit['fasting_amount'].value(), edit['min_fasting_degree_days'].value()),
                         (None, Decimal('60.0')))
        listing = self.client.get(self.list_url, {'species': self.salmon.pk})
        self.assertContains(listing, '60 degree-days')
        self.post(only, species=str(self.salmon.pk), fasting_amount='3', fasting_unit='days',
                  min_fasting_degree_days='60.5')
        only.refresh_from_db()
        self.assertEqual((only.min_fasting_hours, only.min_fasting_degree_days), (72, Decimal('60.5')))
        self.assertContains(self.client.get(self.list_url, {'species': self.salmon.pk}),
                            '3 days (72 h) and 60.5 degree-days')
        self.post(only, species=str(self.salmon.pk), fasting_amount='72')                  # the degree-days cleared
        only.refresh_from_db()
        self.assertEqual((only.min_fasting_hours, only.min_fasting_degree_days), (72, None))
        # Nothing at all is refused, on the amount; so are degree-days for any other kind, and bad values.
        response = self.post(only, species=str(self.salmon.pk))
        self.assertEqual(response.context['form'].errors['fasting_amount'],
                         ['Give the fast in hours or days, in degree-days, or both.'])
        response = self.post(only, kind='transport', species=str(self.salmon.pk), fasting_amount='24',
                             min_fasting_degree_days='10')
        self.assertEqual(response.context['form'].errors['min_fasting_degree_days'],
                         ['Degree-days are for the harvest only: fish that are moved or graded are not purged.'])
        for value in ('-1', '1000.1', 'abc', '10.55'):
            with self.subTest(value=value):
                self.assertIn('min_fasting_degree_days',
                              self.post(only, species=str(self.salmon.pk), fasting_amount='72',
                                        min_fasting_degree_days=value).context['form'].errors)
        only.refresh_from_db()
        self.assertEqual((only.kind, only.min_fasting_hours, only.min_fasting_degree_days), ('harvest', 72, None))
        self.post(only, species=str(self.salmon.pk), fasting_amount='72', min_fasting_degree_days='1000')
        self.assertEqual(HandlingRule.objects.get(pk=only.pk).min_fasting_degree_days, Decimal('1000.0'))

    def test_the_database_holds_the_rules_too(self):
        def make(**fields):
            return HandlingRule.objects.create(species=self.trout, **fields)

        for fields in ({'kind': 'harvest'},                                                  # neither
                       {'kind': 'transport', 'min_fasting_hours': 24, 'min_fasting_degree_days': Decimal(10)},
                       {'kind': 'grading', 'min_fasting_degree_days': Decimal(10)},          # degree-days alone
                       {'kind': 'harvest', 'min_fasting_degree_days': Decimal(-1)},
                       {'kind': 'harvest', 'min_fasting_degree_days': Decimal('1000.1')},
                       {'kind': 'harvest', 'min_fasting_hours': 721},
                       {'kind': 'transport'}):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                make(**fields)
        make(kind='harvest', min_fasting_degree_days=Decimal(0))                            # 0 is a value
        make(kind='transport', min_fasting_hours=0)
        make(kind='grading', min_fasting_hours=720)
        HandlingRule.objects.create(kind='harvest', species=self.salmon, min_fasting_hours=72,
                                    min_fasting_degree_days=Decimal(1000))

    def test_the_page_speaks_each_language(self):
        self.addCleanup(translation.activate, 'en')
        rule = HandlingRule.objects.create(kind='harvest', species=self.salmon, min_fasting_hours=120,
                                           min_fasting_degree_days=Decimal(60))
        words = {'tr': ('5 gün (120 sa) ve 60 gün-derece', 'Arındırma', 'Birim'),
                 'nb': ('5 dager (120 t) og 60 døgngrader', 'Rensing', 'Enhet')}
        for language, (listed, purging, unit) in words.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            self.assertContains(self.client.get(self.list_url, {'species': self.salmon.pk}), listed, msg_prefix=language)
            form = self.client.get(reverse('farm:handlingrule_edit', args=[rule.pk]))
            self.assertContains(form, purging, msg_prefix=language)
            self.assertContains(form, unit, msg_prefix=language)
            self.assertNotContains(form, 'Purging', msg_prefix=language)


# ---- integrations --------------------------------------------------------------------------------------
class ActivityLogTests(HarvestTestCase):
    def test_critical_entries_have_their_badge_and_filter(self):
        self.fed(1, at=clock(18, 0))
        self.harvest(handling_ack=self.assess().fingerprint)
        page = self.client.get(reverse('core:activity_log'), {'severity': 'critical'})
        self.assertEqual([entry.severity for entry in page.context['page'].object_list], ['critical'])
        self.assertContains(page, '<span class="badge badge-critical">Critical</span>', html=True)
        everything = self.client.get(reverse('core:activity_log'), {'severity': 'loud'})
        self.assertGreater(len(everything.context['page'].object_list), 1)
        entry = AuditLog.objects.get(severity='critical')
        with self.assertRaises(IntegrityError), transaction.atomic():
            AuditLog.objects.create(user_name='x', action='create', entity_type='x', entity_id='1', entity_label='x',
                                    severity='loud')
        self.assertTrue(entry.pk)


class PermissionTests(HarvestTestCase):
    def as_role(self, *codenames):
        person = get_user_model().objects.create_user(f'p{len(codenames)}', f'p{len(codenames)}@example.com')
        person.groups.add(role(f'Role {len(codenames)}', *codenames))
        self.client.force_login(person)

    def test_each_page_needs_its_own_read_and_the_menu_places_them(self):
        pages = {'farm.view_harvestrecord': reverse('farm:harvests'),
                 'farm.view_handlingplanitem': reverse('farm:handlingplanitem_list'),
                 'farm.view_productionplan': reverse('farm:productionplan_list'),
                 'farm.view_slaughterfacility': reverse('farm:slaughterfacility_list'),
                 'farm.view_handlingrule': reverse('farm:handlingrule_list')}
        self.as_role('view_stockoperation')
        for url in pages.values():
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.as_role('view_harvestrecord', 'view_stockoperation')
        page = self.client.get(pages['farm.view_harvestrecord'])
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'class="ui-tabs"')                     # one page: no strip of tabs
        self.assertEqual(self.client.post(reverse('farm:handlingplanitem_create'), {}).status_code, 403)
        self.assertEqual([str(navigation.place(perm).path) for perm in pages], [
            'Production · Operations · Harvest', 'Production · Operations · Harvest',
            'Production · Operations · Harvest', 'Production · Setup · Harvest and logistics',
            'Production · Setup · Reference data'])
        areas = {area.model: area.actions for area in access.areas()}
        self.assertEqual((areas['farm.HarvestRecord'], areas['farm.HandlingPlanItem'], areas['farm.HandlingRule']),
                         (('view',), ('view', 'add', 'change', 'delete'), ('view', 'add', 'change', 'delete')))

    def test_record_from_a_plan_needs_the_stocks_create(self):
        HandlingPlanItem.objects.create(kind='harvest', date=self.today, unit=self.t1, batch=self.batch,
                                        facility=self.facility)
        self.as_role('view_handlingplanitem')
        self.assertNotContains(self.client.get(reverse('farm:handlingplanitem_list')), 'Record harvest')


class DatabaseViewerTests(HarvestTestCase):
    def test_the_harvest_tables_are_shown_with_their_descriptions(self):
        tables = {table.name: table for _, tables in database.sections() for table in tables}
        for name, start in (('slaughter_facilities', 'A slaughterhouse harvested fish go to'),
                            ('harvest_records', 'Where a harvest went'),
                            ('production_plans', "A batch's target"),
                            ('handling_plan_items', 'A harvest or a transport planned'),
                            ('handling_rules', 'How long the fish must have been without feed'),
                            ('handling_acknowledgements', 'One warning a person went on past'),
                            ('slaughter_facility_species', 'Which species each slaughter facility takes.')):
            self.assertTrue(str(tables[name].description).startswith(start), name)


class DeletePlanTests(HarvestTestCase):
    def test_a_unit_keeps_its_plans_out_of_sight_and_a_destination_is_cleared(self):
        self.harvest()                                                        # T-01 empty
        item = HandlingPlanItem.objects.create(kind='transport', date=self.today, unit=self.t2, batch=self.batch,
                                               destination_unit=self.t1)
        planned_from = HandlingPlanItem.all_objects.create(kind='transport', date=self.today, unit=self.t1,
                                                           batch=self.batch)
        plan = softdelete.plan_delete(Tank.objects.get(pk=self.t1.pk))
        self.assertEqual((plan.can_delete, plan.detach, dict(plan.kept)),
                         (True, [(item, 'destination_unit')], {HandlingPlanItem: 1}))
        self.client.force_login(get_user_model().objects.create_superuser('root', 'root@example.com', 'x'))
        self.client.post(reverse('farm:tank_delete', args=[self.t1.pk]))
        item.refresh_from_db()
        self.assertIsNone(item.destination_unit)
        self.assertFalse(HandlingPlanItem.objects.filter(pk=planned_from.pk).exists())
        self.assertTrue(HandlingPlanItem.all_objects.filter(pk=planned_from.pk, is_deleted=False).exists())
        self.assertTrue(StockMovement.objects.exists())
