from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from core.audit import message
from core.models import AuditLog

from ..models import ProductionDepartment, Site, System
from .helpers import role

SYSTEM_MANAGER = (
    'view_system', 'add_system', 'change_system', 'delete_system', 'view_site', 'delete_site',
    'view_productiondepartment', 'delete_productiondepartment', 'view_auditlog',
)


def system_data(site=None, **overrides):
    data = {'name': 'Smolt RAS 1', 'code': 'sys-1', 'type': 'ras', 'status': 'operational',
            'site': str(site.pk) if site else '', 'production_department': '', 'parent': '', 'description': '',
            'total_volume_m3': '', 'max_biomass_kg': ''}
    data.update(overrides)
    return data


class SystemTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'eski-sifre-123')
        self.user.groups.add(role('System manager', *SYSTEM_MANAGER))
        self.client.force_login(self.user)
        self.bergen = Site.objects.create(name='Bergen', code='BG')
        self.tromso = Site.objects.create(name='Tromso', code='TR')
        self.hall = ProductionDepartment.objects.create(site=self.bergen, name='Hall A', code='HA')
        self.cages = ProductionDepartment.objects.create(site=self.tromso, name='Cages', code='CG')

    def make(self, site=None, **fields):
        fields.setdefault('name', 'System A')
        fields.setdefault('code', 'SA')
        return System.objects.create(site=site or self.bergen, **fields)


class SystemRoundTripTests(SystemTestCase):
    def test_create_read_edit_delete(self):
        # Create
        self.client.post(reverse('farm:system_create'), system_data(
            self.bergen, production_department=str(self.hall.pk), description='Main loop', total_volume_m3='120.5',
            max_biomass_kg='9000'))
        system = System.objects.get()
        self.assertEqual(
            (system.name, system.code, system.type, system.status, system.site, system.production_department,
             system.parent, system.description, system.total_volume_m3, system.max_biomass_kg, system.created_by),
            ('Smolt RAS 1', 'SYS-1', 'ras', 'operational', self.bergen, self.hall, None, 'Main loop',
             Decimal('120.50'), Decimal('9000.00'), self.user),
        )
        # Read: listed, and the edit form is filled from the database
        self.assertEqual([s.pk for s in self.client.get(reverse('farm:system_list')).context['objects']], [system.pk])
        form = self.client.get(reverse('farm:system_edit', args=[system.pk])).context['form']
        self.assertEqual((form['description'].value(), form['production_department'].value()), ('Main loop', self.hall.pk))
        # Edit; the site is chosen once and cannot be moved
        self.client.post(reverse('farm:system_edit', args=[system.pk]), system_data(
            self.tromso, name='Smolt RAS 2', type='flow_through', status='maintenance',
            production_department=str(self.hall.pk), description='Main loop', total_volume_m3='130', max_biomass_kg='',
            version='1'))
        system.refresh_from_db()
        self.assertEqual((system.name, system.type, system.status, system.site, system.total_volume_m3,
                          system.max_biomass_kg, system.version),
                         ('Smolt RAS 2', 'flow_through', 'maintenance', self.bergen, Decimal('130.00'), None, 2))
        # Delete
        self.client.post(reverse('farm:system_delete', args=[system.pk]))
        self.assertFalse(System.objects.exists())
        self.assertTrue(System.all_objects.get().is_deleted)

    def test_links_and_text_can_be_cleared_when_editing(self):
        parent = self.make(name='Parent', code='PA')
        system = self.make(name='Child', code='CH', production_department=self.hall, parent=parent, description='Note')
        self.client.post(reverse('farm:system_edit', args=[system.pk]),
                         system_data(self.bergen, name='Child', code='CH', version='1'))
        system.refresh_from_db()
        self.assertEqual((system.production_department, system.parent, system.description), (None, None, ''))


