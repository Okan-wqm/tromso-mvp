from datetime import date
from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from core import softdelete
from core.audit import message
from core.models import AuditLog, Profile

from ..equipment_types import TYPES
from ..models import (Equipment, EquipmentSystem, EquipmentType, FeederCalibration, ProductionDepartment, Site,
                      System)
from .helpers import leave_without_site, role, rows_data

EQUIPMENT_MANAGER = (
    'view_equipment', 'add_equipment', 'change_equipment', 'delete_equipment', 'view_site', 'delete_site',
    'view_productiondepartment', 'delete_productiondepartment', 'view_system', 'delete_system', 'view_auditlog',
)


def link(system, primary=False, role='', criticality=3):
    return system, primary, role, criticality


def equipment_data(kind, department, links=(), specs=None, **overrides):
    """What the equipment dialog posts."""
    data = {
        'name': 'Main pump', 'code': 'pmp-1', 'category': kind.category, 'equipment_type': str(kind.pk),
        'status': 'operational', 'production_department': str(department.pk), 'parent': '', 'manufacturer': '',
        'model': '', 'serial_number': '', 'purchase_date': '', 'warranty_end_date': '', 'installation_date': '',
        'description': '', 'notes': '', 'systems': [str(system.pk) for system, *_ in links],
    }
    for system, primary, role_text, criticality in links:
        data[f'systems-{system.pk}-role'] = role_text
        data[f'systems-{system.pk}-criticality'] = str(criticality)
        if primary:
            data['systems-primary'] = str(system.pk)
    for name, value in (specs or {}).items():
        data[f'spec__{kind.code}__{name}'] = value
    data.update(overrides)
    return data


def calibrations_data(rows, initial=0, record=None):
    return rows_data('calibrations', rows, initial, record)


class EquipmentTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        self.user.groups.add(role('Equipment manager', *EQUIPMENT_MANAGER))
        self.client.force_login(self.user)
        self.bergen = Site.objects.create(name='Bergen', code='BG')
        self.tromso = Site.objects.create(name='Tromso', code='TR')
        self.hall = ProductionDepartment.objects.create(site=self.bergen, name='Hall A', code='HA')
        self.hall_b = ProductionDepartment.objects.create(site=self.bergen, name='Hall B', code='HB')
        self.cages = ProductionDepartment.objects.create(site=self.tromso, name='Cages', code='CG')
        self.ras = System.objects.create(site=self.bergen, name='RAS 1', code='R1')
        self.ras2 = System.objects.create(site=self.bergen, name='RAS 2', code='R2')
        self.cage_line = System.objects.create(site=self.tromso, name='Cage line', code='CL')
        self.pump = EquipmentType.objects.get(code='pump-centrifugal')
        self.feeder = EquipmentType.objects.get(code='feeder-automatic')
        self.heater = EquipmentType.objects.get(code='heater')

    def make(self, name='Pump', code='P1', kind=None, department=None, systems=None, **fields):
        kind = kind or self.pump
        fields.setdefault('specifications', {'flowRate': 100} if kind == self.pump else {})
        equipment = Equipment.objects.create(name=name, code=code, equipment_type=kind,
                                             production_department=department or self.hall, **fields)
        for index, system in enumerate(systems if systems is not None else [self.ras]):
            EquipmentSystem.objects.create(equipment=equipment, system=system, is_primary=index == 0)
        return equipment

    def post(self, data, equipment=None):
        url = reverse('farm:equipment_edit', args=[equipment.pk]) if equipment else reverse('farm:equipment_create')
        return self.client.post(url, data)

    def errors(self, data, equipment=None):
        response = self.post(data, equipment)
        self.assertEqual(response.status_code, 200, 'the form was expected to be refused')
        return response.context['form'].errors

    def links(self, equipment):
        return list(equipment.system_links.order_by('system__name')
                    .values_list('system__code', 'is_primary', 'role', 'criticality'))


