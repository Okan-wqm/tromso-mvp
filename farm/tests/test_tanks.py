"""Tanks, ponds & cages: the units fish are held in, checked through the pages against the stored rows."""
from datetime import date
from decimal import Decimal
from itertools import product
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, ProgrammingError, connection, transaction
from django.test import TestCase
from django.urls import reverse

from core import access, database, dbgrid, navigation, softdelete
from core.audit import message
from core.models import AuditLog, Profile

from ..models import ProductionDepartment, Site, System, Tank
from ..models.tank import NEEDS_FISH, STARTING_STATUSES, TRANSITIONS
from ..stock import services
from .helpers import role, stock_fish

Status = Tank.Status
UNIT_MANAGER = (
    'view_tank', 'add_tank', 'change_tank', 'delete_tank', 'view_site', 'delete_site', 'view_productiondepartment',
    'delete_productiondepartment', 'view_system', 'change_system', 'delete_system', 'view_auditlog',
)
# What each kind's part of the dialog posts by default.
KIND_DATA = {
    'tank': {'shape': 'circular', 'material': 'fiberglass', 'diameter': '2', 'depth': '1.5', 'water_depth': '',
             'max_density_kg_m3': '60'},
    'pond': {'pond_type': 'earthen', 'water_source': '', 'surface_area_m2': '1000', 'depth': '1.5', 'max_depth': '',
             'water_depth': '', 'liner_type': '', 'max_density_kg_m3': '3'},
    'cage': {'cage_type': 'floating', 'shape': 'circular', 'diameter': '50', 'depth': '20', 'net_material': '',
             'mesh_size_mm': '', 'frame_type': '', 'max_density_kg_m3': '25'},
}
# What each kind needs when made directly.
KIND_FIELDS = {
    'tank': {'shape': 'circular', 'material': 'fiberglass', 'diameter': Decimal('2'), 'depth': Decimal('1.5'),
             'max_density_kg_m3': Decimal('60')},
    'pond': {'pond_type': 'earthen', 'surface_area_m2': Decimal('1000'), 'depth': Decimal('1.5'),
             'max_density_kg_m3': Decimal('2')},
    'cage': {'cage_type': 'floating', 'shape': 'circular', 'diameter': Decimal('50'), 'depth': Decimal('20'),
             'max_density_kg_m3': Decimal('20')},
}


def unit_data(department, kind='tank', **overrides):
    """What the unit dialog posts."""
    data = {
        'name': 'Start tank 1', 'code': 't-01', 'kind': kind, 'status': 'preparing', 'status_reason': '',
        'water_type': 'freshwater', 'regulatory_unit_id': '', 'production_department': str(department.pk),
        'system': '', 'installation_date': '', 'description': '', 'notes': '',
        **KIND_DATA[kind],
    }
    data.update(overrides)
    return data


class TankTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        self.user.groups.add(role('Unit manager', *UNIT_MANAGER))
        self.client.force_login(self.user)
        self.bergen = Site.objects.create(name='Bergen', code='BG')
        self.tromso = Site.objects.create(name='Tromso', code='TR')
        self.hall = ProductionDepartment.objects.create(site=self.bergen, name='Hall A', code='HA')
        self.hall_b = ProductionDepartment.objects.create(site=self.bergen, name='Hall B', code='HB')
        self.sea = ProductionDepartment.objects.create(site=self.tromso, name='Sea', code='SE')
        self.orphan = ProductionDepartment.objects.create(name='Orphan', code='OR')
        self.ras = System.objects.create(site=self.bergen, name='RAS 1', code='R1')
        self.ras_a = System.objects.create(site=self.bergen, name='RAS A', code='RA', production_department=self.hall)
        self.cage_line = System.objects.create(site=self.tromso, name='Cage line', code='CL')

    def make(self, kind='tank', name='Tank', code='T1', department=None, **fields):
        values = {'water_type': 'freshwater', **KIND_FIELDS[kind], **fields}
        return Tank.objects.create(name=name, code=code, kind=kind, production_department=department or self.hall,
                                   **values)

    def post(self, data, unit=None):
        url = reverse('farm:tank_edit', args=[unit.pk]) if unit else reverse('farm:tank_create')
        return self.client.post(url, data)

    def errors(self, data, unit=None):
        response = self.post(data, unit)
        self.assertEqual(response.status_code, 200, 'the form was expected to be refused')
        return response.context['form'].errors

    def draft(self, data, unit=None):
        url = reverse('farm:tank_edit', args=[unit.pk]) if unit else reverse('farm:tank_create')
        return self.client.post(url, data).context['form']


