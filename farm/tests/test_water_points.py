"""Sampling points: where in the water a sample is taken. The model and its database checks, the points a new unit or
system starts with, the tab (create, read, edit, delete through the pages against the stored rows), the delete plan and
restore, the one read of "the unit's water" and its fallback order, the dialog and the round that choose a point, the
history that says where each value was taken, permissions and languages."""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from core import access, database, navigation
from core.models import AuditLog, Profile
from core.softdelete import plan_delete, restore

from ..feeding.temperature import temperature_for
from ..models import Equipment, EquipmentSystem, EquipmentType, SamplingPoint, Site, System, Tank, WaterMeasurement
from ..models.water_point import (FLOW_ROLE, OUTLET_KINDS, STREAM_KINDS, FlowRole, PointKind, flow_role, kinds_for,
                                  kinds_with, site_of)
from ..resources.water_point import SamplingPointResource
from ..water import parameters, points, read, services
from ..water.evaluate import Status
from .helpers import point_of, role
from .test_stock import make_unit
from .test_water import WATER_KEEPER, WaterTestCase

D = Decimal
POINT_MANAGER = ('view_samplingpoint', 'add_samplingpoint', 'change_samplingpoint', 'delete_samplingpoint',
                 'view_tank', 'change_tank', 'delete_tank', 'view_system', 'delete_system', 'view_equipment',
                 'view_site', 'view_watermeasurement', 'view_auditlog')


class KindTests(SimpleTestCase):
    """The fixed list of kinds and what each means: one mapping, read everywhere."""

    def test_every_kind_has_one_flow_role_and_the_roles_are_the_ones_a_balance_reads(self):
        self.assertEqual(set(FLOW_ROLE), set(PointKind))
        self.assertEqual({kind.value: flow_role(kind).value for kind in PointKind},
                         {'inlet': 'in', 'middle': 'within', 'depth': 'within', 'outlet': 'out',
                          'side_outlet': 'out', 'bottom_drain': 'out'})
        self.assertEqual(kinds_with(FlowRole.IN), ['inlet'])
        self.assertEqual(kinds_with(FlowRole.OUT), ['outlet', 'side_outlet', 'bottom_drain'])
        self.assertEqual((STREAM_KINDS, OUTLET_KINDS), (['inlet', 'outlet', 'side_outlet', 'bottom_drain'],
                                                        ['outlet', 'side_outlet', 'bottom_drain']))
        self.assertEqual(flow_role('side_outlet'), FlowRole.OUT)

    def test_each_owner_can_have_the_kinds_that_make_sense_for_it(self):
        tank, pond, cage = (Tank(kind=kind) for kind in ('tank', 'pond', 'cage'))
        self.assertEqual([kind.value for kind in kinds_for(tank)],
                         ['inlet', 'middle', 'depth', 'outlet', 'side_outlet', 'bottom_drain'])
        self.assertEqual([kind.value for kind in kinds_for(pond)], ['inlet', 'middle', 'depth', 'outlet'])
        self.assertEqual([kind.value for kind in kinds_for(cage)], ['middle', 'depth'])
        self.assertEqual([kind.value for kind in kinds_for(System())], ['inlet', 'middle', 'outlet'])
        self.assertEqual([kind.value for kind in kinds_for(Equipment())], ['inlet', 'middle', 'outlet'])


class PointTestCase(WaterTestCase):
    """The water tests' farm (Bergen, Hall A, RAS 1 with T-01 and T-02, each with its points) and a pond, a cage and a
    piece of equipment."""

    def setUp(self):
        super().setUp()
        self.pond = make_unit('P-01', self.hall, 'pond')
        self.cage = Tank.objects.create(name='Cage 1', code='C-01', kind='cage', production_department=self.hall,
                                        water_type='saltwater', cage_type='floating', shape='circular',
                                        diameter=D(50), depth=D(20), max_density_kg_m3=D(20))
        self.filter = Equipment.objects.create(name='Drum filter', code='DF1', production_department=self.hall,
                                               equipment_type=EquipmentType.objects.filter(category='filtration').first())
        EquipmentSystem.objects.create(equipment=self.filter, system=self.ras, is_primary=True)

    def bare_system(self, code='R9'):
        return System.objects.create(name=f'System {code}', code=code, site=self.bergen)

    def named(self, owner, kind=None):
        owner_type = 'unit' if isinstance(owner, Tank) else 'system' if isinstance(owner, System) else 'equipment'
        found = SamplingPoint.objects.filter(**{owner_type: owner})
        return {point.name: point for point in (found.filter(kind=kind) if kind else found)}


# ---- the database -----------------------------------------------------------------------------------------
class ConstraintTests(PointTestCase):
    def refused(self, constraint, **values):
        with self.assertRaisesMessage(IntegrityError, constraint), transaction.atomic():
            SamplingPoint.objects.create(**values)

    def test_a_point_is_on_exactly_one_owner(self):
        self.refused('chk_water_sampling_points_one_owner', name='Nowhere', kind='middle')
        self.refused('chk_water_sampling_points_one_owner', name='Both', kind='middle', unit=self.pond,
                     system=self.bare_system())
        self.refused('chk_water_sampling_points_one_owner', name='All three', kind='middle', unit=self.pond,
                     system=self.bare_system('R8'), equipment=self.filter)

    def test_the_kind_is_from_the_list_and_the_name_is_not_empty(self):
        system = self.bare_system()
        self.refused('chk_water_sampling_points_kind', system=system, name='Sideways', kind='sideways')
        self.refused('chk_water_sampling_points_name', system=system, name='', kind='middle')

    def test_a_depth_belongs_to_a_depth_point_and_to_none_other(self):
        system = self.bare_system()
        self.refused('chk_water_sampling_points_depth', system=system, name='D', kind='depth')
        self.refused('chk_water_sampling_points_depth', system=system, name='Outlet', kind='outlet', depth_m=D(3))
        self.refused('chk_water_sampling_points_depth', unit=self.cage, name='Deep', kind='depth', depth_m=D(201))
        self.refused('chk_water_sampling_points_depth', unit=self.cage, name='Above', kind='depth', depth_m=D(-1))
        SamplingPoint.objects.create(unit=self.cage, name='3 m', kind='depth', depth_m=D('3.5'))

    def test_a_flow_is_for_the_points_on_a_stream_and_a_share_for_outlets(self):
        system = self.bare_system()
        self.refused('chk_water_sampling_points_flow', system=system, name='Mid', kind='middle', flow_m3_h=D(5))
        self.refused('chk_water_sampling_points_flow', system=system, name='In', kind='inlet', flow_m3_h=D(-1))
        self.refused('chk_water_sampling_points_flow', system=system, name='In', kind='inlet', flow_m3_h=D(100001))
        self.refused('chk_water_sampling_points_share', system=system, name='In', kind='inlet', flow_share_pct=D(10))
        self.refused('chk_water_sampling_points_share', system=system, name='Out', kind='outlet',
                     flow_share_pct=D('100.01'))
        self.refused('chk_water_sampling_points_share', system=system, name='Out', kind='outlet',
                     flow_share_pct=D(-1))
        SamplingPoint.objects.create(system=system, name='In', kind='inlet', flow_m3_h=D('1200.5'))
        SamplingPoint.objects.create(system=system, name='Out', kind='outlet', flow_m3_h=D(0), flow_share_pct=D(100))

    def test_a_name_is_unique_among_an_owners_live_points_whatever_its_case(self):
        for owner in (self.t1, self.ras, self.filter):
            with self.subTest(owner=owner.code):
                field = 'unit' if isinstance(owner, Tank) else 'system' if isinstance(owner, System) else 'equipment'
                first = SamplingPoint.objects.create(**{field: owner}, name='After the filter', kind='inlet')
                self.refused(f'uq_water_sampling_points_{field}_name', **{field: owner}, name='AFTER THE FILTER',
                             kind='outlet')
                first.soft_delete(self.user)                          # a deleted point frees its name
                SamplingPoint.objects.create(**{field: owner}, name='After the filter', kind='outlet')
        SamplingPoint.objects.create(unit=self.t2, name='After the filter', kind='outlet')       # another owner's

    def test_an_owner_has_one_active_middle_point_and_inactive_ones_stay(self):
        for field, owner in (('unit', self.pond), ('system', self.bare_system()), ('equipment', self.filter)):
            with self.subTest(owner=field):
                first = SamplingPoint.objects.create(**{field: owner}, name='Middle', kind='middle')
                self.refused(f'uq_water_sampling_points_{field}_middle', **{field: owner}, name='Probe 2',
                             kind='middle')
                first.is_active = False
                first.save()
                second = SamplingPoint.objects.create(**{field: owner}, name='Probe 2', kind='middle')
                self.assertEqual(read.middle_points([owner])[owner.pk], second)
                self.refused(f'uq_water_sampling_points_{field}_middle', **{field: owner}, name='Probe 3',
                             kind='middle')