class EquipmentRoundTripTests(EquipmentTestCase):
    def test_create_read_edit_delete(self):
        # Create
        self.post(equipment_data(
            self.pump, self.hall, [link(self.ras, True, 'main circulation', 5), link(self.ras2)],
            {'flowRate': '120.5', 'head': '12', 'phase': 'three'}, manufacturer='Grundfos', model='NB 65',
            serial_number='SN-1', purchase_date='2026-01-10', warranty_end_date='2028-01-10',
            installation_date='2026-02-01', description='Feeds the RAS loop', notes='Spare seal in store'))
        pump = Equipment.objects.get()
        self.assertEqual(
            (pump.name, pump.code, pump.equipment_type, pump.status, pump.production_department, pump.parent,
             pump.manufacturer, pump.model, pump.serial_number, pump.purchase_date, pump.warranty_end_date,
             pump.installation_date, pump.description, pump.notes, pump.created_by, pump.version),
            ('Main pump', 'PMP-1', self.pump, 'operational', self.hall, None, 'Grundfos', 'NB 65', 'SN-1',
             date(2026, 1, 10), date(2028, 1, 10), date(2026, 2, 1), 'Feeds the RAS loop', 'Spare seal in store',
             self.user, 1))
        self.assertEqual(pump.specifications, {'flowRate': 120.5, 'head': 12, 'phase': 'three'})
        self.assertEqual(self.links(pump), [('R1', True, 'main circulation', 5), ('R2', False, '', 3)])

        # Read: listed, and the edit form is filled from the database
        response = self.client.get(reverse('farm:equipment_list'))
        self.assertEqual([e.pk for e in response.context['objects']], [pump.pk])
        self.assertContains(response, 'Centrifugal pump')
        form = self.client.get(reverse('farm:equipment_edit', args=[pump.pk])).context['form']
        self.assertEqual((form['category'].value(), form['equipment_type'].value(), form['description'].value()),
                         ('pump', pump.equipment_type_id, 'Feeds the RAS loop'))
        self.assertEqual(form['systems'].value(), [
            {'pk': str(self.ras.pk), 'primary': True, 'role': 'main circulation', 'criticality': 5},
            {'pk': str(self.ras2.pk), 'primary': False, 'role': '', 'criticality': 3}])
        self.assertEqual(form['spec__pump-centrifugal__flowRate'].value(), 120.5)

        # Edit: another department, one system, other specifications, status
        self.post(equipment_data(
            self.pump, self.hall_b, [link(self.ras2, role='backup')], {'flowRate': '90', 'voltage': '400'},
            name='Backup pump', status='standby', manufacturer='Grundfos', version='1'), pump)
        pump.refresh_from_db()
        self.assertEqual((pump.name, pump.status, pump.production_department, pump.version, pump.updated_by),
                         ('Backup pump', 'standby', self.hall_b, 2, self.user))
        self.assertEqual(pump.specifications, {'flowRate': 90, 'voltage': 400})
        self.assertEqual(self.links(pump), [('R2', True, 'backup', 3)])

        # Delete: hidden, kept with its links for a restore
        self.client.post(reverse('farm:equipment_delete', args=[pump.pk]))
        self.assertFalse(Equipment.objects.exists())
        self.assertTrue(Equipment.all_objects.get().is_deleted)
        self.assertEqual(EquipmentSystem.objects.count(), 1)

    def test_every_optional_field_can_be_cleared(self):
        parent = self.make(name='Filter unit', code='FU')
        pump = self.make(parent=parent, manufacturer='Grundfos', model='NB', serial_number='SN', description='x',
                         notes='y', purchase_date=date(2026, 1, 1), warranty_end_date=date(2027, 1, 1),
                         installation_date=date(2026, 2, 1), specifications={'flowRate': 100, 'head': 5})
        self.post(equipment_data(self.pump, self.hall, [link(self.ras)], {'flowRate': '100'}, name='Pump', code='P1',
                                 version='1'), pump)
        pump.refresh_from_db()
        self.assertEqual(
            (pump.parent, pump.manufacturer, pump.model, pump.serial_number, pump.description, pump.notes,
             pump.purchase_date, pump.warranty_end_date, pump.installation_date, pump.specifications),
            (None, '', '', '', '', '', None, None, None, {'flowRate': 100}))

    def test_the_form_opens_in_the_dialog_with_its_tabs(self):
        response = self.client.get(reverse('farm:equipment_create'), headers={'X-Modal': '1'})
        self.assertContains(response, 'class="modal-head"')
        for tab in ('general', 'location', 'details', 'specifications'):
            self.assertContains(response, f'data-tab="{tab}"')
        self.assertContains(response, 'Choose a type on the General tab')