class TankRoundTripTests(TankTestCase):
    def test_a_tank_create_read_edit_delete(self):
        # Create
        self.post(unit_data(self.hall, system=str(self.ras_a.pk), status='fallow', status_reason='Rested',
                            water_type='saltwater', regulatory_unit_id='K-17', water_depth='1.2',
                            installation_date='2026-03-01', description='Start feeding', notes='Check the outlet'))
        tank = Tank.objects.get()
        self.assertEqual(
            (tank.name, tank.code, tank.kind, tank.status, tank.status_reason, tank.water_type, tank.regulatory_unit_id,
             tank.production_department, tank.system, tank.shape, tank.material, tank.diameter, tank.length, tank.width,
             tank.depth, tank.water_depth, tank.max_density_kg_m3, tank.installation_date, tank.description, tank.notes,
             tank.created_by, tank.version),
            ('Start tank 1', 'T-01', 'tank', 'fallow', 'Rested', 'saltwater', 'K-17', self.hall, self.ras_a, 'circular',
             'fiberglass', Decimal('2.00'), None, None, Decimal('1.50'), Decimal('1.20'), Decimal('60.00'),
             date(2026, 3, 1), 'Start feeding', 'Check the outlet', self.user, 1))
        self.assertEqual((tank.volume_m3, tank.water_volume_m3, tank.max_biomass_kg),
                         (Decimal('4.712'), Decimal('3.770'), Decimal('226.20')))
        self.assertIsNotNone(tank.status_changed_at)

        # Read: listed, and the edit form is filled from the database
        response = self.client.get(reverse('farm:tank_list'))
        self.assertEqual([unit.pk for unit in response.context['objects']], [tank.pk])
        self.assertContains(response, 'Start tank 1')
        self.assertContains(response, '<span class="badge badge-fallow">Fallow</span>', html=True)
        form = self.client.get(reverse('farm:tank_edit', args=[tank.pk])).context['form']
        self.assertEqual((form['kind'].value(), form['shape'].value(), form['diameter'].value(),
                          form['water_depth'].value(), form['system'].value(), form['volume_m3'].value(),
                          form['freeboard'].value(), form['max_biomass_kg'].value()),
                         ('tank', 'circular', Decimal('2.00'), Decimal('1.20'), self.ras_a.pk, '4.712', '0.30', '226.20'))

        # Edit: another shape, its measures, and a status it can move to
        self.post(unit_data(self.hall, name='Start tank 1b', code='t-01', shape='rectangular', diameter='',
                            length='4', width='2', depth='1', water_depth='', status='preparing',
                            max_density_kg_m3='50', water_type='saltwater', version='1'), tank)
        tank.refresh_from_db()
        self.assertEqual((tank.name, tank.shape, tank.diameter, tank.length, tank.width, tank.depth, tank.water_depth,
                          tank.status, tank.version, tank.updated_by),
                         ('Start tank 1b', 'rectangular', None, Decimal('4.00'), Decimal('2.00'), Decimal('1.00'), None,
                          'preparing', 2, self.user))
        self.assertEqual((tank.volume_m3, tank.water_volume_m3, tank.max_biomass_kg),
                         (Decimal('8.000'), None, Decimal('400.00')))

        # Delete: hidden, kept for a restore
        self.client.post(reverse('farm:tank_delete', args=[tank.pk]))
        self.assertFalse(Tank.objects.exists())
        self.assertTrue(Tank.all_objects.get().is_deleted)

    def test_a_pond_create_read_edit_delete(self):
        self.post(unit_data(self.hall, 'pond', name='Pond 4', code='p-4', pond_type='lined', liner_type='hdpe',
                            liner_thickness_mm='1.5', water_source='river', surface_area_m2='2500', depth='1.8',
                            max_depth='2.5', water_depth='1.6', max_density_kg_m3='3'))
        pond = Tank.objects.get()
        self.assertEqual(
            (pond.kind, pond.pond_type, pond.liner_type, pond.liner_thickness_mm, pond.water_source,
             pond.surface_area_m2, pond.depth, pond.max_depth, pond.water_depth, pond.shape, pond.material,
             pond.diameter),
            ('pond', 'lined', 'hdpe', Decimal('1.50'), 'river', Decimal('2500.00'), Decimal('1.80'), Decimal('2.50'),
             Decimal('1.60'), '', '', None))
        self.assertEqual((pond.volume_m3, pond.water_volume_m3, pond.max_biomass_kg),
                         (Decimal('4500.000'), Decimal('4000.000'), Decimal('12000.00')))
        form = self.client.get(reverse('farm:tank_edit', args=[pond.pk])).context['form']
        self.assertEqual((form['surface_area_m2'].value(), form['liner_type'].value()), (Decimal('2500.00'), 'hdpe'))
        self.assertNotIn('diameter', form.fields)

        # An earthen pond has no membrane: the liner is cleared with the type, and so is the thickness
        self.post(unit_data(self.hall, 'pond', name='Pond 4', code='p-4', pond_type='earthen', liner_type='clay',
                            surface_area_m2='2500', depth='1.8', max_density_kg_m3='3', version='1'), pond)
        pond.refresh_from_db()
        self.assertEqual((pond.pond_type, pond.liner_type, pond.liner_thickness_mm, pond.water_source,
                          pond.max_depth, pond.water_volume_m3),
                         ('earthen', 'clay', None, '', None, None))
        self.client.post(reverse('farm:tank_delete', args=[pond.pk]))
        self.assertTrue(Tank.all_objects.get().is_deleted)

    def test_a_cage_create_read_edit_delete(self):
        self.post(unit_data(self.sea, 'cage', name='Merd 3', code='m-3', system=str(self.cage_line.pk),
                            water_type='saltwater', cage_type='submersible', shape='square', length='20',
                            depth='15', max_submersion_depth='25', net_material='nylon', mesh_size_mm='22.5',
                            frame_type='steel', max_density_kg_m3='25'))
        cage = Tank.objects.get()
        self.assertEqual(
            (cage.kind, cage.cage_type, cage.shape, cage.length, cage.width, cage.depth, cage.max_submersion_depth,
             cage.net_material, cage.mesh_size_mm, cage.frame_type, cage.water_depth, cage.system),
            ('cage', 'submersible', 'square', Decimal('20.00'), Decimal('20.00'), Decimal('15.00'), Decimal('25.00'),
             'nylon', Decimal('22.5'), 'steel', None, self.cage_line))
        self.assertEqual((cage.volume_m3, cage.water_volume_m3, cage.max_biomass_kg),
                         (Decimal('6000.000'), None, Decimal('150000.00')))
        form = self.client.get(reverse('farm:tank_edit', args=[cage.pk])).context['form']
        self.assertEqual((form['length'].label, form['depth'].label), ('Side (m)', 'Net depth (m)'))
        self.assertNotIn('width', form.fields)
        self.assertNotIn('water_depth', form.fields)

        # A floating cage is not lowered: its submersion depth goes
        self.post(unit_data(self.sea, 'cage', name='Merd 3', code='m-3', water_type='saltwater', cage_type='floating',
                            shape='circular', diameter='50.93', depth='30', max_density_kg_m3='25', version='1'), cage)
        cage.refresh_from_db()
        self.assertEqual((cage.cage_type, cage.shape, cage.diameter, cage.length, cage.width,
                          cage.max_submersion_depth, cage.net_material, cage.system),
                         ('floating', 'circular', Decimal('50.93'), None, None, None, '', None))
        self.client.post(reverse('farm:tank_delete', args=[cage.pk]))
        self.assertTrue(Tank.all_objects.get().is_deleted)

    def test_every_optional_field_can_be_cleared(self):
        tank = self.make(system=self.ras, status_reason='x', regulatory_unit_id='K-1', water_depth=Decimal('1'),
                         installation_date=date(2026, 1, 1), description='d', notes='n')
        self.post(unit_data(self.hall, name='Tank', code='T1', version='1'), tank)
        tank.refresh_from_db()
        self.assertEqual((tank.system, tank.status_reason, tank.regulatory_unit_id, tank.water_depth,
                          tank.water_volume_m3, tank.installation_date, tank.description, tank.notes),
                         (None, '', '', None, None, None, '', ''))
        pond = self.make('pond', name='Pond', code='P1', water_source='well', max_depth=Decimal('2'),
                         liner_type='clay', water_depth=Decimal('1'))
        self.post(unit_data(self.hall, 'pond', name='Pond', code='P1', version='1'), pond)
        pond.refresh_from_db()
        self.assertEqual((pond.water_source, pond.max_depth, pond.liner_type, pond.water_depth), ('', None, '', None))
        cage = self.make('cage', name='Cage', code='C1', net_material='nylon', mesh_size_mm=Decimal('10'),
                         frame_type='hdpe')
        self.post(unit_data(self.hall, 'cage', name='Cage', code='C1', version='1'), cage)
        cage.refresh_from_db()
        self.assertEqual((cage.net_material, cage.mesh_size_mm, cage.frame_type), ('', None, ''))

    def test_the_form_opens_in_the_dialog_with_its_tabs(self):
        response = self.client.get(reverse('farm:tank_create'), headers={'X-Modal': '1'})
        self.assertContains(response, 'class="modal-head"')
        for tab in ('general', 'location', 'dimensions', 'capacity', 'details'):
            self.assertContains(response, f'data-tab="{tab}"')
        self.assertContains(response, 'Choose the kind on the General tab')
        self.assertNotContains(response, 'name="volume_m3"')