class RuleTests(PointTestCase):
    """What no database check can say: a kind the owner can have, a depth the unit has, shares that add up."""

    def check(self, **values):
        point = SamplingPoint(**values)
        try:
            point.full_clean(exclude=['created_by', 'updated_by', 'deleted_by'], validate_unique=False,
                             validate_constraints=False)
        except ValidationError as error:
            return error.message_dict
        return {}

    def test_a_kind_the_owner_cannot_have_is_refused(self):
        self.assertEqual(self.check(unit=self.cage, name='Drain', kind='bottom_drain')['kind'],
                         ['C-01 cannot have a point of this kind: Middle, Depth point.'])
        self.assertEqual(self.check(system=self.ras, name='Drain', kind='bottom_drain')['kind'],
                         ['R1 cannot have a point of this kind: Inlet, Middle, Outlet.'])
        self.assertEqual(self.check(unit=self.t1, name='Extra inlet', kind='inlet'), {})

    def test_a_depth_point_has_a_depth_no_deeper_than_its_unit(self):
        self.assertEqual(self.check(unit=self.t1, name='Deep', kind='depth')['depth_m'], ['A depth point has a depth.'])
        self.assertEqual(self.check(unit=self.t1, name='Deep', kind='depth', depth_m=D('2.5'))['depth_m'],
                         ['T-01 is 2 m deep: the point cannot be deeper.'])
        self.assertEqual(self.check(unit=self.t1, name='1 m', kind='depth', depth_m=D(1)), {})
        self.assertEqual(self.check(unit=self.cage, name='20 m', kind='depth', depth_m=D(20)), {})

    def test_what_the_kind_does_not_use_is_emptied_not_kept(self):
        point = SamplingPoint(unit=self.t1, name='Inlet 2', kind='inlet', depth_m=D(1), flow_m3_h=D(4),
                              flow_share_pct=D(5))
        point.clean()
        self.assertEqual((point.depth_m, point.flow_m3_h, point.flow_share_pct), (None, D(4), None))

    def test_the_outlet_shares_of_an_owner_add_up_to_at_most_100(self):
        side, drain = self.named(self.t1, 'side_outlet')['Side outlet'], self.named(self.t1, 'bottom_drain')[
            'Bottom drain']
        side.flow_share_pct = D(90)
        side.save()
        drain.flow_share_pct = D(20)
        self.assertEqual(self.check(pk=drain.pk, unit=self.t1, name='Bottom drain', kind='bottom_drain',
                                    flow_share_pct=D(20)),
                         {'flow_share_pct': ['The outlets of T-01 would take 110 % of its outflow: at most 100.']})
        self.assertEqual(self.check(pk=drain.pk, unit=self.t1, name='Bottom drain', kind='bottom_drain',
                                    flow_share_pct=D(10)), {})
        # An inactive outlet takes no share; another owner's outlets are its own.
        side.is_active = False
        side.save()
        self.assertEqual(self.check(pk=drain.pk, unit=self.t1, name='Bottom drain', kind='bottom_drain',
                                    flow_share_pct=D(100)), {})
        self.assertEqual(self.check(unit=self.t2, name='Another', kind='outlet', flow_share_pct=D(100)), {})

    def test_an_owner_has_one_active_middle_point_said_on_the_kind(self):
        self.assertEqual(self.check(unit=self.t1, name='Probe', kind='middle')['kind'],
                         ['This owner already has an active middle point: it stands for its water.'])
        self.assertEqual(self.check(unit=self.t1, name='Probe', kind='middle', is_active=False), {})


class ShareNoteTests(PointTestCase):
    def test_an_owner_whose_outlet_shares_do_not_add_up_to_100_is_reported(self):
        side, drain = self.named(self.t1, 'side_outlet')['Side outlet'], self.named(self.t1, 'bottom_drain')[
            'Bottom drain']
        self.assertEqual(points.share_notes(), [])                    # nothing stated, nothing claimed
        SamplingPoint.objects.filter(pk=side.pk).update(flow_share_pct=D(90))
        (note,) = points.share_notes()
        self.assertEqual((note.owner, note.total, note.outlets, note.over), (self.t1, D(90), 1, False))
        SamplingPoint.objects.filter(pk=drain.pk).update(flow_share_pct=D(10))
        self.assertEqual(points.share_notes(), [])
        SamplingPoint.objects.filter(pk=drain.pk).update(flow_share_pct=D(30))      # only a raw update gets here
        (note,) = points.share_notes()
        self.assertEqual((note.total, note.over), (D(120), True))
        self.assertEqual(points.share_notes(self.bergen)[0].owner, self.t1)
        other = Site.objects.create(name='Tromso', code='TR')
        self.assertEqual(points.share_notes(other), [])