class EquipmentValidationTests(EquipmentTestCase):
    def test_name_code_type_department_and_a_system_are_required(self):
        errors = self.errors(equipment_data(self.pump, self.hall, name='', code='', category='', equipment_type='',
                                            production_department=''))
        self.assertEqual(set(errors), {'name', 'code', 'category', 'equipment_type', 'production_department',
                                       'systems'})

    def test_code_is_unique_among_live_equipment(self):
        old = self.make(code='PMP-1')
        errors = self.errors(equipment_data(self.pump, self.hall, [link(self.ras)], {'flowRate': '1'}))
        self.assertEqual(errors['code'], ['Other equipment already uses this code.'])
        old.soft_delete(self.user)
        self.post(equipment_data(self.pump, self.hall, [link(self.ras)], {'flowRate': '1'}))
        self.assertEqual(Equipment.objects.get().code, 'PMP-1')

    def test_a_serial_number_is_unique_among_live_equipment_when_given(self):
        self.make(code='A', serial_number='SN-1')
        self.make(code='B')
        errors = self.errors(equipment_data(self.pump, self.hall, [link(self.ras)], {'flowRate': '1'},
                                            serial_number='SN-1'))
        self.assertEqual(errors['serial_number'], ['Other equipment already has this serial number.'])
        self.post(equipment_data(self.pump, self.hall, [link(self.ras)], {'flowRate': '1'}))
        self.assertEqual(Equipment.objects.filter(serial_number='').count(), 2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make(code='C', serial_number='SN-1')

    def test_the_warranty_cannot_end_before_the_purchase(self):
        errors = self.errors(equipment_data(self.pump, self.hall, [link(self.ras)], {'flowRate': '1'},
                                            purchase_date='2026-05-01', warranty_end_date='2026-04-30'))
        self.assertEqual(errors['warranty_end_date'], ['The warranty cannot end before the purchase date.'])
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make(purchase_date=date(2026, 5, 1), warranty_end_date=date(2026, 4, 30))

    def test_the_type_must_be_of_the_chosen_category(self):
        data = equipment_data(self.pump, self.hall, [link(self.ras)], {'flowRate': '1'}, category='feeding')
        self.assertEqual(self.errors(data)['equipment_type'], ['This type is not in the chosen category.'])

    def test_a_type_no_longer_offered_is_kept_by_its_equipment_but_not_offered_to_new_ones(self):
        pump = self.make()
        EquipmentType.objects.filter(pk=self.pump.pk).update(is_active=False)
        self.assertNotIn(self.pump, self.client.get(reverse('farm:equipment_create')).context['form']
                         .fields['equipment_type'].queryset)
        self.assertIn('equipment_type', self.errors(equipment_data(self.pump, self.hall, [link(self.ras)])))
        self.post(equipment_data(self.pump, self.hall, [link(self.ras)], {'flowRate': '5'}, name='Pump', code='P1',
                                 version='1'), pump)
        pump.refresh_from_db()
        self.assertEqual(pump.specifications, {'flowRate': 5})

    def test_the_department_must_be_on_a_site(self):
        pump = self.make(department=ProductionDepartment.objects.create(site=self.bergen, name='Orphan', code='OR'),
                         systems=[])
        orphan = leave_without_site(pump.production_department)   # a deleted site's, before F-212
        self.assertNotIn(orphan, self.client.get(reverse('farm:equipment_create')).context['form']
                         .fields['production_department'].queryset)
        errors = self.errors(equipment_data(self.pump, orphan, [link(self.ras)], {'flowRate': '1'}, code='P1',
                                            version='1'), pump)
        self.assertEqual(errors['production_department'],
                         ['This production department is not on any site; choose one that is.'])

    def test_the_department_offers_its_site_in_its_label(self):
        form = self.client.get(reverse('farm:equipment_create')).context['form']
        self.assertIn('Bergen · Hall A', form['production_department'].as_widget())


class EquipmentSystemLinkTests(EquipmentTestCase):
    def test_at_least_one_system(self):
        self.assertEqual(self.errors(equipment_data(self.pump, self.hall, [], {'flowRate': '1'}))['systems'],
                         ['Choose at least one.'])

    def test_a_single_system_is_the_primary_one(self):
        self.post(equipment_data(self.pump, self.hall, [link(self.ras2)], {'flowRate': '1'}))
        self.assertEqual(self.links(Equipment.objects.get()), [('R2', True, '', 3)])

    def test_with_several_systems_one_must_be_marked_primary(self):
        errors = self.errors(equipment_data(self.pump, self.hall, [link(self.ras), link(self.ras2)], {'flowRate': '1'}))
        self.assertEqual(errors['systems'], ['Mark which one is the primary one.'])

    def test_every_system_must_be_on_the_departments_site(self):
        errors = self.errors(equipment_data(self.pump, self.hall, [link(self.cage_line)], {'flowRate': '1'}))
        self.assertEqual(errors['systems'], ['Cage line (CL) is on another site than the production department.'])
        self.assertFalse(Equipment.objects.exists())

    def test_link_details_are_checked(self):
        data = equipment_data(self.pump, self.hall, [link(self.ras, True, 'r' * 51, 9)], {'flowRate': '1'})
        errors = self.errors(data)['systems']
        self.assertEqual(len(errors), 2)
        self.assertTrue(all(error.startswith('RAS 1 (R1) · ') for error in errors), errors)
        with self.assertRaises(IntegrityError), transaction.atomic():
            EquipmentSystem.objects.create(equipment=self.make(systems=[]), system=self.ras, criticality=6)

    def test_the_database_allows_one_primary_and_one_row_per_system(self):
        pump = self.make()
        with self.assertRaises(IntegrityError), transaction.atomic():
            EquipmentSystem.objects.create(equipment=pump, system=self.ras2, is_primary=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            EquipmentSystem.objects.create(equipment=pump, system=self.ras)

    def test_the_rows_know_the_sites_of_the_departments(self):
        html = self.client.get(reverse('farm:equipment_create')).content.decode()
        self.assertIn('data-depends-on="production_department"', html)
        self.assertIn(f'data-group="{" ".join(sorted([str(self.hall.pk), str(self.hall_b.pk)]))}"', html)
        self.assertIn(f'data-group="{self.cages.pk}"', html)

    def test_links_to_deleted_systems_are_hidden_and_dropped_on_save(self):
        pump = self.make(systems=[self.ras, self.ras2])
        self.ras.soft_delete(self.user)
        form = self.client.get(reverse('farm:equipment_edit', args=[pump.pk])).context['form']
        self.assertEqual([row['pk'] for row in form['systems'].value()], [str(self.ras2.pk)])
        self.assertIn('Its links to deleted systems (RAS 1 (R1)) are dropped when it is saved.',
                      str(form.fields['systems'].help_text))
        self.post(equipment_data(self.pump, self.hall, [link(self.ras2)], {'flowRate': '100'}, name='Pump',
                                 code='P1', version='1'), pump)
        self.assertEqual(self.links(pump), [('R2', True, '', 3)])


class EquipmentParentTests(EquipmentTestCase):
    def test_a_parent_must_be_on_the_same_site(self):
        elsewhere = self.make(name='Cage feeder', code='CF', department=self.cages, systems=[self.cage_line])
        errors = self.errors(equipment_data(self.pump, self.hall, [link(self.ras)], {'flowRate': '1'},
                                            parent=str(elsewhere.pk)))
        self.assertEqual(errors['parent'], ['The parent equipment is on another site.'])
        # Another production department of the same site is fine.
        unit = self.make(name='Filter unit', code='FU', department=self.hall_b)
        self.post(equipment_data(self.pump, self.hall, [link(self.ras)], {'flowRate': '1'}, parent=str(unit.pk)))
        self.assertEqual(Equipment.objects.get(code='PMP-1').parent, unit)

    def test_no_loops(self):
        top = self.make(name='Skid', code='SK')
        middle = self.make(name='Unit', code='UN', parent=top)
        bottom = self.make(name='Motor', code='MO', parent=middle)
        offered = self.client.get(reverse('farm:equipment_edit', args=[top.pk])).context['form'].fields['parent'].queryset
        self.assertEqual(set(offered), set())
        offered = self.client.get(reverse('farm:equipment_edit', args=[bottom.pk])).context['form'].fields['parent'].queryset
        self.assertEqual(set(offered), {top, middle})
        errors = self.errors(equipment_data(self.pump, self.hall, [link(self.ras)], {'flowRate': '1'}, name='Skid',
                                            code='SK', parent=str(bottom.pk), version='1'), top)
        self.assertIn('parent', errors)
        top.parent = bottom
        with self.assertRaisesMessage(ValidationError, 'one of its own parts'):
            top.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Equipment.objects.filter(pk=top.pk).update(parent=top)

    def test_moving_to_another_site_needs_the_parts_moved_first(self):
        unit = self.make(name='Filter unit', code='FU')
        self.make(name='Motor', code='MO', parent=unit)
        errors = self.errors(equipment_data(self.pump, self.cages, [link(self.cage_line)], {'flowRate': '1'},
                                            name='Filter unit', code='FU', version='1'), unit)
        self.assertEqual(errors['production_department'],
                         ['Its parts are on another site: Motor (MO). Move them first.'])


class SpecificationTests(EquipmentTestCase):
    def spec_errors(self, kind, specs):
        return self.errors(equipment_data(kind, self.hall, [link(self.ras)], specs))

    def test_required_bounds_choices_and_whole_numbers_are_checked_on_the_field(self):
        errors = self.spec_errors(self.pump, {'head': '-1', 'phase': 'four'})
        self.assertEqual(errors['spec__pump-centrifugal__flowRate'], ['This field is required.'])
        self.assertEqual(errors['spec__pump-centrifugal__head'], ['Ensure this value is greater than or equal to 0.'])
        self.assertIn('spec__pump-centrifugal__phase', errors)
        inlet = EquipmentType.objects.get(code='tank-inlet')
        errors = self.spec_errors(inlet, {'pipeSize': '110', 'holeCount': '2.5'})
        self.assertEqual(errors['spec__tank-inlet__holeCount'], ['Enter a whole number.'])
        heater_errors = self.spec_errors(self.heater, {'heatingCapacity': '5', 'fuelType': 'gas', 'efficiency': '101'})
        self.assertEqual(heater_errors['spec__heater__efficiency'], ['Ensure this value is less than or equal to 100.'])

    def test_the_tab_with_errors_is_flagged(self):
        response = self.post(equipment_data(self.pump, self.hall, [link(self.ras)], {}))
        tabs = {tab['key']: tab['has_errors'] for tab in response.context['form'].tab_list()}
        self.assertEqual(tabs, {'general': False, 'location': False, 'details': False, 'specifications': True})

    def test_empty_values_are_not_stored_and_choices_are_stored_in_their_order(self):
        probe = EquipmentType.objects.get(code='sensor-multiparameter')
        data = equipment_data(probe, self.hall, [link(self.ras)], {'measurementRange': '', 'accuracy': ' '})
        data['spec__sensor-multiparameter__parameters'] = ['do', 'temperature']
        self.post(data)
        self.assertEqual(Equipment.objects.get().specifications, {'parameters': ['temperature', 'do']})

    def test_groups_of_a_type_are_shown_under_their_heading(self):
        form = self.client.post(reverse('farm:equipment_create'), {'_draft': '1', 'equipment_type': self.pump.pk,
                                                                  'category': 'pump'}).context['form']
        (spec_tab,) = [tab for tab in form.tab_list() if tab['key'] == 'specifications']
        self.assertEqual([(fieldset['label'], [f.name for f in fieldset['fields']]) for fieldset in spec_tab['fieldsets']], [
            ('Performance', ['spec__pump-centrifugal__flowRate', 'spec__pump-centrifugal__head']),
            ('Electrical', ['spec__pump-centrifugal__power', 'spec__pump-centrifugal__voltage',
                            'spec__pump-centrifugal__phase'])])

    def test_numbers_are_read_and_shown_the_way_the_language_writes_them(self):
        Profile.objects.create(user=self.user, language='nb')
        self.post(equipment_data(self.pump, self.hall, [link(self.ras)], {'flowRate': '120,5'}))
        pump = Equipment.objects.get()
        self.assertEqual(pump.specifications, {'flowRate': 120.5})
        self.assertContains(self.client.get(reverse('farm:equipment_edit', args=[pump.pk])), 'value="120,5"')

    def test_a_new_type_starts_from_its_defaults_and_a_changed_type_drops_the_old_values(self):
        inlet = EquipmentType.objects.get(code='tank-inlet')
        form = self.client.post(reverse('farm:equipment_create'), {'_draft': '1', 'equipment_type': inlet.pk,
                                                                  'category': 'plumbing'}).context['form']
        self.assertEqual((form['spec__tank-inlet__pipeSize'].value(), form['spec__tank-inlet__material'].value()),
                         (110, 'pvc'))
        pump = self.make(specifications={'flowRate': 100, 'power': 4})
        self.post(equipment_data(self.heater, self.hall, [link(self.ras)], {'heatingCapacity': '20', 'fuelType': 'gas'},
                                 name='Pump', code='P1', version='1'), pump)
        pump.refresh_from_db()
        self.assertEqual((pump.equipment_type, pump.specifications),
                         (self.heater, {'heatingCapacity': 20, 'fuelType': 'gas'}))

    def test_stored_values_are_checked_against_the_type_whatever_wrote_them(self):
        pump = self.make()
        for stored, words in [({'flowRate': 100, 'colour': 'red'}, '“colour” is not one of the specifications'),
                              ({'flowRate': '100'}, 'not in the form it is saved in'),
                              ({'flowRate': 100, 'head': ''}, 'not in the form it is saved in'),
                              ({'flowRate': -1}, 'greater than or equal to 0'),
                              ({}, 'This field is required'),
                              ({'flowRate': 1, 'phase': 'four'}, 'Select a valid choice')]:
            pump.specifications = stored
            with self.subTest(stored=stored), self.assertRaisesMessage(ValidationError, words):
                pump.full_clean()
        pump.specifications = {'flowRate': 100.25, 'phase': 'single'}
        pump.full_clean()

    def test_every_type_of_the_catalogue_is_in_the_database_and_builds_its_form(self):
        stored = {kind.code: kind for kind in EquipmentType.objects.all()}
        self.assertEqual(set(stored), {entry['code'] for entry in TYPES})
        for entry in TYPES:
            kind = stored[entry['code']]
            with self.subTest(type=kind.code):
                self.assertEqual((kind.name, kind.category, kind.specification_schema, kind.is_active),
                                 (entry['name'], entry['category'], entry['specification_schema'], True))
                kind.full_clean()
                self.assertTrue(kind.schema.form_fields())
        self.assertFalse(stored.keys() & {'tank-circular', 'pond-earthen', 'cage-floating'})

    def test_a_malformed_schema_is_refused(self):
        kind = EquipmentType(code='x', name='X', category='other',
                             specification_schema={'fields': [{'name': 'a', 'label': 'A', 'type': 'colour'}]})
        with self.assertRaisesMessage(ValidationError, "unknown type 'colour'"):
            kind.full_clean()


class DraftTests(EquipmentTestCase):
    """Changing the type renders the form again with what was entered (core.crud.TabbedForm.refresh_on)."""

    def test_the_category_and_type_ask_for_a_new_form(self):
        html = self.client.get(reverse('farm:equipment_create')).content.decode()
        self.assertEqual(html.count('data-refresh="_draft"'), 2)
        self.assertIn('data-depends-on="category"', html)

    def test_a_draft_keeps_what_was_entered_and_shows_no_errors(self):
        response = self.client.post(reverse('farm:equipment_create'), {
            '_draft': '1', 'name': 'Feeder 1', 'code': 'fd-1', 'category': 'feeding',
            'equipment_type': self.feeder.pk, 'production_department': self.hall.pk, 'systems': [self.ras.pk],
            f'systems-{self.ras.pk}-role': 'feeding', 'spec__pump-centrifugal__flowRate': '99'})
        form = response.context['form']
        self.assertFalse(form.is_bound)
        self.assertEqual((form['name'].value(), form['equipment_type'].value(), form['systems'].value()[0]['role']),
                         ('Feeder 1', str(self.feeder.pk), 'feeding'))
        self.assertIn('spec__feeder-automatic__capacity', form.fields)
        self.assertNotIn('spec__pump-centrifugal__flowRate', form.fields)
        self.assertNotContains(response, 'errorlist')
        self.assertContains(response, 'data-tab="calibration"')
        self.assertContains(response, 'Calibrations can be added once the equipment is created.')
        self.assertFalse(Equipment.objects.exists())
        self.assertFalse(AuditLog.objects.exists())

    def test_a_draft_of_an_existing_record_keeps_what_cannot_be_typed_and_saves_nothing(self):
        pump = self.make()
        form = self.client.post(reverse('farm:equipment_edit', args=[pump.pk]), {
            '_draft': '1', 'name': 'Renamed', 'version': '1'}).context['form']
        self.assertEqual((form['name'].value(), form['version'].value()), ('Renamed', '1'))
        stored = Equipment.objects.get(pk=pump.pk)
        self.assertEqual((stored.name, stored.version), (pump.name, pump.version))

    def test_a_draft_travels_in_the_request_body_not_the_address(self):
        long_notes = 'Inspected. ' * 1000    # far beyond what an address may carry
        response = self.client.post(reverse('farm:equipment_create'), {
            '_draft': '1', 'equipment_type': self.pump.pk, 'category': 'pump', 'notes': long_notes})
        self.assertEqual(response.context['form']['notes'].value(), long_notes)
        self.assertFalse(Equipment.objects.exists())
        address = self.client.get(reverse('farm:equipment_create'), {'_draft': '1', 'name': 'From the address'})
        self.assertIsNone(address.context['form']['name'].value())    # a draft in the address is not read


class FeederCalibrationTests(EquipmentTestCase):
    def setUp(self):
        super().setUp()
        self.unit = self.make(name='Feeder', code='FD', kind=self.feeder,
                              specifications={'capacity': 50, 'siloVolume': 200})
        self.url = reverse('farm:equipment_calibrations', args=[self.unit.pk])

    def test_create_read_edit_delete(self):
        self.client.post(self.url, calibrations_data([
            {'feed_size_mm': '3', 'label': 'Starter', 'grams_per_dispensing': '25', 'silo_capacity_kg': '250',
             'notes': 'top up daily'},
            {'feed_size_mm': '1.5', 'grams_per_dispensing': '10.5', 'silo_capacity_kg': '0'},
            {'feed_size_mm': '', 'label': '', 'grams_per_dispensing': '', 'silo_capacity_kg': ''},   # left blank
        ], record=self.unit))
        rows = list(self.unit.calibrations.values_list('feed_size_mm', 'label', 'grams_per_dispensing',
                                                       'silo_capacity_kg', 'notes', 'created_by'))
        self.assertEqual(rows, [(Decimal('1.50'), '', Decimal('10.50'), Decimal('0.00'), '', self.user.pk),
                                (Decimal('3.00'), 'Starter', Decimal('25.00'), Decimal('250.00'), 'top up daily',
                                 self.user.pk)])
        page = self.client.get(reverse('farm:equipment_edit', args=[self.unit.pk]))
        self.assertEqual(page.context['calibrations'].forms[1]['label'].value(), 'Starter')
        small, starter = self.unit.calibrations.all()
        self.client.post(self.url, calibrations_data([
            {'id': str(small.pk), 'feed_size_mm': '1.5', 'grams_per_dispensing': '12', 'silo_capacity_kg': '0',
             'DELETE': True},
            {'id': str(starter.pk), 'feed_size_mm': '3', 'label': 'Starter', 'grams_per_dispensing': '30',
             'silo_capacity_kg': '250'},
        ], initial=2, record=self.unit))
        self.assertEqual(list(self.unit.calibrations.values_list('feed_size_mm', 'grams_per_dispensing')),
                         [(Decimal('3.00'), Decimal('30.00'))])

    def test_values_are_checked(self):
        response = self.client.post(self.url, calibrations_data([
            {'feed_size_mm': '0', 'grams_per_dispensing': '0.05', 'silo_capacity_kg': '-1'},
            {'feed_size_mm': '2', 'grams_per_dispensing': '1', 'silo_capacity_kg': '1'},
            {'feed_size_mm': '2.00', 'grams_per_dispensing': '1', 'silo_capacity_kg': '1'},
        ], record=self.unit))
        formset = response.context['calibrations']
        self.assertEqual(set(formset.forms[0].errors), {'feed_size_mm', 'grams_per_dispensing', 'silo_capacity_kg'})
        self.assertIn('Two rows have the same feed size.', formset.non_form_errors())
        self.assertEqual(response.context['open_tab'], 'calibration')
        self.assertFalse(self.unit.calibrations.exists())

    def test_at_most_fifty(self):
        rows = [{'feed_size_mm': str(size), 'grams_per_dispensing': '1', 'silo_capacity_kg': '1'} for size in range(1, 52)]
        response = self.client.post(self.url, calibrations_data(rows, record=self.unit))
        self.assertIn('A feeder has at most 50 calibrations.', response.context['calibrations'].non_form_errors())
        self.assertFalse(self.unit.calibrations.exists())

    def test_only_a_feeder_has_them(self):
        pump = self.make()
        self.assertNotContains(self.client.get(reverse('farm:equipment_edit', args=[pump.pk])), 'data-tab="calibration"')
        url = reverse('farm:equipment_calibrations', args=[pump.pk])
        self.assertEqual(self.client.post(url, calibrations_data([], record=pump)).status_code, 404)
        row = FeederCalibration(equipment=pump, feed_size_mm=Decimal(1), grams_per_dispensing=Decimal(1),
                                silo_capacity_kg=Decimal(1))
        with self.assertRaisesMessage(ValidationError, 'Only a feeder has feed calibrations.'):
            row.full_clean()

    def test_a_feeder_with_calibrations_keeps_a_feeder_type(self):
        FeederCalibration.objects.create(equipment=self.unit, feed_size_mm=3, grams_per_dispensing=25, silo_capacity_kg=1)
        errors = self.errors(equipment_data(self.pump, self.hall, [link(self.ras)], {'flowRate': '1'}, name='Feeder',
                                            code='FD', version='1'), self.unit)
        self.assertIn('It has feed calibrations', errors['equipment_type'][0])
        demand = EquipmentType.objects.get(code='feeder-demand')
        self.post(equipment_data(demand, self.hall, [link(self.ras)], {'capacity': '50', 'siloVolume': '200'},
                                 name='Feeder', code='FD', version='1'), self.unit)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.equipment_type, demand)

    def test_saving_is_logged_on_the_equipment(self):
        self.client.post(self.url, calibrations_data([
            {'feed_size_mm': '3', 'label': 'Starter', 'grams_per_dispensing': '25', 'silo_capacity_kg': '250'}],
            record=self.unit))
        entry = AuditLog.objects.get()
        self.assertEqual((entry.action, entry.entity_type, entry.entity_label), ('update', 'equipment', 'Feeder (FD)'))
        self.assertEqual(entry.changes, {'Feed calibrations': [None, '3.00 mm Starter: 25.00 g per shot, silo 250.00 kg']})


class EquipmentDeletePlanTests(EquipmentTestCase):
    def log(self):
        return sorted(AuditLog.objects.values_list('action', 'entity_type', 'entity_label'))

    def test_deleting_a_production_department_deletes_its_equipment_and_their_parts(self):
        unit = self.make(name='Filter unit', code='FU')
        self.make(name='Motor', code='MO', parent=unit, department=self.hall_b)
        page = self.client.get(reverse('farm:productiondepartment_delete', args=[self.hall.pk]))
        self.assertContains(page, 'Equipment deleted with it')
        self.client.post(reverse('farm:productiondepartment_delete', args=[self.hall.pk]))
        self.assertFalse(Equipment.objects.exists())
        self.assertEqual(self.log(), [('delete', 'equipment', 'Filter unit (FU)'), ('delete', 'equipment', 'Motor (MO)'),
                                      ('delete', 'production department', 'Hall A (HA)')])

    def test_deleting_equipment_deletes_its_parts(self):
        unit = self.make(name='Filter unit', code='FU')
        self.make(name='Motor', code='MO', parent=unit)
        self.assertContains(self.client.get(reverse('farm:equipment_delete', args=[unit.pk])), 'Motor (MO)')
        self.client.post(reverse('farm:equipment_delete', args=[unit.pk]))
        self.assertEqual(self.log(), [('delete', 'equipment', 'Filter unit (FU)'), ('delete', 'equipment', 'Motor (MO)')])

    def test_deleting_a_system_keeps_the_links_and_restoring_it_brings_them_back(self):
        pump = self.make()
        page = self.client.get(reverse('farm:system_delete', args=[self.ras.pk]))
        self.assertContains(page, 'Equipment linked to it')
        self.assertContains(page, 'Pump (P1)')
        self.client.post(reverse('farm:system_delete', args=[self.ras.pk]))
        self.assertEqual(EquipmentSystem.objects.get().system, self.ras)
        listing = self.client.get(reverse('farm:equipment_list'))
        self.assertContains(listing, 'No system')
        self.assertContains(listing, '1 piece of equipment is not linked to any system.')
        self.assertEqual(self.log(), [('delete', 'system', 'RAS 1 (R1)')])
        softdelete.restore(System.all_objects.get(pk=self.ras.pk), self.user)
        self.assertEqual(pump.live_links()[0].system, self.ras)
        self.assertNotContains(self.client.get(reverse('farm:equipment_list')), 'not linked to any system')

    def test_deleting_a_site_deletes_its_equipment_with_its_departments_and_restoring_it_brings_them_back(self):
        pump = self.make()
        self.client.post(reverse('farm:site_delete', args=[self.bergen.pk]))
        pump.refresh_from_db()
        self.assertTrue(pump.is_deleted)
        softdelete.restore(Site.all_objects.get(pk=self.bergen.pk), self.user)
        pump.refresh_from_db()
        self.assertFalse(pump.is_deleted)
        self.assertEqual(pump.live_links()[0].system, self.ras)

    def test_a_restored_equipment_is_checked_like_a_new_one(self):
        pump = self.make()
        self.client.post(reverse('farm:equipment_delete', args=[pump.pk]))
        self.make(name='New pump', code='P1')
        with self.assertRaisesMessage(ValidationError, 'Other equipment already uses this code.'):
            softdelete.restore(Equipment.all_objects.get(pk=pump.pk), self.user)
        Equipment.objects.filter(code='P1').update(code='P2')
        self.hall.soft_delete(self.user)
        with self.assertRaisesMessage(ValidationError, 'Production department “Hall A (HA)” is deleted.'):
            softdelete.restore(Equipment.all_objects.get(pk=pump.pk), self.user)


class EquipmentListTests(EquipmentTestCase):
    def setUp(self):
        super().setUp()
        self.unit = self.make(name='Alpha filter unit', code='AF', serial_number='SN-77')
        self.motor = self.make(name='Alpha motor', code='AM', parent=self.unit, systems=[self.ras2],
                               status='repair')
        self.feeder_unit = self.make(name='Beta feeder', code='BF', kind=self.feeder, department=self.cages,
                                     systems=[self.cage_line], specifications={'capacity': 5, 'siloVolume': 9})
        self.lonely = self.make(name='Gamma heater', code='GH', kind=self.heater, systems=[],
                                specifications={'heatingCapacity': 3, 'fuelType': 'oil'})

    def rows(self, **query):
        return [(e.code, e.depth) for e in self.client.get(reverse('farm:equipment_list'), query).context['objects']]

    def test_listed_site_by_site_with_parts_under_their_equipment(self):
        self.assertEqual(self.rows(), [('AF', 0), ('AM', 1), ('GH', 0), ('BF', 0)])

    def test_search_and_filters(self):
        self.assertEqual(self.rows(q='sn-77'), [('AF', 0)])
        self.assertEqual(self.rows(site=self.tromso.pk), [('BF', 0)])
        self.assertEqual(self.rows(production_department=self.cages.pk), [('BF', 0)])
        self.assertEqual(self.rows(system=self.ras2.pk), [('AM', 1)])
        self.assertEqual(self.rows(system='none'), [('GH', 0)])
        self.assertEqual(self.rows(category='feeding'), [('BF', 0)])
        self.assertEqual(self.rows(type=self.heater.pk), [('GH', 0)])
        self.assertEqual(self.rows(status='repair'), [('AM', 1)])
        self.assertEqual(len(self.rows(site='x', system='y', category='z', status='w', type='v')), 4)

    def test_columns(self):
        response = self.client.get(reverse('farm:equipment_list'))
        self.assertContains(response, '1 part')
        self.assertContains(response, 'part of AF')
        self.assertContains(response, '<span class="badge badge-repair">Repair</span>', html=True)
        self.assertContains(response, '1 piece of equipment is not linked to any system.')

    def test_the_production_overview_counts_equipment(self):
        response = self.client.get(reverse('production_home'))
        self.assertIn({'key': 'equipment', 'label': 'Equipment', 'count': 4, 'url': reverse('farm:equipment_list')},
                      [{**tile, 'label': str(tile['label'])} for tile in response.context['tiles']])


class EquipmentAuditTests(EquipmentTestCase):
    def test_create_and_edit_are_logged_with_the_systems_and_the_specifications(self):
        self.post(equipment_data(self.pump, self.hall, [link(self.ras, role='main')], {'flowRate': '120', 'phase': 'three'}))
        pump = Equipment.objects.get()
        self.post(equipment_data(self.heater, self.hall, [link(self.ras, role='main', criticality=4)],
                                 {'heatingCapacity': '20', 'fuelType': 'gas'}, status='maintenance', version='1'), pump)
        created, edited = AuditLog.objects.order_by('created_at')
        self.assertEqual(created.changes['Type'], [None, message('Centrifugal pump')])
        self.assertEqual(created.changes['Status'], [None, message('Operational')])
        self.assertEqual(created.changes['Systems'], [None, 'RAS 1 (R1): primary, main, criticality 3'])
        self.assertEqual(created.changes['Flow rate'], [None, '120 m³/h'])
        self.assertEqual(created.changes['Phase'], [None, message('Three-phase')])
        self.assertEqual(edited.changes, {
            'Type': [message('Centrifugal pump'), message('Heater')],
            'Status': [message('Operational'), message('Maintenance')],
            'Systems': ['RAS 1 (R1): primary, main, criticality 3', 'RAS 1 (R1): primary, main, criticality 4'],
            'Heating capacity': [None, '20 kW'], 'Fuel type': [None, message('Gas')],
            'Flow rate': ['120 m³/h', None], 'Phase': [message('Three-phase'), None],
        })

    def test_the_log_is_english_whatever_the_language(self):
        Profile.objects.create(user=self.user, language='tr')
        self.post(equipment_data(self.pump, self.hall, [link(self.ras)], {'flowRate': '1', 'phase': 'single'}))
        entry = AuditLog.objects.get()
        self.assertEqual(entry.entity_type, 'equipment')
        self.assertEqual(entry.changes['Phase'], [None, message('Single-phase')])
        self.assertIn('Production department', entry.changes)


class EquipmentPermissionTests(EquipmentTestCase):
    def test_a_read_only_role_sees_equipment_but_cannot_change_it(self):
        viewer = get_user_model().objects.create_user('ola', 'ola@example.com', 'x')
        viewer.groups.add(role('Viewer', 'view_equipment'))
        self.client.force_login(viewer)
        feeder = self.make(kind=self.feeder, specifications={'capacity': 1, 'siloVolume': 1})
        response = self.client.get(reverse('farm:equipment_list'))
        self.assertContains(response, 'Pump')
        self.assertNotContains(response, reverse('farm:equipment_edit', args=[feeder.pk]))
        self.assertNotContains(response, reverse('farm:equipment_create'))
        for url in (reverse('farm:equipment_create'), reverse('farm:equipment_edit', args=[feeder.pk]),
                    reverse('farm:equipment_delete', args=[feeder.pk]),
                    reverse('farm:equipment_calibrations', args=[feeder.pk])):
            self.assertEqual(self.client.post(url, equipment_data(self.pump, self.hall)).status_code, 403, url)
        self.assertFalse(Equipment.objects.get().is_deleted)

    def test_no_view_permission_no_tab_and_no_menu_entry(self):
        stranger = get_user_model().objects.create_user('per', 'per@example.com', 'x')
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(reverse('farm:equipment_list')).status_code, 403)
        self.assertNotContains(self.client.get(reverse('production_home')), reverse('farm:equipment_list'))

    def test_the_menu_and_the_matrix_place_it_under_facility_structure(self):
        response = self.client.get(reverse('farm:equipment_list'))
        self.assertContains(response, f'href="{reverse("farm:equipment_list")}"')
        self.assertEqual(str(response.context['group']), 'Facility structure')