class SystemValidationTests(SystemTestCase):
    def errors(self, **data):
        return self.client.post(reverse('farm:system_create'), system_data(**data)).context['form'].errors

    def test_site_name_and_code_are_required(self):
        self.assertEqual(set(self.errors(name='', code='')), {'site', 'name', 'code'})

    def test_code_is_unique_within_a_site_only(self):
        self.make(code='SYS-1')
        self.assertEqual(self.errors(site=self.bergen, name='Other', code='sys-1')['code'],
                         ['This site already has a system with this code.'])
        self.client.post(reverse('farm:system_create'), system_data(self.tromso))
        self.assertTrue(System.objects.filter(site=self.tromso, code='SYS-1').exists())

    def test_a_deleted_system_frees_its_code(self):
        self.make(code='SYS-1').soft_delete(self.user)
        self.client.post(reverse('farm:system_create'), system_data(self.bergen))
        self.assertEqual(System.objects.count(), 1)

    def test_volume_and_biomass_cannot_be_negative(self):
        errors = self.errors(site=self.bergen, total_volume_m3='-1', max_biomass_kg='-5')
        self.assertEqual(set(errors), {'total_volume_m3', 'max_biomass_kg'})
        for field in ('total_volume_m3', 'max_biomass_kg'):
            with self.assertRaises(IntegrityError), transaction.atomic():
                self.make(**{field: -1})

    def test_the_department_must_be_on_the_systems_site(self):
        errors = self.errors(site=self.bergen, production_department=str(self.cages.pk))
        self.assertEqual(errors['production_department'], ['The production department belongs to another site.'])
        self.client.post(reverse('farm:system_create'), system_data(self.bergen, production_department=str(self.hall.pk)))
        self.assertEqual(System.objects.get().production_department, self.hall)

    def test_a_parent_system_must_be_on_the_same_site(self):
        elsewhere = self.make(site=self.tromso, name='Elsewhere', code='EL')
        errors = self.errors(site=self.bergen, parent=str(elsewhere.pk))
        self.assertEqual(errors['parent'], ['The parent system belongs to another site.'])

    def test_a_system_cannot_be_nested_under_itself_or_anything_below_it(self):
        top = self.make(name='Top', code='TOP')
        middle = self.make(name='Middle', code='MID', parent=top)
        bottom = self.make(name='Bottom', code='BOT', parent=middle)
        page = self.client.get(reverse('farm:system_edit', args=[top.pk]))
        offered = set(page.context['form'].fields['parent'].queryset)
        self.assertEqual(offered, set())          # everything else is below it
        page = self.client.get(reverse('farm:system_edit', args=[bottom.pk]))
        self.assertEqual(set(page.context['form'].fields['parent'].queryset), {top, middle})
        # Posting a choice the page did not offer is refused as well
        response = self.client.post(reverse('farm:system_edit', args=[top.pk]), system_data(
            self.bergen, name='Top', code='TOP', parent=str(bottom.pk), version='1'))
        self.assertIn('parent', response.context['form'].errors)
        top.refresh_from_db()
        self.assertIsNone(top.parent)

    def test_the_model_refuses_loops_however_it_is_reached(self):
        top = self.make(name='Top', code='TOP')
        child = self.make(name='Child', code='CH', parent=top)
        top.parent = child
        with self.assertRaisesMessage(ValidationError, 'nested under this system'):
            top.full_clean()
        top.parent = top
        with self.assertRaises(ValidationError):
            top.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            System.objects.filter(pk=top.pk).update(parent=top)

    def test_only_live_sites_and_departments_can_be_chosen(self):
        self.tromso.soft_delete(self.user)
        self.assertIn('site', self.errors(site=self.tromso))
        self.cages.soft_delete(self.user)
        self.assertIn('production_department', self.errors(site=self.bergen, production_department=str(self.cages.pk)))


class SystemFormTests(SystemTestCase):
    def test_department_and_parent_choices_know_their_site(self):
        parent = self.make(site=self.tromso, name='Tromso loop', code='TL')
        html = self.client.get(reverse('farm:system_create')).content.decode()
        self.assertEqual(html.count('data-depends-on="site"'), 2)
        self.assertIn(f'<option value="{self.hall.pk}" data-group="{self.bergen.pk}">', html)
        self.assertIn(f'<option value="{parent.pk}" data-group="{self.tromso.pk}">', html)

    def test_the_form_opens_in_the_dialog(self):
        response = self.client.get(reverse('farm:system_create'), headers={'X-Modal': '1'})
        self.assertContains(response, 'class="modal-head"')
        self.assertNotContains(response, 'id="rail"')


class SystemListTests(SystemTestCase):
    def setUp(self):
        super().setUp()
        self.top = self.make(name='Alpha RAS', code='AL', production_department=self.hall)
        self.child = self.make(name='Alpha tank loop', code='ALT', parent=self.top)
        self.grandchild = self.make(name='Alpha filter', code='ALF', parent=self.child)
        self.other = self.make(site=self.tromso, name='Beta pond', code='BP', production_department=self.cages)

    def rows(self, **query):
        response = self.client.get(reverse('farm:system_list'), query)
        return [(system.name, system.depth) for system in response.context['objects']]

    def test_systems_are_listed_site_by_site_with_nested_ones_under_their_parent(self):
        self.assertEqual(self.rows(), [('Alpha RAS', 0), ('Alpha tank loop', 1), ('Alpha filter', 2), ('Beta pond', 0)])

    def test_a_search_keeps_the_real_depth(self):
        self.assertEqual(self.rows(q='filter'), [('Alpha filter', 2)])

    def test_site_and_department_filters(self):
        self.assertEqual(self.rows(site=str(self.tromso.pk)), [('Beta pond', 0)])
        self.assertEqual(self.rows(production_department=str(self.hall.pk)), [('Alpha RAS', 0)])
        self.assertEqual(self.rows(production_department='none'), [('Alpha tank loop', 1), ('Alpha filter', 2)])
        self.assertEqual(len(self.rows(site='not-a-site', production_department='x')), 4)

    def test_systems_without_a_production_department_are_flagged(self):
        self.assertContains(self.client.get(reverse('farm:system_list')), '2 systems are not in any production department.')

    def test_the_empty_list_invites_to_add_one(self):
        System.objects.all().delete()
        self.assertContains(self.client.get(reverse('farm:system_list')), 'No systems yet')