class VolumeTests(TankTestCase):
    """The database works the volumes out from the measures (Tank.water_surface)."""

    def test_each_shape_with_known_numbers(self):
        cases = [
            # π·(2/2)²·1.5; water π·1²·1.2
            ('tank', {'shape': 'circular', 'diameter': 2, 'depth': '1.5', 'water_depth': '1.2'}, '4.712', '3.770'),
            ('tank', {'shape': 'rectangular', 'diameter': None, 'length': 4, 'width': 2, 'depth': 1}, '8.000', None),
            ('tank', {'shape': 'square', 'diameter': None, 'length': 3, 'depth': 2}, '18.000', None),
            # an ellipse with axes 4 and 2: π·2·1·1
            ('tank', {'shape': 'oval', 'diameter': None, 'length': 4, 'width': 2, 'depth': 1}, '6.283', None),
            ('tank', {'shape': 'raceway', 'diameter': None, 'length': 30, 'width': 3, 'depth': 1}, '90.000', None),
            # (10 − 2)·2 + π·(2/2)², times 1
            ('tank', {'shape': 'd_end', 'diameter': None, 'length': 10, 'width': 2, 'depth': 1}, '19.142', None),
            # entered; the water volume in proportion to the depth
            ('tank', {'shape': 'other', 'diameter': None, 'stated_volume_m3': '12.5', 'depth': '2.5',
                      'water_depth': 2}, '12.500', '10.000'),
            ('pond', {'surface_area_m2': 1000, 'depth': '1.5', 'water_depth': '1.2'}, '1500.000', '1200.000'),
            # a 160 m ring is 50.93 m across: π·25.465²·20
            ('cage', {'diameter': '50.93', 'depth': 20}, '40744.335', None),
            ('cage', {'shape': 'square', 'diameter': None, 'length': 20, 'depth': 15}, '6000.000', None),
        ]
        for index, (kind, fields, volume, water) in enumerate(cases):
            with self.subTest(kind=kind, fields=fields):
                unit = self.make(kind, code=f'U{index}', **{
                    name: value if name == 'shape' or value is None else Decimal(str(value))
                    for name, value in fields.items()})
                unit.refresh_from_db()
                self.assertEqual(unit.volume_m3, Decimal(volume))
                self.assertEqual(unit.water_volume_m3, None if water is None else Decimal(water))

    def test_the_max_biomass_is_the_effective_volume_at_the_max_density(self):
        tank = self.make(max_density_kg_m3=Decimal('60'))
        self.assertEqual(tank.max_biomass_kg, Decimal('282.72'))    # 4.712 m³ · 60
        tank.water_depth = Decimal('1.2')
        tank.save()
        self.assertEqual(tank.max_biomass_kg, Decimal('226.20'))    # 3.770 m³ · 60
        tank.max_density_kg_m3 = Decimal('80')
        tank.save()
        self.assertEqual(Tank.objects.get().max_biomass_kg, Decimal('301.60'))

    def test_clearing_the_water_depth_clears_the_water_volume(self):
        tank = self.make(water_depth=Decimal('1'))
        self.assertEqual(tank.water_volume_m3, Decimal('3.142'))
        self.post(unit_data(self.hall, name='Tank', code='T1', water_depth='', version='1'), tank)
        tank.refresh_from_db()
        self.assertEqual((tank.water_depth, tank.water_volume_m3, tank.max_biomass_kg), (None, None, Decimal('282.72')))

    def test_a_derived_value_cannot_be_written(self):
        tank = self.make()
        with self.assertRaises(ProgrammingError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute('UPDATE tanks SET volume_m3 = 1 WHERE id = %s', [tank.pk])
        # Whatever writes the measures, the database recalculates.
        Tank.objects.filter(pk=tank.pk).update(depth=Decimal('3'))
        self.assertEqual(Tank.objects.get().volume_m3, Decimal('9.425'))

    def test_only_a_shape_of_its_own_has_its_volume_entered(self):
        form = self.draft({'_draft': 'shape', 'kind': 'tank', 'shape': 'other'})
        self.assertTrue(form.fields['stated_volume_m3'].required)
        self.assertEqual(form.fields['stated_volume_m3'].label, 'Volume (m³)')
        self.assertNotIn('stated_volume_m3', self.draft({'_draft': 'shape', 'kind': 'tank', 'shape': 'oval'}).fields)
        errors = self.errors(unit_data(self.hall, shape='other', diameter=''))
        self.assertEqual(errors['stated_volume_m3'], ['This field is required.'])

    def test_the_freeboard_is_shown_not_stored(self):
        tank = self.make(depth=Decimal('2'), water_depth=Decimal('1.75'))
        self.assertEqual(tank.freeboard, Decimal('0.25'))
        self.assertNotIn('freeboard', [field.name for field in Tank._meta.concrete_fields])


class MeasureValidationTests(TankTestCase):
    def test_name_code_kind_water_type_department_and_density_are_required(self):
        errors = self.errors({**unit_data(self.hall, name='', code='', water_type='', production_department='',
                                          max_density_kg_m3=''), 'kind': ''})
        self.assertEqual(set(errors), {'name', 'code', 'kind', 'water_type', 'production_department',
                                       'max_density_kg_m3'})
        errors = self.errors(unit_data(self.hall, shape='', material='', depth=''))
        self.assertEqual(set(errors), {'shape', 'material', 'depth'})
        errors = self.errors(unit_data(self.hall, 'pond', pond_type='', surface_area_m2=''))
        self.assertEqual(set(errors), {'pond_type', 'surface_area_m2'})
        errors = self.errors(unit_data(self.hall, 'cage', cage_type='', shape='', depth=''))
        self.assertEqual(set(errors), {'cage_type', 'shape', 'depth'})

    def test_each_shape_needs_its_measures(self):
        for shape, missing in [('circular', {'diameter'}), ('rectangular', {'length', 'width'}),
                               ('square', {'length'}), ('d_end', {'length', 'width'})]:
            with self.subTest(shape=shape):
                errors = self.errors(unit_data(self.hall, shape=shape, diameter='', length='', width=''))
                self.assertEqual(set(errors), missing)

    def test_the_water_cannot_stand_above_the_depth(self):
        errors = self.errors(unit_data(self.hall, depth='1.5', water_depth='1.6'))
        self.assertEqual(errors['water_depth'], ['The water cannot stand higher than the depth.'])
        errors = self.errors(unit_data(self.hall, depth='1.5', water_depth='0'))
        self.assertEqual(errors['water_depth'], ['Leave the water depth empty, or give one above 0.'])
        self.post(unit_data(self.hall, depth='1.5', water_depth='1.5'))
        self.assertEqual(Tank.objects.get().water_depth, Decimal('1.50'))
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make(code='T2', water_depth=Decimal('2'))

    def test_a_ponds_deepest_point_is_not_above_its_average_depth(self):
        errors = self.errors(unit_data(self.hall, 'pond', depth='1.5', max_depth='1.2'))
        self.assertEqual(errors['max_depth'], ['The deepest point cannot be shallower than the average depth.'])
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make('pond', max_depth=Decimal('1'))

    def test_an_oval_and_a_d_ended_tank_are_longer_than_wide(self):
        for shape in ('oval', 'd_end'):
            with self.subTest(shape=shape):
                errors = self.errors(unit_data(self.hall, shape=shape, diameter='', length='2', width='3'))
                self.assertEqual(errors['width'], ['The width cannot be more than the length.'])
        with self.assertRaises(IntegrityError), transaction.atomic():
            Tank.objects.filter(pk=self.make(shape='d_end', diameter=None, length=Decimal('5'),
                                             width=Decimal('2')).pk).update(width=Decimal('6'))

    def test_a_squares_width_is_its_side(self):
        self.post(unit_data(self.hall, shape='square', diameter='', length='3', width='99'))
        tank = Tank.objects.get()
        self.assertEqual((tank.length, tank.width), (Decimal('3.00'), Decimal('3.00')))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Tank.objects.filter(pk=tank.pk).update(width=Decimal('4'))

    def test_bounds_follow_the_kind(self):
        # A net is far deeper than a tank: 40 m is a cage's depth, not a tank's.
        self.assertIn('depth', self.errors(unit_data(self.hall, depth='21')))
        self.post(unit_data(self.sea, 'cage', depth='40', water_type='saltwater', max_density_kg_m3='25'))
        self.assertEqual(Tank.objects.get().depth, Decimal('40.00'))
        self.assertIn('depth', self.errors(unit_data(self.sea, 'cage', code='c-2', depth='101')))
        self.assertIn('diameter', self.errors(unit_data(self.hall, diameter='51')))
        self.assertIn('max_density_kg_m3', self.errors(unit_data(self.hall, max_density_kg_m3='501')))
        self.assertIn('max_density_kg_m3', self.errors(unit_data(self.hall, 'pond', max_density_kg_m3='51')))
        self.assertIn('max_density_kg_m3', self.errors(unit_data(self.hall, 'cage', max_density_kg_m3='301')))
        self.assertIn('max_density_kg_m3', self.errors(unit_data(self.hall, max_density_kg_m3='0')))
        form = self.draft({'_draft': 'kind', 'kind': 'cage'})
        self.assertIn('From 1 to 100.', str(form.fields['depth'].help_text))
        # The database holds the same bounds.
        for fields in ({'depth': Decimal('25')}, {'max_density_kg_m3': Decimal('600')}):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                self.make(code='X', **fields)

    def test_a_square_side_has_the_bounds_of_both_sides(self):
        errors = self.errors(unit_data(self.hall, shape='square', diameter='', length='60'))
        self.assertEqual(errors['length'], ['Ensure this value is less than or equal to 50.'])

    def test_liners(self):
        errors = self.errors(unit_data(self.hall, 'pond', pond_type='lined', liner_type=''))
        self.assertEqual(errors['liner_type'], ['This field is required.'])
        errors = self.errors(unit_data(self.hall, 'pond', pond_type='earthen', liner_type='hdpe'))
        self.assertIn('Select a valid choice', errors['liner_type'][0])
        errors = self.errors(unit_data(self.hall, 'pond', pond_type='lined', liner_type='hdpe', liner_thickness_mm='12'))
        self.assertEqual(errors['liner_thickness_mm'], ['This liner is 0.2 to 5 mm thick.'])
        self.post(unit_data(self.hall, 'pond', pond_type='lined', liner_type='concrete', liner_thickness_mm='120'))
        self.assertEqual(Tank.objects.get().liner_thickness_mm, Decimal('120.00'))
        for fields in ({'pond_type': 'earthen', 'liner_type': 'hdpe'}, {'pond_type': 'lined', 'liner_type': ''},
                       {'pond_type': 'lined', 'liner_type': 'pvc', 'liner_thickness_mm': Decimal('30')}):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                Tank.objects.filter(pk=Tank.objects.get().pk).update(**fields)

    def test_fields_another_kind_has_stay_empty_in_the_database(self):
        tank = self.make()
        for fields in ({'surface_area_m2': 5}, {'cage_type': 'floating'}, {'material': ''}, {'shape': 'oval'},
                       {'max_submersion_depth': 3}, {'kind': 'pond'}):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                Tank.objects.filter(pk=tank.pk).update(**fields)

    def test_the_model_tidies_what_its_kind_does_not_use(self):
        tank = self.make(surface_area_m2=Decimal('9'), cage_type='floating', length=Decimal('4'))
        self.assertEqual((tank.surface_area_m2, tank.cage_type, tank.length), (None, '', None))


class DraftTests(TankTestCase):
    """The kind, the shape, the pond type and the cage type render the form again (TabbedForm.refresh_on)."""

    def test_they_ask_for_a_new_form(self):
        html = self.client.get(reverse('farm:tank_create')).content.decode()
        self.assertIn('name="kind" data-refresh="_draft"', html)
        self.assertEqual(html.count('data-refresh="_draft"'), 1)      # the others come with a kind
        response = self.client.post(reverse('farm:tank_create'), {'_draft': 'kind', 'kind': 'cage'})
        self.assertEqual(response.content.decode().count('data-refresh="_draft"'), 3)    # kind, cage type, shape

    def test_each_kind_shows_its_own_fields(self):
        expected = {
            'tank': ['shape', 'material', 'depth', 'water_depth'],
            'pond': ['pond_type', 'water_source', 'surface_area_m2', 'depth', 'max_depth', 'water_depth', 'liner_type'],
            'cage': ['cage_type', 'shape', 'depth', 'net_material', 'mesh_size_mm', 'frame_type'],
        }
        for kind, names in expected.items():
            with self.subTest(kind=kind):
                form = self.draft({'_draft': 'kind', 'kind': kind})
                (tab,) = [tab for tab in form.tab_list() if tab['key'] == 'dimensions']
                self.assertEqual([field.name for fieldset in tab['fieldsets'] for field in fieldset['fields']], names)
        cage = self.draft({'_draft': 'cage_type', 'kind': 'cage', 'cage_type': 'submersible', 'shape': 'circular'})
        self.assertIn('max_submersion_depth', cage.fields)
        self.assertEqual([value for value, _ in cage.fields['shape'].choices], ['', 'circular', 'square'])
        lined = self.draft({'_draft': 'pond_type', 'kind': 'pond', 'pond_type': 'lined'})
        self.assertEqual([value for value, _ in lined.fields['liner_type'].choices], ['', 'hdpe', 'pvc', 'epdm', 'concrete'])
        self.assertIn('liner_thickness_mm', lined.fields)

    def test_the_form_comes_back_on_the_tab_of_the_field_that_changed(self):
        response = self.client.post(reverse('farm:tank_create'), {'_draft': 'shape', 'kind': 'tank', 'shape': 'oval',
                                                                  'name': 'Oval 1', 'length': '4'})
        self.assertEqual(response.context['open_tab'], 'dimensions')
        self.assertContains(response, 'data-open="dimensions"')
        form = response.context['form']
        self.assertEqual((form['name'].value(), form['length'].value(), form['length'].label),
                         ('Oval 1', '4', 'Long axis (m)'))
        self.assertNotContains(response, 'errorlist')
        self.assertFalse(Tank.objects.exists())
        self.assertFalse(AuditLog.objects.exists())

    def test_a_kind_cannot_be_changed_on_an_existing_unit(self):
        tank = self.make()
        self.post({**unit_data(self.hall, name='Tank', code='T1', version='1'), 'kind': 'pond', 'surface_area_m2': '100'},
                  tank)
        tank.refresh_from_db()
        self.assertEqual((tank.kind, tank.diameter, tank.surface_area_m2, tank.version), ('tank', Decimal('2.00'), None, 2))


class LocationTests(TankTestCase):
    def test_the_system_must_be_live(self):
        self.ras.soft_delete(self.user)
        self.assertIn('system', self.errors(unit_data(self.hall, system=str(self.ras.pk))))
        tank = self.make()
        tank.system = System.all_objects.get(pk=self.ras.pk)
        with self.assertRaisesMessage(ValidationError, 'This system is deleted.'):
            tank.full_clean()

    def test_the_system_must_be_on_the_departments_site(self):
        errors = self.errors(unit_data(self.hall, system=str(self.cage_line.pk)))
        self.assertEqual(errors['system'], ['The system is on another site than the production department.'])

    def test_a_system_of_a_production_department_takes_only_its_units(self):
        errors = self.errors(unit_data(self.hall_b, system=str(self.ras_a.pk)))
        self.assertEqual(errors['system'], ['The system belongs to another production department: Hall A (HA).'])
        self.post(unit_data(self.hall_b, system=str(self.ras.pk)))
        self.assertEqual(Tank.objects.get().system, self.ras)

    def test_a_department_without_a_site_has_no_systems(self):
        errors = self.errors(unit_data(self.orphan, system=str(self.ras.pk)))
        self.assertEqual(errors['system'],
                         ['The production department is not on any site, so its units cannot be in a system.'])
        self.post(unit_data(self.orphan))
        self.assertEqual(Tank.objects.get().production_department, self.orphan)

    def test_the_systems_offered_know_their_departments(self):
        form = self.client.get(reverse('farm:tank_create')).context['form']
        html = form['system'].as_widget()
        self.assertIn('data-depends-on="production_department"', html)
        self.assertIn(f'value="{self.ras_a.pk}" data-group="{self.hall.pk}"', html)
        self.assertIn(f'data-group="{" ".join(sorted([str(self.hall.pk), str(self.hall_b.pk)]))}"', html)
        labels = form['production_department'].as_widget()
        self.assertIn('Bergen · Hall A', labels)
        self.assertIn('Orphan (no site)', labels)

    def test_a_system_cannot_move_to_another_department_while_units_of_another_are_in_it(self):
        self.make(system=self.ras, department=self.hall_b)
        response = self.client.post(reverse('farm:system_edit', args=[self.ras.pk]), {
            'name': 'RAS 1', 'code': 'R1', 'type': 'other', 'status': 'operational', 'site': str(self.bergen.pk),
            'production_department': str(self.hall.pk), 'parent': '', 'description': '', 'total_volume_m3': '',
            'max_biomass_kg': '', 'version': '1'})
        self.assertEqual(response.context['form'].errors['production_department'],
                         ['Units of another production department are in it: Tank (T1). Take them out of the system '
                          'first.'])


class UniquenessTests(TankTestCase):
    def test_the_code_is_unique_among_live_units(self):
        old = self.make(code='T-01')
        self.assertEqual(self.errors(unit_data(self.hall))['code'], ['Another unit already uses this code.'])
        old.soft_delete(self.user)
        self.post(unit_data(self.hall))
        self.assertEqual(Tank.objects.get().code, 'T-01')

    def test_a_regulatory_unit_id_is_unique_among_live_units_when_given(self):
        self.make(code='A', regulatory_unit_id='K-7')
        self.make(code='B')
        errors = self.errors(unit_data(self.hall, regulatory_unit_id='K-7'))
        self.assertEqual(errors['regulatory_unit_id'], ['Another unit already has this regulatory unit ID.'])
        self.post(unit_data(self.hall))
        self.assertEqual(Tank.objects.filter(regulatory_unit_id='').count(), 2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make(code='C', regulatory_unit_id='K-7')


class StatusTests(TankTestCase):
    def test_every_transition_of_the_source_and_no_other(self):
        allowed = {(old, new) for old, targets in TRANSITIONS.items() for new in targets}
        for index, (old, new) in enumerate(product(Status.values, Status.values)):
            if old == new:
                continue
            with self.subTest(old=old, new=new):
                unit = self.make(code=f'S{index}', status=old)
                unit.status = new
                # Fish where the new status needs them (active, harvesting), none where it needs none.
                with mock.patch.object(Tank, 'has_stock', return_value=new in NEEDS_FISH):
                    if (old, new) in allowed:
                        unit.full_clean()
                    else:
                        with self.assertRaisesMessage(ValidationError, 'A unit cannot go from'):
                            unit.full_clean()

    def test_a_new_unit_starts_in_a_starting_status(self):
        self.assertEqual(list(STARTING_STATUSES), ['preparing', 'fallow', 'maintenance', 'inactive'])
        form = self.client.get(reverse('farm:tank_create')).context['form']
        self.assertEqual([value for value, _ in form.fields['status'].choices], list(STARTING_STATUSES))
        for status in Status.values:
            with self.subTest(status=status):
                unit = Tank(name='N', code=f'N-{status}', kind='tank', water_type='freshwater',
                            production_department=self.hall, status=status, **KIND_FIELDS['tank'])
                if status in STARTING_STATUSES:
                    unit.full_clean()
                else:
                    with self.assertRaisesMessage(ValidationError, 'A new unit starts as one of'):
                        unit.full_clean()

    def test_the_form_offers_the_current_status_and_where_it_can_go(self):
        unit = self.make(status='active')
        form = self.client.get(reverse('farm:tank_edit', args=[unit.pk])).context['form']
        # Harvesting needs fish in the unit, so it is not offered while it has none.
        self.assertEqual([value for value, _ in form.fields['status'].choices],
                         ['active', 'maintenance', 'quarantine', 'fallow'])
        errors = self.errors(unit_data(self.hall, name='Tank', code='T1', status='preparing', version='1'), unit)
        self.assertIn('status', errors)
        unit.refresh_from_db()
        self.assertEqual(unit.status, 'active')

    def test_a_status_change_is_stamped_and_takes_its_own_reason(self):
        unit = self.make(status='active', status_reason='Stocked')
        first = unit.status_changed_at
        self.assertIsNotNone(first)
        self.post(unit_data(self.hall, name='Renamed', code='T1', status='active', status_reason='Stocked',
                            version='1'), unit)
        unit.refresh_from_db()
        self.assertEqual((unit.status_changed_at, unit.status_reason), (first, 'Stocked'))
        # The reason left as it was belonged to the old status.
        self.post(unit_data(self.hall, name='Renamed', code='T1', status='maintenance', status_reason='Stocked',
                            version='2'), unit)
        unit.refresh_from_db()
        self.assertEqual((unit.status, unit.status_reason), ('maintenance', ''))
        self.assertGreater(unit.status_changed_at, first)
        self.post(unit_data(self.hall, name='Renamed', code='T1', status='preparing', status_reason='Pump fixed',
                            version='3'), unit)
        unit.refresh_from_db()
        self.assertEqual((unit.status, unit.status_reason), ('preparing', 'Pump fixed'))
        self.assertContains(self.client.get(reverse('farm:tank_edit', args=[unit.pk])), 'Status since')


class StockGuardTests(TankTestCase):
    """Every rule that depends on fish asks Tank.has_stock(), which reads the stock ledger."""

    def stock(self, unit, count=100):
        return stock_fish(self.user, unit, count, '50', days_ago=2)

    def test_a_unit_holds_fish_while_its_lines_add_up_to_more_than_none(self):
        unit = self.make(status='preparing')
        self.assertFalse(unit.has_stock())
        batch = self.stock(unit)
        self.assertTrue(unit.has_stock())
        services.record_mortality(self.user, unit=unit, batch=batch, day=services.local_today(unit), count=100,
                                  cause='unknown')
        self.assertFalse(unit.has_stock())

    def test_the_statuses_that_need_fish_and_those_that_need_none(self):
        unit = self.make(status='preparing')
        unit.status = Status.ACTIVE
        with self.assertRaisesMessage(ValidationError, 'A unit becomes active when fish are stocked in it'):
            unit.full_clean()
        self.stock(unit)
        unit = Tank.objects.get(pk=unit.pk)
        self.assertEqual(unit.status, 'active')     # stocking made it active
        self.assertEqual(unit.next_statuses(), ['active', 'harvesting', 'maintenance', 'quarantine'])
        unit.status = Status.HARVESTING
        unit.full_clean()
        empty = self.make(code='T2', status='maintenance')
        self.assertEqual(empty.next_statuses(), ['maintenance', 'preparing', 'inactive'])
        legacy = self.make(code='T4', status='active')    # active without fish: saved before the stock existed
        self.assertEqual(legacy.next_statuses(), ['active', 'maintenance', 'quarantine', 'fallow'])
        legacy.status = Status.HARVESTING
        with self.assertRaisesMessage(ValidationError, 'A unit can be harvested only while fish are in it.'):
            legacy.full_clean()
        stocked = self.make(code='T3', status='preparing')
        self.stock(stocked)
        Tank.objects.filter(pk=stocked.pk).update(status='maintenance')
        stocked = Tank.objects.get(pk=stocked.pk)
        self.assertEqual(stocked.next_statuses(), ['maintenance'])
        stocked.status = Status.INACTIVE
        with self.assertRaisesMessage(ValidationError, 'cannot be made inactive'):
            stocked.full_clean()

    def test_a_unit_with_fish_cannot_be_deleted_nor_its_department(self):
        unit = self.make()
        self.stock(unit)
        page = self.client.get(reverse('farm:tank_delete', args=[unit.pk]))
        self.assertContains(page, 'It holds fish: move or harvest them first.')
        self.client.post(reverse('farm:tank_delete', args=[unit.pk]))
        self.client.post(reverse('farm:productiondepartment_delete', args=[self.hall.pk]))
        self.assertTrue(Tank.objects.filter(pk=unit.pk).exists())
        self.assertTrue(ProductionDepartment.objects.filter(pk=self.hall.pk).exists())

    def test_the_size_of_a_unit_with_fish_cannot_change(self):
        unit = self.make()
        self.stock(unit)
        unit = Tank.objects.get(pk=unit.pk)
        form = self.client.get(reverse('farm:tank_edit', args=[unit.pk])).context['form']
        self.assertTrue(all(form.fields[name].disabled for name in ('shape', 'diameter', 'depth', 'water_depth')))
        self.assertFalse(form.fields['material'].disabled)
        self.post(unit_data(self.hall, name='Tank', code='T1', diameter='3', depth='2', material='concrete',
                            status='active', version=str(unit.version)), unit)
        unit.refresh_from_db()
        self.assertEqual((unit.diameter, unit.depth, unit.material), (Decimal('2.00'), Decimal('1.50'), 'concrete'))
        unit.depth = Decimal('2')
        with self.assertRaisesMessage(ValidationError, 'its size cannot change'):
            unit.full_clean()


class TankDeletePlanTests(TankTestCase):
    def log(self):
        return sorted(AuditLog.objects.values_list('action', 'entity_type', 'entity_label'))

    def test_deleting_a_production_department_deletes_its_units(self):
        self.make()
        self.make('pond', name='Pond', code='P1')
        page = self.client.get(reverse('farm:productiondepartment_delete', args=[self.hall.pk]))
        self.assertContains(page, 'Units deleted with it')
        self.client.post(reverse('farm:productiondepartment_delete', args=[self.hall.pk]))
        self.assertFalse(Tank.objects.exists())
        # Its system RAS A leaves it (core.softdelete), as before units existed.
        self.assertEqual(self.log(), [('delete', 'production department', 'Hall A (HA)'), ('delete', 'unit', 'Pond (P1)'),
                                      ('delete', 'unit', 'Tank (T1)'), ('update', 'system', 'RAS A (RA)')])

    def test_deleting_a_system_takes_its_units_out_of_it(self):
        unit = self.make(system=self.ras)
        page = self.client.get(reverse('farm:system_delete', args=[self.ras.pk]))
        self.assertContains(page, 'Units that lose their system')
        self.client.post(reverse('farm:system_delete', args=[self.ras.pk]))
        unit.refresh_from_db()
        self.assertEqual((unit.is_deleted, unit.system, unit.version), (False, None, 2))
        entry = AuditLog.objects.get(entity_type='unit')
        self.assertEqual((entry.action, entry.changes), ('update', {'System': ['RAS 1 (R1)', None]}))

    def test_deleting_a_site_leaves_the_units_with_their_department_out_of_its_systems(self):
        unit = self.make(system=self.ras)
        self.client.post(reverse('farm:site_delete', args=[self.bergen.pk]))
        unit.refresh_from_db()
        self.assertEqual((unit.is_deleted, unit.system, unit.production_department.site), (False, None, None))

    def test_a_restored_unit_is_checked_like_a_new_one(self):
        unit = self.make()
        self.client.post(reverse('farm:tank_delete', args=[unit.pk]))
        self.make(name='New', code='T1')
        with self.assertRaisesMessage(ValidationError, 'Another unit already uses this code.'):
            softdelete.restore(Tank.all_objects.get(pk=unit.pk), self.user)
        Tank.objects.filter(code='T1').update(code='T9')
        self.hall.soft_delete(self.user)
        with self.assertRaisesMessage(ValidationError, 'Production department “Hall A (HA)” is deleted.'):
            softdelete.restore(Tank.all_objects.get(pk=unit.pk), self.user)
        softdelete.restore(ProductionDepartment.all_objects.get(pk=self.hall.pk), self.user)
        softdelete.restore(Tank.all_objects.get(pk=unit.pk), self.user)
        restored = Tank.objects.get(pk=unit.pk)
        self.assertEqual((restored.status, restored.volume_m3), ('preparing', Decimal('4.712')))
        self.assertEqual(AuditLog.objects.filter(action='restore', entity_type='unit').count(), 1)

    def test_the_admin_lists_deleted_units_and_restores_them(self):
        root = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(root)
        unit = self.make()
        unit.soft_delete(root)
        self.assertContains(self.client.get(reverse('admin:farm_tank_changelist')), 'Tank')
        response = self.client.post(reverse('admin:farm_tank_changelist'),
                                    {'action': 'restore', '_selected_action': [str(unit.pk)]}, follow=True)
        self.assertContains(response, '1 record restored.')
        self.assertTrue(Tank.objects.filter(pk=unit.pk).exists())


class TankListTests(TankTestCase):
    def setUp(self):
        super().setUp()
        self.alpha = self.make(name='Alpha tank', code='AT', regulatory_unit_id='KAR-12', system=self.ras_a,
                               status='active')
        self.pond = self.make('pond', name='Beta pond', code='BP', department=self.hall_b, water_type='brackish')
        self.cage = self.make('cage', name='Gamma merd', code='GM', department=self.sea, system=self.cage_line,
                              water_type='saltwater', max_density_kg_m3=Decimal('25'))

    def rows(self, **query):
        return [unit.code for unit in self.client.get(reverse('farm:tank_list'), query).context['objects']]

    def test_listed_site_by_site_and_department_by_department(self):
        self.assertEqual(self.rows(), ['AT', 'BP', 'GM'])

    def test_search_and_filters(self):
        self.assertEqual(self.rows(q='kar-12'), ['AT'])
        self.assertEqual(self.rows(q='gamma'), ['GM'])
        self.assertEqual(self.rows(q='bp'), ['BP'])
        self.assertEqual(self.rows(site=self.tromso.pk), ['GM'])
        self.assertEqual(self.rows(production_department=self.hall_b.pk), ['BP'])
        self.assertEqual(self.rows(system=self.cage_line.pk), ['GM'])
        self.assertEqual(self.rows(system='none'), ['BP'])
        self.assertEqual(self.rows(kind='pond'), ['BP'])
        self.assertEqual(self.rows(status='active'), ['AT'])
        self.assertEqual(self.rows(water_type='saltwater'), ['GM'])
        self.assertEqual(len(self.rows(site='x', system='y', kind='z', status='w', water_type='v')), 3)
        self.assertEqual(self.rows(q='%'), [])

    def test_columns_show_labels_and_numbers(self):
        response = self.client.get(reverse('farm:tank_list'))
        self.assertContains(response, 'Circular')                        # the shape under the kind
        self.assertContains(response, 'Floating · Circular')
        self.assertContains(response, 'Earthen')
        self.assertContains(response, 'Brackish')
        self.assertContains(response, '1,500')                            # the pond's volume
        self.assertContains(response, '<span class="badge badge-preparing">Preparing</span>', html=True)
        self.assertNotContains(response, '>freshwater<')                  # never the stored value
        self.assertContains(response, 'Tanks, ponds &amp; cages</h1>')

    def test_the_production_overview_counts_units_by_kind(self):
        response = self.client.get(reverse('production_home'))
        self.assertIn({'label': 'Tanks, ponds & cages', 'count': 3, 'url': reverse('farm:tank_list')},
                      [{**tile, 'label': str(tile['label'])} for tile in response.context['tiles']])
        self.assertEqual([(item['value'], item['count']) for item in response.context['units_by_kind']],
                         [('tank', 1), ('pond', 1), ('cage', 1)])
        self.assertContains(response, f'href="{reverse("farm:tank_list")}?kind=cage"')

    def test_the_systems_list_counts_their_units(self):
        self.make(name='Second', code='T2', system=self.ras_a)
        Tank.objects.filter(code='T2').get().soft_delete(self.user)
        systems = {system.code: system.units for system in self.client.get(reverse('farm:system_list')).context['objects']}
        self.assertEqual(systems, {'R1': 0, 'RA': 1, 'CL': 1})


class TankAuditTests(TankTestCase):
    def test_create_and_edit_are_logged_with_the_calculated_values_and_the_status(self):
        self.post(unit_data(self.hall, water_type='saltwater'))
        unit = Tank.objects.get()
        self.post(unit_data(self.hall, water_type='saltwater', depth='2', status='inactive',
                            status_reason='Pump replaced', version='1'), unit)
        created, edited = AuditLog.objects.order_by('created_at')
        self.assertEqual((created.action, created.entity_type, created.entity_label), ('create', 'unit', 'Start tank 1 (T-01)'))
        self.assertEqual(created.changes['Kind'], [None, message('Tank')])
        self.assertEqual(created.changes['Shape'], [None, message('Circular')])
        self.assertEqual(created.changes['Water type'], [None, message('Saltwater')])
        self.assertEqual(created.changes['Volume (m³)'], [None, '4.712'])
        self.assertEqual(created.changes['Max biomass (kg)'], [None, '282.72'])
        self.assertNotIn('Stated volume (m³)', created.changes)
        self.assertEqual(edited.changes, {
            'Status': [message('Preparing'), message('Inactive')],
            'Reason for the status': [None, 'Pump replaced'],
            'Depth (m)': ['1.50', '2.00'],
            'Volume (m³)': ['4.712', '6.283'],
            'Max biomass (kg)': ['282.72', '376.98'],
        })

    def test_cleared_fields_of_another_shape_show_in_the_log(self):
        unit = self.make()
        self.post(unit_data(self.hall, name='Tank', code='T1', shape='raceway', diameter='', length='30', width='3',
                            depth='1', version='1'), unit)
        changes = AuditLog.objects.get().changes
        self.assertEqual(changes['Diameter (m)'], ['2.00', None])
        self.assertEqual(changes['Length (m)'], [None, '30.00'])
        self.assertEqual(changes['Volume (m³)'], ['4.712', '90.000'])

    def test_the_log_is_english_whatever_the_language(self):
        Profile.objects.create(user=self.user, language='nb')
        self.post(unit_data(self.hall, 'pond', depth='1,5', surface_area_m2='1000'))
        entry = AuditLog.objects.get()
        self.assertEqual(entry.entity_type, 'unit')
        self.assertEqual(entry.changes['Pond type'], [None, message('Earthen')])
        self.assertEqual(Tank.objects.get().depth, Decimal('1.50'))


class TankPermissionTests(TankTestCase):
    def test_a_read_only_role_sees_units_but_cannot_change_them(self):
        viewer = get_user_model().objects.create_user('ola', 'ola@example.com', 'x')
        viewer.groups.add(role('Viewer', 'view_tank'))
        self.client.force_login(viewer)
        unit = self.make()
        response = self.client.get(reverse('farm:tank_list'))
        self.assertContains(response, 'Tank')
        self.assertNotContains(response, reverse('farm:tank_edit', args=[unit.pk]))
        self.assertNotContains(response, reverse('farm:tank_create'))
        for url in (reverse('farm:tank_create'), reverse('farm:tank_edit', args=[unit.pk]),
                    reverse('farm:tank_delete', args=[unit.pk])):
            self.assertEqual(self.client.post(url, unit_data(self.hall)).status_code, 403, url)
        self.assertFalse(Tank.objects.get().is_deleted)

    def test_each_action_needs_its_own_permission(self):
        unit = self.make()
        for codename, url, allowed in [
            ('add_tank', reverse('farm:tank_create'), 200),
            ('change_tank', reverse('farm:tank_edit', args=[unit.pk]), 200),
            ('delete_tank', reverse('farm:tank_delete', args=[unit.pk]), 200),
        ]:
            with self.subTest(codename=codename):
                person = get_user_model().objects.create_user(codename, f'{codename}@example.com', 'x')
                person.groups.add(role(codename, 'view_tank', codename))
                self.client.force_login(person)
                self.assertEqual(self.client.get(url).status_code, allowed)
                others = [other for other in (reverse('farm:tank_create'), reverse('farm:tank_edit', args=[unit.pk]),
                                              reverse('farm:tank_delete', args=[unit.pk])) if other != url]
                for other in others:
                    self.assertEqual(self.client.get(other).status_code, 403, other)

    def test_no_view_permission_no_tab_and_no_menu_entry(self):
        stranger = get_user_model().objects.create_user('per', 'per@example.com', 'x')
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(reverse('farm:tank_list')).status_code, 403)
        self.assertNotContains(self.client.get(reverse('production_home')), reverse('farm:tank_list'))

    def test_the_menu_and_the_matrix_place_it_after_equipment_under_facility_structure(self):
        response = self.client.get(reverse('farm:tank_list'))
        self.assertEqual(str(response.context['group']), 'Facility structure')
        self.assertEqual(str(response.context['title']), 'Tanks, ponds & cages')
        place = navigation.place('farm.view_tank')
        self.assertEqual(str(place.path), 'Production · Setup · Facility structure')
        self.assertEqual([entry.perm for entry in place.group.entries][-2:], ['farm.view_equipment', 'farm.view_tank'])
        (area,) = [area for area in access.areas() if area.model == 'farm.Tank']
        self.assertEqual((str(area.label), str(area.group)), ('Tanks, ponds & cages', 'Production · Setup · Facility structure'))


class TankDatabaseViewerTests(TankTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(get_user_model().objects.create_superuser('root', 'root@example.com', 'x'))

    def test_the_table_is_shown_with_its_generated_columns(self):
        unit = self.make()
        table = database.find('tanks')
        self.assertEqual(table.description, 'A unit fish are held in: a tank, a pond or a cage.')
        columns = {column.name: column for column in table.structure().columns}
        self.assertTrue(columns['volume_m3'].default.startswith('generated always as ('), columns['volume_m3'].default)
        self.assertTrue(dbgrid.is_numeric(columns['volume_m3']))
        grid = dbgrid.Grid(table, table.structure(), {'f_volume_m3': '4.712'})
        self.assertEqual(len(grid.rows), 1)
        grid = dbgrid.Grid(table, table.structure(), {'f_volume_m3': '4.71'})
        self.assertEqual(len(grid.rows), 0)
        page = self.client.get(reverse('core:database_table', args=['tanks']))
        self.assertContains(page, str(unit.pk)[:8])