class EquipmentTypeAdminTests(TestCase):
    def test_the_catalogue_is_shown_and_cannot_be_changed(self):
        root = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(root)
        self.assertIn(EquipmentType, admin.site._registry)
        page = self.client.get(reverse('admin:farm_equipmenttype_changelist'))
        self.assertContains(page, 'Centrifugal pump')
        self.assertNotContains(page, reverse('admin:farm_equipmenttype_add'))
        kind = EquipmentType.objects.get(code='heater')
        self.assertEqual(self.client.post(reverse('admin:farm_equipmenttype_change', args=[kind.pk]),
                                          {'name': 'X'}).status_code, 403)

    def test_deleted_equipment_is_shown_in_the_admin_to_be_restored(self):
        root = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(root)
        site = Site.objects.create(name='Bergen', code='BG')
        pump = Equipment.objects.create(
            name='Pump', code='P1', equipment_type=EquipmentType.objects.get(code='pump-centrifugal'),
            production_department=ProductionDepartment.objects.create(site=site, name='Hall', code='HA'),
            specifications={'flowRate': 10})
        pump.soft_delete(root)
        self.assertContains(self.client.get(reverse('admin:farm_equipment_changelist')), 'Pump')
        self.assertEqual(self.client.get(reverse('admin:farm_equipment_change', args=[pump.pk])).status_code, 200)
        response = self.client.post(reverse('admin:farm_equipment_changelist'),
                                    {'action': 'restore', '_selected_action': [str(pump.pk)]}, follow=True)
        self.assertContains(response, '1 record restored.')
        self.assertTrue(Equipment.objects.filter(pk=pump.pk).exists())