class SystemDeleteTests(SystemTestCase):
    def setUp(self):
        super().setUp()
        self.top = self.make(name='Top', code='TOP', production_department=self.hall)
        self.child = self.make(name='Child', code='CH', parent=self.top)

    def log(self):
        return sorted(AuditLog.objects.values_list('action', 'entity_type', 'entity_label'))

    def test_deleting_a_system_deletes_the_systems_nested_under_it(self):
        self.assertContains(self.client.get(reverse('farm:system_delete', args=[self.top.pk])),
                            'Systems deleted with it')
        self.client.post(reverse('farm:system_delete', args=[self.top.pk]))
        self.assertFalse(System.objects.exists())
        self.assertEqual(self.log(), [('delete', 'system', 'Child (CH)'), ('delete', 'system', 'Top (TOP)')])

    def test_deleting_a_site_deletes_its_systems_and_its_production_departments(self):
        page = self.client.get(reverse('farm:site_delete', args=[self.bergen.pk]))
        self.assertContains(page, 'Systems deleted with it')
        self.assertContains(page, 'Production departments deleted with it')
        self.client.post(reverse('farm:site_delete', args=[self.bergen.pk]))
        self.assertFalse(System.objects.exists())
        self.hall.refresh_from_db()
        self.assertEqual((self.hall.site, self.hall.is_deleted), (self.bergen, True))
        self.assertEqual(self.log(), [
            ('delete', 'production department', 'Hall A (HA)'), ('delete', 'site', 'Bergen (BG)'),
            ('delete', 'system', 'Child (CH)'), ('delete', 'system', 'Top (TOP)'),
        ])

    def test_deleting_a_department_leaves_its_systems_in_place_without_a_production_department(self):
        page = self.client.get(reverse('farm:productiondepartment_delete', args=[self.hall.pk]))
        self.assertContains(page, 'Systems that lose their production department')
        self.client.post(reverse('farm:productiondepartment_delete', args=[self.hall.pk]))
        self.top.refresh_from_db()
        self.assertEqual((self.top.production_department, self.top.is_deleted, self.top.version), (None, False, 2))
        self.assertEqual(self.log(), [('delete', 'production department', 'Hall A (HA)'), ('update', 'system', 'Top (TOP)')])
        self.assertEqual(AuditLog.objects.get(entity_label='Top (TOP)').changes, {'Production department': ['Hall A (HA)', None]})


class SystemAuditAndPermissionTests(SystemTestCase):
    def test_changes_are_logged_with_old_and_new_values(self):
        self.client.post(reverse('farm:system_create'), system_data(self.bergen, production_department=str(self.hall.pk)))
        system = System.objects.get()
        self.client.post(reverse('farm:system_edit', args=[system.pk]), system_data(
            self.bergen, production_department='', status='offline', version='1'))
        created, edited = AuditLog.objects.filter(entity_type='system').order_by('created_at')
        self.assertEqual(created.changes['Production department'], [None, 'Hall A (HA)'])
        self.assertEqual(edited.changes, {'Status': [message('Operational'), message('Offline')], 'Production department': ['Hall A (HA)', None]})

    def test_a_read_only_role_sees_systems_but_cannot_change_them(self):
        viewer = get_user_model().objects.create_user('ola', 'ola@example.com', 'x')
        viewer.groups.add(role('Viewer', 'view_system'))
        self.client.force_login(viewer)
        system = self.make()
        response = self.client.get(reverse('farm:system_list'))
        self.assertContains(response, 'System A')
        self.assertNotContains(response, reverse('farm:system_edit', args=[system.pk]))
        for url in (reverse('farm:system_create'), reverse('farm:system_delete', args=[system.pk])):
            self.assertEqual(self.client.post(url, system_data(self.bergen)).status_code, 403)

    def test_no_view_permission_no_tab_and_no_menu_entry(self):
        stranger = get_user_model().objects.create_user('per', 'per@example.com', 'x')
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(reverse('farm:system_list')).status_code, 403)
        self.assertNotContains(self.client.get(reverse('home')), reverse('farm:system_list'))