# ---- the points a new unit or system starts with ------------------------------------------------------------
class DefaultPointTests(PointTestCase):
    def kinds(self, owner):
        return sorted((point.kind, point.name) for point in self.named(owner).values())

    def test_each_kind_of_unit_and_a_system_starts_with_its_template(self):
        self.assertEqual(self.kinds(self.t1), [('bottom_drain', 'Bottom drain'), ('inlet', 'Inlet'),
                                               ('middle', 'Middle'), ('side_outlet', 'Side outlet')])
        self.assertEqual(self.kinds(self.pond), [])
        for owner in (self.pond, self.cage, self.bare_system(), self.filter):
            points.create_defaults(self.user, owner)
        self.assertEqual(self.kinds(self.pond), [('inlet', 'Inlet'), ('middle', 'Middle'), ('outlet', 'Outlet')])
        self.assertEqual(self.kinds(self.cage), [('middle', 'Middle')])
        self.assertEqual(self.kinds(System.objects.get(code='R9')), [('middle', 'Loop')])
        self.assertEqual(self.kinds(self.filter), [])               # the inlet and outlets of equipment are the person's

    def test_they_are_logged_like_any_change_and_made_once(self):
        created = points.create_defaults(self.user, self.pond)
        self.assertEqual(len(created), 3)
        entries = AuditLog.objects.filter(entity_type='sampling point', action='create')
        self.assertEqual(sorted(entry.entity_label for entry in entries), ['P-01 › Inlet', 'P-01 › Middle', 'P-01 › Outlet'])
        middle = entries.get(entity_label=str(self.named(self.pond, 'middle')['Middle']))
        self.assertEqual(middle.changes['Unit'], [None, str(self.pond)])
        self.assertEqual(middle.changes['Kind'], [None, {'msgid': 'Middle'}])
        self.assertEqual(points.create_defaults(self.user, self.pond), [])         # run again: nothing new
        self.assertEqual(SamplingPoint.objects.filter(unit=self.pond).count(), 3)
        renamed = self.named(self.pond, 'middle')['Middle']
        renamed.name = 'Bulk'
        renamed.save()
        self.assertEqual(points.create_defaults(self.user, self.pond), [])         # it has its middle point under another name

    def test_creating_a_unit_or_a_system_on_its_tab_makes_them_in_the_same_transaction(self):
        manager = get_user_model().objects.create_user('mia', 'mia@example.com', 'x')
        manager.groups.add(role('Structure', 'view_tank', 'add_tank', 'view_system', 'add_system', 'view_auditlog'))
        self.client.force_login(manager)
        response = self.client.post(reverse('farm:system_create'), {
            'name': 'New RAS', 'code': 'N1', 'type': 'ras', 'status': 'operational', 'site': str(self.bergen.pk),
            'production_department': '', 'parent': '', 'description': '', 'total_volume_m3': '', 'max_biomass_kg': ''})
        self.assertEqual(response.status_code, 302)
        system = System.objects.get(code='N1')
        (loop,) = SamplingPoint.objects.filter(system=system)
        self.assertEqual((loop.name, loop.kind, loop.created_by, loop.is_active), ('Loop', 'middle', manager, True))
        response = self.client.post(reverse('farm:tank_create'), {
            'name': 'New pond', 'code': 'np1', 'kind': 'pond', 'status': 'preparing', 'status_reason': '',
            'water_type': 'freshwater', 'regulatory_unit_id': '', 'production_department': str(self.hall.pk),
            'system': '', 'installation_date': '', 'description': '', 'notes': '', 'pond_type': 'earthen',
            'water_source': '', 'surface_area_m2': '1000', 'depth': '1.5', 'max_depth': '', 'water_depth': '',
            'liner_type': '', 'max_density_kg_m3': '3'})
        self.assertEqual(response.status_code, 302)
        unit = Tank.objects.get(code='NP1')
        self.assertEqual(sorted(SamplingPoint.objects.filter(unit=unit).values_list('kind', flat=True)),
                         ['inlet', 'middle', 'outlet'])
        log = list(AuditLog.objects.filter(entity_type__in=['system', 'unit', 'sampling point'], action='create')
                   .order_by('created_at').values_list('entity_type', 'entity_label'))
        self.assertEqual([kind for kind, _label in log], ['system', 'sampling point', 'unit'] + ['sampling point'] * 3)
        self.assertEqual((log[1][1], log[3][1]), ('N1 › Loop', 'NP1 › Inlet'))          # each after its own owner
        self.client.post(reverse('farm:tank_edit', args=[unit.pk]), {'name': 'Renamed', 'version': '1'})
        self.assertEqual(SamplingPoint.objects.filter(unit=unit).count(), 3)       # an edit makes no points


# ---- the tab -----------------------------------------------------------------------------------------------
class PointPageTests(PointTestCase):
    list_url = reverse('farm:samplingpoint_list')

    def setUp(self):
        super().setUp()
        self.manager = get_user_model().objects.create_user('mia', 'mia@example.com', 'x')
        self.manager.groups.add(role('Point manager', *POINT_MANAGER))
        self.client.force_login(self.manager)

    def data(self, **fields):
        values = {'owner_type': 'unit', 'unit': str(self.t1.pk), 'name': 'After the filter', 'kind': 'inlet',
                  'is_active': 'on', 'description': 'Behind the drum filter', 'flow_m3_h': '12.5'}
        values.update(fields)
        return values

    def test_create_read_edit_delete_through_the_pages_against_the_stored_rows(self):
        response = self.client.post(reverse('farm:samplingpoint_create'), self.data())
        self.assertEqual(response.status_code, 302)
        point = SamplingPoint.objects.get(name='After the filter')
        self.assertEqual((point.unit, point.system, point.equipment, point.kind, point.flow_m3_h, point.is_active,
                          point.description, point.depth_m, point.flow_share_pct, point.created_by, point.version),
                         (self.t1, None, None, 'inlet', D('12.50'), True, 'Behind the drum filter', None, None,
                          self.manager, 1))
        page = self.client.get(self.list_url)
        for text in ('After the filter', 'Behind the drum filter', 'T-01', 'Inlet', 'Stream in', '12.5',
                     '<h1>Sampling points</h1>'):
            self.assertContains(page, text, html=text.startswith('<'))
        form = self.client.get(reverse('farm:samplingpoint_edit', args=[point.pk])).context['form']
        self.assertEqual((form['name'].value(), form['kind'].value(), form['flow_m3_h'].value(),
                          form['owner_type'].value()), ('After the filter', 'inlet', D('12.50'), 'unit'))
        response = self.client.post(reverse('farm:samplingpoint_edit', args=[point.pk]),
                                    self.data(name='Filter outlet', kind='outlet', flow_m3_h='40', flow_share_pct='5',
                                              description='', version='1', is_active=''))
        self.assertEqual(response.status_code, 302)
        point.refresh_from_db()
        self.assertEqual((point.name, point.kind, point.flow_m3_h, point.flow_share_pct, point.description,
                          point.is_active, point.unit, point.version, point.updated_by),
                         ('Filter outlet', 'outlet', D('40.00'), D('5.00'), '', False, self.t1, 2, self.manager))
        self.client.post(reverse('farm:samplingpoint_delete', args=[point.pk]))
        self.assertTrue(SamplingPoint.all_objects.get(pk=point.pk).is_deleted)
        self.assertEqual(list(AuditLog.objects.filter(entity_type='sampling point', entity_id=str(point.pk))
                              .order_by('created_at').values_list('action', flat=True)),
                         ['create', 'update', 'delete'])
        update = AuditLog.objects.get(entity_type='sampling point', entity_id=str(point.pk), action='update')
        self.assertEqual(update.changes['Name'], ['After the filter', 'Filter outlet'])
        self.assertEqual(update.changes['Active'], [{'msgid': 'Yes'}, {'msgid': 'No'}])

    def test_every_field_of_the_form_is_a_column(self):
        form = self.client.get(reverse('farm:samplingpoint_create'), {'unit': self.t1.pk}).context['form']
        self.assertEqual(form['unit'].value(), self.t1.pk)             # opened from the unit's page
        columns = {field.name for field in SamplingPoint._meta.concrete_fields}
        every = set()
        for owner_type, owner in (('unit', self.t1), ('system', self.ras), ('equipment', self.filter)):
            for kind in PointKind:
                posted = self.client.post(reverse('farm:samplingpoint_create'),
                                          {'owner_type': owner_type, owner_type: str(owner.pk), 'kind': kind.value,
                                           '_draft': 'kind'}).context['form']
                every |= set(posted.fields)
        # Every field the form can show is a column, except the one that only says which owner field to show; and every
        # column a person fills in is on the form.
        self.assertEqual(sorted(every - columns), ['owner_type'])
        self.assertEqual(columns - every, {'id', 'created_at', 'updated_at', 'created_by', 'updated_by', 'is_deleted',
                                           'deleted_at', 'deleted_by'})
        self.assertEqual(list(SamplingPointResource.snapshot(self.named(self.t1)['Inlet'])),
                         ['Unit', 'System', 'Equipment', 'Name', 'Kind', 'Depth (m)', 'Flow (m³/h)',
                          'Share of the outflow (%)', 'Active', 'Description'])

    def test_the_form_offers_the_owner_the_kinds_it_can_have_and_the_fields_the_kind_uses(self):
        draft = lambda **fields: self.client.post(reverse('farm:samplingpoint_create'), {'_draft': 'kind', **fields}
                                                  ).context['form']
        form = draft(owner_type='unit', unit=str(self.cage.pk), kind='')
        self.assertEqual([value for value, _label in form.fields['kind'].choices], ['', 'middle', 'depth'])
        self.assertEqual({'depth_m', 'flow_m3_h', 'flow_share_pct'} & set(form.fields), set())
        self.assertEqual({'depth_m', 'flow_m3_h', 'flow_share_pct'} & set(draft(
            owner_type='unit', unit=str(self.cage.pk), kind='depth').fields), {'depth_m'})
        self.assertEqual({'depth_m', 'flow_m3_h', 'flow_share_pct'} & set(draft(
            owner_type='unit', unit=str(self.t1.pk), kind='side_outlet').fields), {'flow_m3_h', 'flow_share_pct'})
        form = draft(owner_type='system', system=str(self.ras.pk), kind='inlet')
        self.assertEqual(('unit' in form.fields, 'equipment' in form.fields, 'system' in form.fields), (False, False, True))
        self.assertEqual(SamplingPoint.objects.filter(name='x').count(), 0)

    def test_the_owner_is_chosen_once_and_the_rules_land_on_their_fields(self):
        created = self.client.post(reverse('farm:samplingpoint_create'),
                                   self.data(owner_type='system', system=str(self.ras.pk), unit='', kind='middle',
                                             name='Sump', flow_m3_h=''))
        self.assertEqual(created.context['form'].errors['kind'],
                         ['This owner already has an active middle point: it stands for its water.'])
        response = self.client.post(reverse('farm:samplingpoint_create'), self.data(name='inlet'))
        self.assertEqual(response.context['form'].errors['name'], ['This owner already has a point with this name.'])
        response = self.client.post(reverse('farm:samplingpoint_create'),
                                    self.data(unit=str(self.cage.pk), kind='bottom_drain', name='Drain'))
        self.assertIn('kind', response.context['form'].errors)          # a cage's form does not offer a bottom drain
        response = self.client.post(reverse('farm:samplingpoint_create'), self.data(unit='', name='Nowhere'))
        self.assertIn('unit', response.context['form'].errors)
        response = self.client.post(reverse('farm:samplingpoint_create'),
                                    self.data(kind='depth', name='Deep', depth_m='3', flow_m3_h=''))
        self.assertEqual(response.context['form'].errors['depth_m'], ['T-01 is 2 m deep: the point cannot be deeper.'])
        for fields, field in (({'flow_m3_h': '-3'}, 'flow_m3_h'), ({'flow_m3_h': '100001'}, 'flow_m3_h'),
                              ({'kind': 'outlet', 'flow_share_pct': '101', 'name': 'Out'}, 'flow_share_pct'),
                              ({'kind': 'depth', 'depth_m': '201', 'name': 'Deep'}, 'depth_m')):
            response = self.client.post(reverse('farm:samplingpoint_create'), self.data(**fields))
            self.assertIn(field, response.context['form'].errors, fields)
        self.assertEqual(SamplingPoint.objects.filter(name__in=['After the filter', 'Out', 'Deep']).count(), 0)
        point = self.named(self.t1, 'inlet')['Inlet']
        form = self.client.get(reverse('farm:samplingpoint_edit', args=[point.pk])).context['form']
        self.assertTrue(all(form.fields[name].disabled for name in ('owner_type', 'unit')))
        self.client.post(reverse('farm:samplingpoint_edit', args=[point.pk]),
                         self.data(unit=str(self.t2.pk), name='Inlet', kind='inlet', version='1'))
        self.assertEqual(SamplingPoint.objects.get(pk=point.pk).unit, self.t1)       # the owner does not move

    def test_the_shares_of_an_owners_outlets_are_refused_above_100_and_reported_below(self):
        side, drain = self.named(self.t1, 'side_outlet')['Side outlet'], self.named(self.t1, 'bottom_drain')['Bottom drain']
        edit = lambda point, share, **extra: self.client.post(
            reverse('farm:samplingpoint_edit', args=[point.pk]),
            self.data(name=point.name, kind=point.kind, flow_share_pct=share, flow_m3_h='', version=str(point.version),
                      **extra))
        self.assertEqual(edit(side, '90').status_code, 302)
        page = self.client.get(self.list_url)
        self.assertContains(page, 'The outlets of T-01 take 90 % of its outflow, not 100 %.')
        response = edit(drain, '20')
        self.assertEqual(response.context['form'].errors['flow_share_pct'],
                         ['The outlets of T-01 would take 110 % of its outflow: at most 100.'])
        self.assertIsNone(SamplingPoint.objects.get(pk=drain.pk).flow_share_pct)
        self.assertEqual(edit(drain, '10').status_code, 302)
        self.assertNotContains(self.client.get(self.list_url), 'of its outflow')
        # Raised through two forms at once the sum can pass 100 (no check spans rows): the list says so.
        SamplingPoint.objects.filter(pk=drain.pk).update(flow_share_pct=D(30))
        self.assertContains(self.client.get(self.list_url), 'more than 100 %')

    def test_the_list_filters_by_site_owner_and_kind_and_narrows_to_one_owner(self):
        tromso = Site.objects.create(name='Tromso', code='TR')
        names = lambda **query: [(point.owner.code, point.name) for point in
                                 self.client.get(self.list_url, query).context['objects']]
        point_of(self.pond)
        self.assertEqual(names(owner_type='unit', kind='inlet'), [('P-01', 'Inlet'), ('T-01', 'Inlet'), ('T-02', 'Inlet')])
        self.assertEqual(names(owner_type='system'), [('R1', 'Loop')])
        self.assertEqual(names(owner_type='equipment'), [])
        self.assertEqual(names(unit=self.t1.pk, kind='side_outlet'), [('T-01', 'Side outlet')])
        self.assertEqual([name for _code, name in names(unit=self.t2.pk)],
                         ['Inlet', 'Middle', 'Side outlet', 'Bottom drain'])        # in the order of the kinds
        self.assertEqual(len(names(site=self.bergen.pk)), 12)
        self.assertEqual(names(site=tromso.pk), [])
        self.assertEqual(len(names(site='not-a-site', kind='sideways', owner_type='x')), 12)
        self.assertEqual([code for code, _name in names(q='side')], ['T-01', 'T-02'])
        page = self.client.get(self.list_url, {'unit': self.t2.pk})
        self.assertContains(page, 'The points of T-02.')
        self.assertContains(page, f'{reverse("farm:samplingpoint_create")}?unit={self.t2.pk}')

    def test_the_unit_system_and_equipment_pages_link_to_their_points(self):
        for url, param, owner in (('farm:tank_list', 'unit', self.t1), ('farm:system_list', 'system', self.ras),
                                  ('farm:equipment_list', 'equipment', self.filter)):
            self.assertContains(self.client.get(reverse(url)), f'{self.list_url}?{param}={owner.pk}')
        only_units = get_user_model().objects.create_user('sam', 'sam@example.com', 'x')
        only_units.groups.add(role('Only units', 'view_tank'))
        self.client.force_login(only_units)
        self.assertNotContains(self.client.get(reverse('farm:tank_list')), self.list_url)

    def test_a_point_is_added_to_a_piece_of_equipment_and_a_sample_taken_there(self):
        for name, kind in (('Inlet', 'inlet'), ('Clean outlet', 'outlet'), ('Backwash', 'outlet')):
            response = self.client.post(reverse('farm:samplingpoint_create'),
                                        {'owner_type': 'equipment', 'equipment': str(self.filter.pk), 'name': name,
                                         'kind': kind, 'is_active': 'on', 'description': ''})
            self.assertEqual(response.status_code, 302, response.context and response.context['form'].errors)
        self.assertEqual(sorted(self.named(self.filter)), ['Backwash', 'Clean outlet', 'Inlet'])
        self.assertEqual(site_of(self.named(self.filter)['Inlet']), self.bergen)

    def test_the_tab_has_its_menu_entry_area_and_activity_log_name(self):
        self.assertEqual(str(navigation.place('farm.view_samplingpoint').path), 'Production · Setup · Facility structure')
        areas = {area.model: area for area in access.areas()}
        self.assertEqual((str(areas['farm.SamplingPoint'].label), areas['farm.SamplingPoint'].actions),
                         ('Sampling points', ('view', 'add', 'change', 'delete')))
        self.assertContains(self.client.get(reverse('farm:system_list')), self.list_url)
        self.assertEqual(SamplingPointResource.entity_type(), 'sampling point')

    def test_the_tab_is_in_the_database_viewer_and_the_admin(self):
        tables = {table.name: table for _, tables in database.sections() for table in tables}
        self.assertTrue(tables['water_sampling_points'].description.startswith('Where a water sample is taken'))
        structure = tables['water_sampling_points'].structure()
        self.assertTrue({'chk_water_sampling_points_one_owner', 'chk_water_sampling_points_share',
                         'chk_water_sampling_points_depth'} <= {constraint.name for constraint in structure.constraints})
        self.assertTrue({'uq_water_sampling_points_unit_middle', 'uq_water_sampling_points_system_name'}
                        <= {index.name for index in structure.indexes})
        admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse('core:database_table', args=['water_sampling_points'])).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:farm_samplingpoint_changelist')).status_code, 200)
        self.mid1.soft_delete(admin)
        self.assertContains(self.client.get(reverse('admin:farm_samplingpoint_changelist')), 'Middle')
        self.client.post(reverse('admin:farm_samplingpoint_changelist'), {
            'action': 'restore', '_selected_action': [str(self.mid1.pk)]})
        self.assertFalse(SamplingPoint.all_objects.get(pk=self.mid1.pk).is_deleted)


class PointPermissionTests(PointTestCase):
    def as_role(self, *codenames):
        name = uuid.uuid4().hex[:8]
        person = get_user_model().objects.create_user(name, f'{name}@example.com')
        person.groups.add(role(f'Role {name}', *codenames))
        self.client.force_login(person)

    def test_read_add_edit_and_delete_are_separate(self):
        point = self.named(self.t1, 'inlet')['Inlet']
        urls = {'create': reverse('farm:samplingpoint_create'), 'edit': reverse('farm:samplingpoint_edit', args=[point.pk]),
                'delete': reverse('farm:samplingpoint_delete', args=[point.pk])}
        self.as_role('view_tank')
        self.assertEqual(self.client.get(reverse('farm:samplingpoint_list')).status_code, 403)
        self.as_role('view_samplingpoint')
        page = self.client.get(reverse('farm:samplingpoint_list'))
        self.assertEqual(page.status_code, 200)
        for text in (urls['create'], urls['edit'], urls['delete']):
            self.assertNotContains(page, text)
        for url in urls.values():
            self.assertEqual(self.client.post(url, {}).status_code, 403, url)
        self.as_role('view_samplingpoint', 'change_samplingpoint')
        self.assertEqual(self.client.get(urls['edit']).status_code, 200)
        self.assertEqual(self.client.post(urls['delete']).status_code, 403)
        self.as_role('view_samplingpoint', 'delete_samplingpoint')
        self.assertEqual(self.client.get(urls['edit']).status_code, 403)
        self.client.post(urls['delete'])
        self.assertTrue(SamplingPoint.all_objects.get(pk=point.pk).is_deleted)

    def test_a_person_without_read_has_no_menu_entry(self):
        self.as_role('view_tank')
        self.assertNotContains(self.client.get(reverse('production_home')), reverse('farm:samplingpoint_list'))


# ---- deleting ------------------------------------------------------------------------------------------------
class DeleteTests(PointTestCase):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(self.admin)

    def test_a_point_with_samples_is_not_deleted_and_is_made_inactive_instead(self):
        inlet = self.named(self.t1, 'inlet')['Inlet']
        self.sample(point=inlet, ph='7')
        voided = self.sample(point=inlet, hours=2, ph='7.1')
        services.void(self.user, voided, 'Typo')
        plan = plan_delete(inlet)
        self.assertEqual(plan.blockers, ['It has 2 water samples in the history: make it inactive instead.'])
        page = self.client.get(reverse('farm:samplingpoint_delete', args=[inlet.pk]))
        self.assertContains(page, 'It has 2 water samples in the history: make it inactive instead.')
        response = self.client.post(reverse('farm:samplingpoint_delete', args=[inlet.pk]), follow=True)
        self.assertContains(response, 'cannot be deleted: It has 2 water samples in the history')
        self.assertFalse(SamplingPoint.all_objects.get(pk=inlet.pk).is_deleted)
        self.assertEqual(WaterMeasurement.all_objects.filter(point=inlet).count(), 2)
        self.client.post(reverse('farm:samplingpoint_edit', args=[inlet.pk]), {
            'owner_type': 'unit', 'unit': str(self.t1.pk), 'name': 'Inlet', 'kind': 'inlet', 'description': '',
            'flow_m3_h': '', 'version': '1'})                                                # is_active left out: off
        inlet.refresh_from_db()
        self.assertFalse(inlet.is_active)
        history = self.client.get(reverse('farm:water'), {'point': inlet.pk})
        self.assertEqual(len(history.context['history']), 2)                                # the history stays
        self.assertEqual(self.refused(services.record, self.user, point=inlet, measured_at=self.ago(hours=1),
                                      source='manual', values={'ph': D(7)}),
                         {'point': ['T-01 › Inlet is inactive: it takes no new samples.']})

    def test_a_point_without_samples_is_deleted_logged_and_frees_its_name(self):
        outlet = self.named(self.t1, 'side_outlet')['Side outlet']
        plan = plan_delete(outlet)
        self.assertEqual((plan.can_delete, plan.blockers, plan.kept_groups()), (True, [], []))
        self.client.post(reverse('farm:samplingpoint_delete', args=[outlet.pk]))
        self.assertTrue(SamplingPoint.all_objects.get(pk=outlet.pk).is_deleted)
        self.assertNotIn(outlet, SamplingPoint.objects.all())
        self.assertTrue(AuditLog.objects.filter(entity_type='sampling point', action='delete',
                                                entity_id=str(outlet.pk)).exists())
        SamplingPoint.objects.create(unit=self.t1, name='Side outlet', kind='side_outlet')
        restore_error = None
        try:
            restore(SamplingPoint.all_objects.get(pk=outlet.pk), self.admin)
        except ValidationError as error:
            restore_error = error.messages
        self.assertEqual(restore_error, ['This owner already has a point with this name.'])      # taken meanwhile

    def test_deleting_the_owner_keeps_its_points_and_their_samples_out_of_sight_and_restore_brings_them_back(self):
        self.sample(point=self.named(self.t2, 'inlet')['Inlet'], ph='7')
        self.sample(point=self.t2, hours=2, ph='7.1')
        self.sample(point=self.loop, co2_mg_l='9')
        self.assertEqual(plan_delete(self.ras).kept_groups(),
                         [{'label': 'Sampling points', 'count': 1, 'note': SamplingPoint.kept_note},
                          {'label': 'Water samples', 'count': 1, 'note': WaterMeasurement.kept_note}])
        self.ras.soft_delete(self.admin)
        self.assertEqual(SamplingPoint.objects.filter(system=self.ras).count(), 0)
        self.assertEqual(WaterMeasurement.objects.filter(point__system=self.ras).count(), 0)
        self.assertEqual(read.middle_points([self.ras]), {})
        restore(System.all_objects.get(pk=self.ras.pk), self.admin)
        self.assertEqual(SamplingPoint.objects.filter(system=self.ras).count(), 1)
        self.assertEqual(WaterMeasurement.objects.filter(point__system=self.ras).count(), 1)
        # A unit: the points, the samples at them, the unit's water and the history all come back with it.
        self.t2.soft_delete(self.admin)
        self.assertEqual(read.unit_water([self.t2])[self.t2.pk].readings, {})
        history = self.client.get(reverse('farm:water'), {'view': 'history'}).context['history']
        self.assertEqual([row.sample.point.owner.code for row in history], ['R1'])
        restore(Tank.all_objects.get(pk=self.t2.pk), self.admin)
        self.assertEqual(self.unit_water(self.t2).get('ph').value, D('7.10'))      # never its inlet's (A9.1)
        history = self.client.get(reverse('farm:water'), {'view': 'history'}).context['history']
        self.assertEqual(sorted(row.sample.point.owner.code for row in history), ['R1', 'T-02', 'T-02'])

    def test_the_equipments_points_stay_with_it_too(self):
        inlet = point_of(self.filter, 'inlet')
        self.sample(point=inlet, ph='7')
        self.assertEqual(plan_delete(self.filter).kept_groups(),
                         [{'label': 'Sampling points', 'count': 1, 'note': SamplingPoint.kept_note},
                          {'label': 'Water samples', 'count': 1, 'note': WaterMeasurement.kept_note}])
        self.filter.soft_delete(self.admin)
        self.assertEqual(SamplingPoint.objects.filter(equipment=self.filter).count(), 0)
        self.assertEqual(self.refused(services.record, self.user, point=inlet, measured_at=self.ago(hours=1),
                                      source='manual', values={'ph': D(7)}), {'point': ['DF1 is deleted.']})


# ---- reading "the unit's water" ---------------------------------------------------------------------------
class ReadTests(PointTestCase):
    def test_the_water_of_a_unit_is_its_points_and_the_loop_stands_in_for_what_it_has_none_of(self):
        """Owner rule A9 (2026-11-07), A9.1 "its own sampling points" (owner, 2026-11-08): every active point that
        measures the unit's own water (the middle, a depth point, an outlet, a drain) is its own, the newest fresh value
        among them wins (at one time the middle first, then by name); an inlet is the supply stream, not the unit's
        water, and never counts; its loop's fresh sample stands in only for a parameter the unit has nothing fresh of."""
        self.sample(point=self.named(self.t1, 'inlet')['Inlet'], hours=1, temperature_c='15', ph='6.1')
        self.sample(point=self.named(self.t1, 'side_outlet')['Side outlet'], hours=1, temperature_c='11')
        self.sample(point=self.t1, hours=3, temperature_c='9.5', co2_mg_l='8')
        self.sample(point=self.loop, hours=1, temperature_c='12', ph='7.3', oxygen_mg_l='9')
        water = read.unit_water([self.t1, self.t2, self.pond])
        outlet = self.named(self.t1, 'side_outlet')['Side outlet']
        self.assertEqual((water[self.t1.pk].point, water[self.t1.pk].get('temperature_c').value,
                          water[self.t1.pk].get('ph').value, water[self.t1.pk].get('ph').point),
                         (self.mid1, D('11.0'), D('7.30'), self.loop))   # its outlet's, newer; the inlet's pH is not its
        self.assertEqual(water[self.t1.pk].get('co2_mg_l').point, self.mid1)
        self.assertEqual(water[self.t1.pk].get('oxygen_mg_l').point, self.loop)   # none of its own: the loop's
        self.assertEqual((water[self.t2.pk].point, water[self.t2.pk].get('temperature_c').value),
                         (self.mid2, D('12.0')))                                   # nothing of its own: the loop's
        self.assertEqual((water[self.pond.pk].point, water[self.pond.pk].readings, water[self.pond.pk].status),
                         (None, {}, Status.NOT_MEASURED))
        self.assertEqual(water[self.t1.pk].get('temperature_c').point, outlet)

    def test_the_sources_of_a_units_temperature_are_its_middle_point_then_its_loops(self):
        parent = System.objects.create(name='Parent', code='PR', site=self.bergen)
        System.objects.filter(pk=self.ras.pk).update(parent=parent)
        self.ras.refresh_from_db()
        parent_loop = point_of(parent)
        sources = lambda unit, nested: [(source.via, source.owner.code, source.point.name)
                                        for source in read.water_sources([unit], nested=nested)[unit.pk]]
        self.assertEqual(sources(self.t1, True), [('unit', 'T-01', 'Middle'), ('system', 'R1', 'Loop'),
                                                  ('system', 'PR', 'Loop')])
        self.assertEqual(sources(self.t1, False), [('unit', 'T-01', 'Middle'), ('system', 'R1', 'Loop')])
        every = [(source.via, source.owner.code, source.point.name)
                 for source in read.water_sources([self.t1], nested=False, every_point=True)[self.t1.pk]]
        self.assertEqual(every, [('unit', 'T-01', 'Middle'), ('unit', 'T-01', 'Bottom drain'),
                                 ('unit', 'T-01', 'Side outlet'), ('system', 'R1', 'Loop')])
        # A9.1: every point of the unit's own water, the middle first; never its inlet (the supply stream)
        self.assertEqual(sources(self.pond, True), [])                      # in no system, no point of its own
        SamplingPoint.objects.filter(pk=self.mid1.pk).update(is_active=False)
        self.assertEqual(sources(self.t1, False), [('system', 'R1', 'Loop')])      # an inactive point is not a source
        Tank.objects.filter(pk=self.t1.pk).update(system=None)
        self.t1.refresh_from_db()
        self.assertEqual(sources(self.t1, True), [])
        del parent_loop

    def test_the_feeding_temperature_follows_that_order(self):
        self.sample(point=self.loop, hours=2, temperature_c='12')
        self.sample(point=self.t1, hours=40, temperature_c='13')                  # its own, but stale
        self.sample(point=self.named(self.t1, 'inlet')['Inlet'], hours=1, temperature_c='20')   # a stream, not the unit's
        now = timezone.now()
        found = temperature_for([self.t1, self.t2], now)
        self.assertEqual((found[self.t1.pk].value_c, found[self.t1.pk].via, found[self.t1.pk].point),
                         (D('12.0'), 'system', self.ras))                         # the loop's fresh one wins
        self.assertEqual((found[self.t2.pk].value_c, found[self.t2.pk].via), (D('12.0'), 'system'))
        drain = self.named(self.t1, 'bottom_drain')['Bottom drain']
        self.sample(point=drain, hours=1, temperature_c='9')                     # the unit's own water (A9.1), fresh
        found = temperature_for([self.t1], now)[self.t1.pk]
        self.assertEqual((found.value_c, found.via, found.point, found.sampling_point, found.fresh),
                         (D('9.0'), 'unit', self.t1, drain, True))

    def test_the_withdrawals_daily_mean_reads_the_same_places(self):
        from ..water.degree_days import Temperatures
        from ..stock.dates import local_today
        today = local_today(self.t1)
        # Taken now, not an hour ago: in the first hour of the farm's day an hour ago is yesterday's daily mean.
        self.sample(point=self.named(self.t1, 'inlet')['Inlet'], hours=0, temperature_c='20')
        self.sample(point=self.t1, hours=0, temperature_c='8')
        self.sample(point=self.loop, hours=0, temperature_c='11')
        temperatures = Temperatures([self.t1, self.t2], today - timedelta(days=1), today)
        self.assertEqual(temperatures.of(self.t1.pk, today), D(8))                # the unit's own, not the inlet's
        self.assertEqual(temperatures.of(self.t2.pk, today), D(11))               # else its system's loop
        self.assertIsNone(temperatures.of(self.t2.pk, today - timedelta(days=1)))

    def test_the_calculator_takes_the_values_of_a_unit_or_a_loop_from_its_middle_point(self):
        from ..water import calculation
        self.stock(self.t1)
        self.limit('co2_mg_l', critical_high=15)
        self.sample(point=self.named(self.t1, 'inlet')['Inlet'], hours=1, temperature_c='15', ph='6.1')
        self.sample(point=self.t1, hours=2, temperature_c='9.5', ph='7.2')
        self.sample(point=self.loop, hours=1, alkalinity_mg_l='90', salinity_ppt='0.5')
        offers = calculation.offers(self.t1)
        self.assertEqual((offers['temperature_c'].value, offers['ph'].value, offers['co2_limit_mg_l'].value),
                         (D('9.5'), D('7.20'), D(15)))                    # never its inlet's (the supply stream)
        self.assertEqual(offers['temperature_c'].reading.point, self.mid1)
        self.assertEqual(offers['alkalinity_mg_l'].reading.point, self.loop)   # A9: the loop stands in for what the unit lacks
        self.assertEqual(offers['altitude_m'].value, D(0))
        loop = calculation.offers(self.ras)
        self.assertEqual((loop['alkalinity_mg_l'].value, loop['salinity_ppt'].value, 'ph' in loop),
                         (D(90), D('0.5'), False))
        bare = calculation.offers(self.pond)                            # no point at all: no readings, the site's altitude
        self.assertEqual(set(bare), {'altitude_m'})

    def test_there_is_one_implementation_of_the_units_water(self):
        """The feeding temperature and the withdrawal ask farm/water/read.py's `water_sources`, and no module outside
        the water module reads the samples: the places a unit's water is read from are defined once."""
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        for module in ('feeding/temperature.py', 'water/degree_days.py'):
            self.assertIn('water_sources(', (root / module).read_text(encoding='utf-8'), module)
        readers = sorted(path.relative_to(root).as_posix() for path in root.rglob('*.py')
                         if not {'water', 'tests', 'migrations'} & set(path.relative_to(root).parts)
                         and 'WaterMeasurement' in path.read_text(encoding='utf-8'))
        self.assertEqual(readers, ['admin.py', 'forms/water.py', 'models/__init__.py', 'models/water.py',
                                   'models/water_point.py', 'screens.py'])    # the sample's form and its data-map
        # declaration name its model, they read nothing

    def test_a_samples_salinity_falls_back_to_its_points_then_its_owners_middle_point(self):
        Tank.objects.filter(pk=self.t1.pk).update(water_type='saltwater')
        self.t1.refresh_from_db()
        inlet = self.named(self.t1, 'inlet')['Inlet']
        self.sample(point=self.t1, hours=24 * 3, salinity_ppt='33')
        self.sample(point=inlet, hours=2, tan_mg_l='1', ph='8', temperature_c='10')
        nh3 = read.latest([inlet])[inlet.pk].get('nh3_n_mg_l')
        self.assertIsNotNone(nh3.value)                                           # the owner's middle point's salinity
        self.sample(point=inlet, hours=24 * 2, salinity_ppt='20')
        self.assertNotEqual(read.latest([inlet])[inlet.pk].get('nh3_n_mg_l').value, nh3.value)   # the point's own first

    def test_a_pieces_of_equipments_sample_is_judged_for_the_fish_of_the_systems_it_serves(self):
        self.stock(self.t1)
        self.limit('co2_mg_l', warning_high=15, critical_high=20)
        inlet = point_of(self.filter, 'inlet')
        self.sample(point=inlet, hours=1, co2_mg_l='25')
        reading = read.latest([inlet])[inlet.pk].get('co2_mg_l')
        self.assertEqual((reading.status, [row.species for row in reading.limits]), (Status.CRITICAL, [self.salmon]))
        self.assertEqual(read.limits_now(inlet)['co2_mg_l'][0].species, self.salmon)
        unserved = Equipment.objects.create(name='Lamp', code='LP1', production_department=self.hall,
                                            equipment_type=self.filter.equipment_type)
        point = point_of(unserved, 'inlet')
        self.sample(point=point, hours=1, co2_mg_l='25')
        self.assertEqual(read.latest([point])[point.pk].get('co2_mg_l').status, Status.NO_LIMIT)

    def test_the_history_of_a_point_an_owner_and_a_site_is_one_query(self):
        inlet = self.named(self.t1, 'inlet')['Inlet']
        a = self.sample(point=inlet, hours=1, ph='7')
        b = self.sample(point=self.t1, hours=2, ph='7.1')
        c = self.sample(point=self.loop, hours=3, co2_mg_l='9')
        d = self.sample(point=self.t2, hours=4, ph='7.2')
        services.void(self.user, d, 'Wrong unit')
        ids = lambda **where: [sample.pk for sample in read.samples_of(**where)]
        self.assertEqual(ids(points=[inlet]), [a.pk])
        self.assertEqual(ids(owner=self.t1), [a.pk, b.pk])
        self.assertEqual(ids(owner=self.ras), [c.pk])
        self.assertEqual(ids(site=self.bergen), [a.pk, b.pk, c.pk, d.pk])         # a voided one stays in the history
        self.assertEqual(ids(site=self.bergen, since=self.ago(hours=2, days=0) - timedelta(minutes=1),
                             before=self.ago(hours=1)), [b.pk])
        rows = read.history(list(read.samples_of(owner=self.t1)))
        self.assertEqual([row.sample.point.name for row in rows], ['Inlet', 'Middle'])


# ---- the dialog, the round and the pages that say where -------------------------------------------------------
class DialogTests(PointTestCase):
    def post(self, url, data):
        return self.client.post(url, data, headers={'X-Modal': '1'})

    def record_data(self, point, **values):
        local = timezone.localtime(self.ago(hours=1)).strftime('%Y-%m-%dT%H:%M')
        return {'token': str(uuid.uuid4()), 'point': str(point.pk), 'measured_at': local, 'source': 'manual',
                'notes': '', **{code: '' for code in parameters.COLUMNS}, **values}

    def test_from_a_unit_the_middle_point_is_chosen_and_the_others_of_it_are_one_choice_away(self):
        form = self.client.get(reverse('farm:water_record'), {'unit': self.t1.pk}).context['form']
        self.assertEqual(form['point'].value(), str(self.mid1.pk))
        groups = form.fields['point'].choices
        self.assertEqual([(label, [text for _value, text in options]) for label, options in groups],
                         [('Units', ['T-01 › Inlet', 'T-01 › Middle', 'T-01 › Side outlet', 'T-01 › Bottom drain'])])
        self.assertFalse(form.fixed)
        response = self.client.get(reverse('farm:water_record'), {'unit': self.t1.pk})
        self.assertContains(response, 'T-01 › Side outlet')
        self.assertContains(response, f'<option value="{self.mid1.pk}" selected>T-01 › Middle</option>', html=True)
        form = self.client.get(reverse('farm:water_record'), {'system': self.ras.pk}).context['form']
        self.assertEqual((form.fixed, form['point'].value()), (True, str(self.loop.pk)))       # one point: fixed
        response = self.client.get(reverse('farm:water_record'), {'point': self.named(self.t1, 'inlet')['Inlet'].pk})
        self.assertEqual(response.context['form']['point'].value(), str(self.named(self.t1, 'inlet')['Inlet'].pk))

    def test_from_nowhere_every_active_point_is_offered_grouped_by_what_owns_it(self):
        point_of(self.filter, 'inlet')
        SamplingPoint.objects.filter(pk=self.mid2.pk).update(is_active=False)
        form = self.client.get(reverse('farm:water_record')).context['form']
        groups = {label: [text for _value, text in options] for label, options in form.fields['point'].choices[1:]}
        self.assertEqual(list(groups), ['Units', 'Systems (loop)', 'Equipment'])
        self.assertIn('T-01 › Middle', groups['Units'])
        self.assertNotIn('T-02 › Middle', groups['Units'])                  # inactive: not offered
        self.assertEqual((groups['Systems (loop)'], groups['Equipment']), (['R1 › Loop'], ['DF1 › Inlet']))

    def test_a_sample_is_recorded_at_the_point_chosen_and_says_so(self):
        outlet = self.named(self.t1, 'side_outlet')['Side outlet']
        url = f'{reverse("farm:water_record")}?unit={self.t1.pk}'
        self.assertEqual(self.post(url, self.record_data(outlet, ph='7.5')).status_code, 204)
        sample = WaterMeasurement.objects.get()
        self.assertEqual((sample.point, sample.ph), (outlet, D('7.50')))
        self.assertEqual(AuditLog.objects.get(action='create', entity_type='water sample').changes['Sampling point'],
                         [None, 'T-01 › Side outlet'])
        page = self.client.get(reverse('farm:water'), {'unit': self.t1.pk})
        self.assertContains(page, 'Side outlet · Side outlet')
        self.assertEqual(self.client.get(reverse('farm:water'), {'point': self.mid1.pk}).context['history'], [])
        history = self.client.get(reverse('farm:water'), {'point': outlet.pk})
        self.assertContains(history, 'History of T-01 › Side outlet')
        self.assertEqual(len(history.context['history']), 1)
        # A point of another owner cannot be posted to the dialog of this one.
        response = self.post(url, self.record_data(self.mid2, ph='7'))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(WaterMeasurement.objects.count(), 1)

    def test_a_species_name_in_a_limits_help_is_text_not_markup(self):
        """The dialog's help is shown as HTML, so the species' name in a limit (a person's text) is escaped."""
        self.salmon.common_name = '<script>alert(1)</script> salmon'
        self.salmon.save()
        self.stock()
        self.limit('ph', warning_low='6.8')
        response = self.client.get(reverse('farm:water_record'), {'unit': self.t1.pk})
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt; salmon: warning below 6.80')
        self.assertNotContains(response, '<script>alert(1)')

    def test_a_sample_at_the_middle_point_is_as_quick_as_before(self):
        """Opened from a unit the form needs the same fields as before: the point is already chosen."""
        url = f'{reverse("farm:water_record")}?unit={self.t1.pk}'
        data = self.record_data(self.mid1, temperature_c='9')
        self.assertEqual(self.post(url, data).status_code, 204)
        self.assertEqual(WaterMeasurement.objects.get().point, self.mid1)

    def test_a_unit_without_a_middle_point_says_so_in_the_drawer(self):
        stock = get_user_model().objects.create_user('sue', 'sue@example.com', 'x')
        stock.groups.add(role('Units', 'view_stockoperation', 'view_watermeasurement', 'view_samplingpoint', 'view_tank'))
        self.client.force_login(stock)
        response = self.client.get(reverse('farm:production_units'), {'unit': self.pond.pk})
        self.assertContains(response, 'This unit has no active middle sampling point')
        self.assertContains(response, f'{reverse("farm:samplingpoint_list")}?unit={self.pond.pk}')
        response = self.client.get(reverse('farm:production_units'), {'unit': self.t1.pk})
        self.assertContains(response, 'at T-01 › Middle')


class RoundTests(PointTestCase):
    def rows(self, **query):
        response = self.client.get(reverse('farm:water_round'), {'site': self.bergen.pk, **query})
        return [str(row.point) for row in response.context['rows']]

    def test_a_round_has_a_row_per_middle_point_and_lists_other_points_when_asked(self):
        point_of(self.pond)
        self.assertEqual(self.rows(), ['P-01 › Middle', 'T-01 › Middle', 'T-02 › Middle', 'R1 › Loop'])
        self.assertEqual(self.rows(include='inlet'), ['P-01 › Inlet', 'P-01 › Middle', 'T-01 › Inlet', 'T-01 › Middle',
                                                     'T-02 › Inlet', 'T-02 › Middle', 'R1 › Loop'])
        rows = self.rows(include=['side_outlet', 'bottom_drain'], production_department=self.hall.pk)
        self.assertEqual([row for row in rows if row.startswith('T-01')],
                         ['T-01 › Middle', 'T-01 › Side outlet', 'T-01 › Bottom drain'])
        self.assertEqual([row for row in rows if row.startswith('P-01')], ['P-01 › Middle'])     # a pond has neither
        point_of(self.filter, 'inlet')
        self.assertEqual(self.rows(include='equipment')[-1], 'DF1 › Inlet')
        self.assertNotIn('DF1 › Inlet', self.rows())
        self.assertEqual(self.rows(include='equipment', system=self.ras.pk), ['T-01 › Middle', 'T-02 › Middle',
                                                                              'R1 › Loop', 'DF1 › Inlet'])
        SamplingPoint.objects.filter(pk=self.named(self.t1, 'inlet')['Inlet'].pk).update(is_active=False)
        self.assertNotIn('T-01 › Inlet', self.rows(include='inlet'))

    def test_a_round_records_the_samples_at_their_points_all_or_none(self):
        outlet = self.named(self.t1, 'bottom_drain')['Bottom drain']
        url = f'{reverse("farm:water_round")}?site={self.bergen.pk}&columns=ph&include=bottom_drain'
        local = timezone.localtime(self.ago(hours=1)).strftime('%Y-%m-%dT%H:%M')
        data = {'token': str(uuid.uuid4()), 'measured_at': local, 'source': 'manual',
                f'point-{self.mid1.pk}-ph': '7.2', f'point-{outlet.pk}-ph': '7.6', f'point-{self.mid2.pk}-ph': ''}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(sorted((sample.point.name, str(sample.ph)) for sample in WaterMeasurement.objects.all()),
                         [('Bottom drain', '7.60'), ('Middle', '7.20')])
        response = self.client.post(url, {**data, 'token': str(uuid.uuid4()), f'point-{outlet.pk}-ph': '25'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(WaterMeasurement.objects.count(), 2)


class HistoryTests(PointTestCase):
    def test_the_history_filters_by_owner_and_point_and_says_where_each_value_was_taken(self):
        inlet = self.named(self.t1, 'inlet')['Inlet']
        self.sample(point=inlet, hours=1, ph='7')
        self.sample(point=self.t1, hours=2, ph='7.1')
        self.sample(point=self.loop, hours=3, co2_mg_l='9')
        point_of(self.filter, 'inlet')
        self.sample(point=point_of(self.filter, 'inlet'), hours=4, ph='6.9')
        history = lambda **query: [str(row.sample.point) for row in
                                   self.client.get(reverse('farm:water'), {'view': 'history', **query}).context['history']]
        self.assertEqual(history(), ['T-01 › Inlet', 'T-01 › Middle', 'R1 › Loop', 'DF1 › Inlet'])
        self.assertEqual(history(unit=self.t1.pk), ['T-01 › Inlet', 'T-01 › Middle'])
        self.assertEqual(history(owner=f'unit:{self.t1.pk}', point=inlet.pk), ['T-01 › Inlet'])
        self.assertEqual(history(owner=f'system:{self.ras.pk}'), ['R1 › Loop'])
        self.assertEqual(history(equipment=self.filter.pk), ['DF1 › Inlet'])
        self.assertEqual(history(point=self.mid1.pk), ['T-01 › Middle'])
        page = self.client.get(reverse('farm:water'), {'view': 'history'})
        for text in ('<span class="row-sub">Inlet · Inlet</span>', 'Loop · Middle', 'DF1'):
            self.assertContains(page, text)
        page = self.client.get(reverse('farm:water'), {'owner': f'unit:{self.t1.pk}'})
        self.assertContains(page, f'<option value="unit:{self.t1.pk}" selected>')
        self.assertContains(page, 'All its points')

    def test_the_latest_page_lists_the_middle_points_and_the_other_points_that_were_sampled(self):
        self.sample(point=self.named(self.t1, 'inlet')['Inlet'], hours=1, ph='7')
        self.sample(point=self.loop, hours=1, co2_mg_l='9')
        point_of(self.pond)
        response = self.client.get(reverse('farm:water'))
        found = [(row['owner'].code, row['point'].name if row['point'] else None) for row in response.context['rows']]
        self.assertEqual(found, [('C-01', None), ('P-01', 'Middle'), ('T-01', 'Inlet'), ('T-01', 'Middle'),
                                 ('T-02', 'Middle'), ('R1', 'Loop')])          # the cage has no point: a row to say so
        self.assertEqual(response.context['point_count'], 5)
        make_unit('T-09', self.hall)                                              # a unit with no point at all
        rows = self.client.get(reverse('farm:water')).context['rows']
        self.assertIn(('T-09', None), [(row['owner'].code, row['point']) for row in rows])
        self.assertContains(self.client.get(reverse('farm:water')), 'No middle point')


class LanguageTests(PointTestCase):
    def test_the_tab_and_the_dialog_speak_each_language(self):
        words = {'tr': ('Numune noktaları', 'Orta', 'Numune noktası'), 'nb': ('Prøvepunkter', 'Midten', 'Prøvepunkt')}
        for language, (title, middle, outlet) in words.items():
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            self.user.groups.add(role(f'Points {language}', 'view_samplingpoint'))
            page = self.client.get(reverse('farm:samplingpoint_list'))
            self.assertContains(page, title, msg_prefix=language)
            self.assertContains(page, middle, msg_prefix=language)
            self.assertContains(self.client.get(reverse('farm:water_record'), {'unit': self.t1.pk}), outlet,
                                msg_prefix=language)
