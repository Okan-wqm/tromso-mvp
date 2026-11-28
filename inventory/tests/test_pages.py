"""The store through its pages, every form and every kind of operation: create, read, void (or edit and
delete) and the rows stored; the storage location tab with every field clearable and its reorder levels; the
overview's warnings; permissions; the delete plan; the activity log; the menu, the role matrix, the database
viewer and the three languages."""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.management import call_command
from django.urls import reverse

from core import access, navigation
from core.models import AuditLog, Profile
from farm.models import Equipment, EquipmentType, ProductionDepartment, Supplier
from farm.tests.helpers import role, rows_data

from .. import read, services
from ..models import (
    InventoryItem, InventoryLot, InventoryOperation, ReorderLevel, StorageLocation,
)
from .helpers import D, StoreTestCase, departure_data, location_data, receipt_data, receipt_row
from core.testing import delete_confirmed

MODAL = {'X-Modal': '1'}


def setUpModule():
    call_command('compile_catalogs', verbosity=0)     # the language test reads the built catalogs


class DialogTests(StoreTestCase):
    def test_a_delivery_through_its_dialog_is_stored_shown_and_voided(self):
        url = reverse('inventory:receive')
        form = self.client.get(url, headers=MODAL)
        self.assertContains(form, 'Receive delivery')
        self.assertNotContains(form, 'Vet AS')                     # only suppliers of what the store keeps
        response = self.client.post(url, receipt_data(self, [
            receipt_row(self, quantity='1000', unit_cost='12.5', currency='nok'),
            receipt_row(self, lot_number='', expiry_date='', location=str(self.silo.pk), quantity='250.5')],
            reference='DN-4711', notes='Two pallets wet'), headers=MODAL)
        self.assertEqual(response.status_code, 204)
        delivery = InventoryOperation.objects.get()
        self.assertEqual((delivery.kind, delivery.supplier, delivery.reference, delivery.notes, delivery.date),
                         ('receipt', self.mill, 'DN-4711', 'Two pallets wet', self.day(2)))
        self.assertEqual(sorted(delivery.lines.values_list('location__code', 'lot__number', 'quantity', 'unit_cost',
                                                           'currency')),
                         [('SI-1', '', D('250.5'), None, ''), ('WH-1', 'L1', D(1000), D('12.5'), 'NOK')])
        page = self.client.get(f'{reverse("inventory:storage")}?tab=movements')
        self.assertContains(page, 'DN-4711')
        self.assertContains(page, '+1,000 kg')
        stock = self.client.get(f'{reverse("inventory:storage")}?tab=stock')
        self.assertContains(stock, '12,500.00 NOK')                 # value: 1000 kg × 12.5
        self.assertContains(stock, 'No lot number')
        # Void through its dialog.
        void_url = reverse('inventory:void', args=[delivery.pk])
        self.assertContains(self.client.get(void_url, headers=MODAL), 'Void the delivery of')
        self.assertEqual(self.client.post(void_url, {'reason': ''}, headers=MODAL).status_code, 422)
        self.assertEqual(self.client.post(void_url, {'reason': 'Typed twice'}, headers=MODAL).status_code, 204)
        delivery.refresh_from_db()
        self.assertEqual((delivery.is_deleted, delivery.void_reason), (True, 'Typed twice'))
        self.assertFalse(InventoryLot.objects.exists())
        self.assertContains(self.client.get(f'{reverse("inventory:storage")}?tab=movements&voided=1'), 'Typed twice')

    def test_a_delivery_needs_a_line_and_a_cost_with_its_currency(self):
        url = reverse('inventory:receive')
        response = self.client.post(url, receipt_data(self, [receipt_row(self, unit_cost='3')]), headers=MODAL)
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'A unit cost needs its currency', status_code=422)
        response = self.client.post(url, receipt_data(self, [receipt_row(self, quantity='0')]), headers=MODAL)
        self.assertEqual(response.status_code, 422)
        response = self.client.post(url, receipt_data(self, [receipt_row(self)], supplier=str(self.vet.pk)),
                                    headers=MODAL)
        self.assertEqual(response.status_code, 422)
        self.assertFalse(InventoryOperation.objects.exists())

    def departure(self, name, **fields):
        self.receive('500')
        lot = self.lot()
        url = f'{reverse(f"inventory:{name}")}?location={self.store.pk}&lot={lot.pk}'
        form = self.client.get(url, headers=MODAL)
        self.assertEqual(form.context['form'].initial['source'], f'{self.store.pk}:{lot.pk}')
        response = self.client.post(url, departure_data(self, self.store, lot, quantity='120.25', notes='Shelf 3',
                                                        **fields), headers=MODAL)
        self.assertEqual(response.status_code, 204, getattr(response, 'context', None) and response.context['form'].errors)
        operation = InventoryOperation.objects.exclude(kind='receipt').get()
        self.assertEqual((operation.date, operation.notes), (self.day(1), 'Shelf 3'))
        self.assertEqual(self.on_hand(self.store), D('379.75'))
        movements = self.client.get(f'{reverse("inventory:storage")}?tab=movements')
        self.assertContains(movements, '−120.25 kg')
        void_url = reverse('inventory:void', args=[operation.pk])
        self.assertEqual(self.client.post(void_url, {'reason': 'Wrong lot'}, headers=MODAL).status_code, 204)
        self.assertEqual(self.on_hand(self.store), 500)
        return operation

    def test_an_issue(self):
        operation = self.departure('issue', reason='samples')
        self.assertEqual((operation.kind, operation.reason), ('issue', 'samples'))
        self.assertEqual(list(operation.lines.values_list('kind', 'quantity')), [('out', D('-120.25'))])

    def test_a_write_off(self):
        operation = self.departure('write_off', reason='damaged')
        self.assertEqual((operation.kind, operation.reason), ('write_off', 'damaged'))

    def test_a_return_to_the_supplier_takes_stock_out(self):
        operation = self.departure('return', supplier=str(self.mill.pk), reference='RN-9')
        self.assertEqual((operation.kind, operation.supplier, operation.reference), ('return', self.mill, 'RN-9'))

    def test_a_transfer(self):
        operation = self.departure('transfer', destination=str(self.far.pk))
        self.assertEqual(sorted(operation.lines.values_list('location__code', 'quantity')),
                         [('TR-1', D('120.25')), ('WH-1', D('-120.25'))])

    def test_the_return_dialog_proposes_who_delivered_the_lot(self):
        self.receive('10')
        form = self.client.get(f'{reverse("inventory:return")}?location={self.store.pk}&lot={self.lot().pk}')
        self.assertEqual(form.context['form'].initial['supplier'], self.mill.pk)

    def test_other_and_the_server_reasons_on_their_fields(self):
        self.receive('100')
        lot = self.lot()
        url = reverse('inventory:write_off')
        response = self.client.post(url, departure_data(self, self.store, lot, quantity='200', reason='spilled'))
        self.assertEqual(response.status_code, 422)
        self.assertIn('Only 100 kg', response.context['form'].errors['quantity'][0])
        response = self.client.post(url, departure_data(self, self.store, lot, reason='other'))
        self.assertEqual(response.context['form'].errors['notes'], ['Say what it was: the reason is “other”.'])
        response = self.client.post(url, departure_data(self, self.store, lot, reason='spilled', date='2001-01-01'))
        self.assertIn('days back', response.context['form'].errors['date'][0])
        self.assertEqual(InventoryOperation.objects.count(), 1)

    def test_a_form_sent_twice_records_once(self):
        data = receipt_data(self, [receipt_row(self)])
        self.client.post(reverse('inventory:receive'), data, headers=MODAL)
        self.client.post(reverse('inventory:receive'), data, headers=MODAL)
        self.assertEqual(InventoryOperation.objects.count(), 1)

    def test_a_count_through_its_dialog(self):
        self.receive('100', number='L1')
        self.receive('40', number='L2', expiry_in=20)
        url = reverse('inventory:count')
        first = self.client.get(f'{url}?location={self.store.pk}', headers=MODAL)
        self.assertEqual([str(lot) for _form, lot, _book in first.context['pairs']], ['L2', 'L1'])  # expiring first
        # Changing the day renders the book of that day again (a draft), nothing saved.
        draft = self.client.post(url, {'_draft': 'date', 'location': str(self.store.pk), 'date': self.day(20).isoformat(),
                                       **rows_data('found', [])}, headers=MODAL)
        self.assertEqual(draft.context['pairs'], [])
        self.assertFalse(InventoryOperation.objects.filter(kind='count').exists())
        lots = [lot for _form, lot, _book in first.context['pairs']]
        data = {'token': str(uuid.uuid4()), 'location': str(self.store.pk), 'date': self.day(1).isoformat(),
                'notes': 'Monthly count',
                **rows_data('lots', [{'lot': str(lots[0].pk), 'quantity': '35'}, {'lot': str(lots[1].pk), 'quantity': ''}],
                            initial=2),
                **rows_data('found', [{'feed': str(self.feed.pk), 'lot_number': 'F-1', 'expiry_date': '',
                                       'quantity': '7.5'}])}
        response = self.client.post(url, data, headers=MODAL)
        self.assertEqual(response.status_code, 422)                 # every listed lot must be filled in
        data['lots-1-quantity'] = '100'
        self.assertEqual(self.client.post(url, data, headers=MODAL).status_code, 204)
        count = InventoryOperation.objects.get(kind='count')
        self.assertEqual((count.location, count.notes), (self.store, 'Monthly count'))
        self.assertEqual(sorted(count.lines.values_list('lot__number', 'quantity')),
                         [('F-1', D('7.5')), ('L1', D(100)), ('L2', D(35))])
        page = self.client.get(f'{reverse("inventory:storage")}?tab=counts')
        self.assertContains(page, '−5 kg')                          # L2: 40 in the book, 35 counted
        self.assertContains(page, '+7.5 kg')
        self.assertEqual(self.client.post(reverse('inventory:void', args=[count.pk]), {'reason': 'Recount'},
                                          headers=MODAL).status_code, 204)
        self.assertEqual(self.on_hand(self.store, 'L2'), 40)
        self.assertStoreAddsUp()

    def test_a_count_day_it_cannot_read_is_said_and_never_replaced_by_today(self):
        """A typo in the count's day on a reload (a draft) is said back and kept in the box; the book shown is no day's,
        never today's in its place."""
        self.receive('100', number='L1')
        url = reverse('inventory:count')
        draft = self.client.post(url, {'_draft': 'date', 'location': str(self.store.pk), 'date': '31.13.2026',
                                       **rows_data('found', [])}, headers=MODAL)
        self.assertEqual(draft.status_code, 200)
        self.assertEqual(draft.context['pairs'], [])
        self.assertEqual(draft.context['form'].initial['date'], '31.13.2026')
        said = [str(message) for message in get_messages(draft.wsgi_request)]
        self.assertTrue(any(text.startswith('“31.13.2026” is not a date this page reads') for text in said), said)

    def test_the_item_and_lot_pages(self):
        self.receive('100', cost='2', currency='EUR')
        services.transfer(self.user, source=self.store, lot=self.lot(), destination=self.far, day=self.day(1),
                          quantity=D(30))
        item = InventoryItem.objects.get()
        page = self.client.get(f'{reverse("inventory:item", args=[item.pk])}?site={self.bergen.pk}')
        self.assertEqual([(day.day, day.arrived, day.left, day.closing) for day in page.context['days']],
                         [(self.day(1), 0, 30, 70), (self.day(10), 100, 0, 100)])
        self.assertContains(page, 'Tromso')                          # its other site, a tab
        lot_page = self.client.get(reverse('inventory:lot', args=[self.lot().pk]))
        self.assertContains(lot_page, 'Feed mill AS')
        self.assertContains(lot_page, 'TR-1')


class OverviewTests(StoreTestCase):
    def test_low_stock_over_capacity_expiring_and_expired(self):
        self.store.capacity, self.store.capacity_unit = D(500), 'kg'
        self.store.save()
        self.receive('450', number='SOON', expiry_in=10)
        self.receive('100', number='OLD', expiry_in=60)
        services.write_off(self.user, location=self.store, lot=self.lot('OLD'), day=self.day(1), quantity=D(40),
                           reason='spilled')
        ReorderLevel.objects.create(location=self.store, item=InventoryItem.objects.get(), level=D(600))
        summary = read.overview()
        self.assertEqual([(location.code, held, level) for location, _item, held, level in summary.low],
                         [('WH-1', D(510), D(600))])
        self.assertEqual([(location.code, held) for location, held, _capacity in summary.over], [('WH-1', D(510))])
        self.assertEqual([str(row.lot) for row in summary.expiring], ['SOON'])
        page = self.client.get(reverse('inventory:storage'))
        self.assertContains(page, 'below the reorder level of 600 kg')
        self.assertContains(page, 'above its capacity of 500 kg')
        self.assertContains(page, 'Expiring within 30 days')

    def test_an_empty_store_says_so(self):
        self.assertContains(self.client.get(reverse('inventory:storage')), 'Nothing in the store yet')
        for tab in ('stock', 'movements', 'counts'):
            self.assertEqual(self.client.get(f'{reverse("inventory:storage")}?tab={tab}').status_code, 200)


class LocationTabTests(StoreTestCase):
    def feeder(self, department=None, code='FD-1'):
        return Equipment.objects.create(name=f'Feeder {code}', code=code, production_department=department or self.hall,
                                        equipment_type=EquipmentType.objects.get(code='feeder-automatic'))

    def test_create_read_edit_clear_and_delete_a_location(self):
        feeder = self.feeder()
        response = self.client.post(reverse('inventory:storagelocation_create'), location_data(
            self.bergen, name='Silo 2', code='si-02', kind='silo', feeder=str(feeder.pk), capacity='25000',
            capacity_unit='kg', notes='Outside hall A'), headers=MODAL)
        self.assertEqual(response.status_code, 204)
        silo = StorageLocation.objects.get(code='SI-02')
        self.assertEqual((silo.site, silo.kind, silo.feeder, silo.capacity, silo.capacity_unit, silo.notes),
                         (self.bergen, 'silo', feeder, D(25000), 'kg', 'Outside hall A'))
        listing = self.client.get(reverse('inventory:storagelocation_list'), {'site': self.bergen.pk, 'kind': 'silo'})
        self.assertContains(listing, 'Silo 2')
        self.assertNotContains(listing, 'Feed store')
        # Edit: every optional field cleared; the site stays where it was created.
        response = self.client.post(reverse('inventory:storagelocation_edit', args=[silo.pk]), location_data(
            self.tromso, name='Silo two', code='SI-02', kind='silo', version='1'), headers=MODAL)
        self.assertEqual(response.status_code, 204)
        silo.refresh_from_db()
        self.assertEqual((silo.name, silo.site, silo.feeder, silo.capacity, silo.capacity_unit, silo.notes),
                         ('Silo two', self.bergen, None, None, '', ''))
        log = AuditLog.objects.filter(entity_type='storage location', entity_id=str(silo.pk)).order_by('created_at')
        self.assertEqual([entry.action for entry in log], ['create', 'update'])
        self.assertEqual(log[1].changes['Feeder'], ['Feeder FD-1 (FD-1)', None])
        # Delete.
        self.assertEqual(delete_confirmed(self.client, reverse('inventory:storagelocation_delete', args=[silo.pk]),
                                          headers=MODAL).status_code, 204)
        self.assertTrue(StorageLocation.all_objects.get(pk=silo.pk).is_deleted)

    def test_the_rules_of_the_form(self):
        other_site = ProductionDepartment.objects.create(site=self.tromso, name='Sea', code='SE')
        far_feeder = self.feeder(other_site, 'FD-9')
        url = reverse('inventory:storagelocation_create')
        cases = [
            (location_data(self.bergen, kind='warehouse', feeder=str(self.feeder().pk)), 'feeder'),
            (location_data(self.bergen, kind='silo', feeder=str(far_feeder.pk)), 'feeder'),
            (location_data(self.bergen, capacity='100'), 'capacity_unit'),
            (location_data(self.bergen, code='WH-1'), 'code'),
            (location_data(self.bergen, name='feed STORE'), 'name'),
        ]
        for data, field in cases:
            with self.subTest(field=field, data=data):
                response = self.client.post(url, data)
                self.assertIn(field, response.context['form'].errors)
        self.assertEqual(StorageLocation.objects.count(), 3)

    def test_a_location_holding_stock_cannot_be_deleted_and_neither_can_its_site(self):
        self.receive('10')
        confirm = self.client.get(reverse('inventory:storagelocation_delete', args=[self.store.pk]))
        self.assertContains(confirm, 'It holds stock')
        delete_confirmed(self.client, reverse('inventory:storagelocation_delete', args=[self.store.pk]))
        self.assertFalse(StorageLocation.all_objects.get(pk=self.store.pk).is_deleted)
        admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(admin)
        self.assertContains(self.client.get(reverse('farm:site_delete', args=[self.bergen.pk])), 'It holds stock')
        # The empty location of the other site goes with it.
        delete_confirmed(self.client, reverse('farm:site_delete', args=[self.tromso.pk]))
        self.assertTrue(StorageLocation.all_objects.get(pk=self.far.pk).is_deleted)

    def test_deleting_the_feeder_leaves_the_silo_without_one(self):
        feeder = self.feeder()
        self.silo.feeder = feeder
        self.silo.save()
        admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(admin)
        delete_confirmed(self.client, reverse('farm:equipment_delete', args=[feeder.pk]))
        self.silo.refresh_from_db()
        self.assertIsNone(self.silo.feeder)

    def test_a_supplier_and_a_feed_with_deliveries_stay(self):
        self.receive('10')
        admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(admin)
        delete_confirmed(self.client, reverse('farm:supplier_delete', args=[self.mill.pk]))
        self.assertFalse(Supplier.all_objects.get(pk=self.mill.pk).is_deleted)
        delete_confirmed(self.client, reverse('farm:feed_delete', args=[self.feed.pk]))
        self.feed.refresh_from_db()
        self.assertFalse(self.feed.is_deleted)

    def test_reorder_levels_are_saved_as_a_list(self):
        url = reverse('inventory:storagelocation_reorder', args=[self.store.pk])
        response = self.client.post(url, rows_data('reorder', [{'feed': str(self.feed.pk), 'level': '2000'}],
                                                   record=self.store),
                                    headers=MODAL)
        self.assertEqual(response.status_code, 204)
        level = ReorderLevel.objects.get()
        self.assertEqual((level.location, level.item.feed, level.level), (self.store, self.feed, D(2000)))
        edit = self.client.get(reverse('inventory:storagelocation_edit', args=[self.store.pk]))
        self.assertEqual(edit.context['reorder'].forms[0]['feed'].value(), self.feed.pk)
        twice = self.client.post(url, rows_data('reorder', [{'feed': str(self.feed.pk), 'level': '1'},
                                                            {'feed': str(self.feed.pk), 'level': '2'}],
                                                 record=self.store))
        self.assertEqual(twice.status_code, 200)
        self.assertContains(twice, 'One reorder level per feed.')
        self.client.post(url, rows_data('reorder', [], initial=0, record=self.store))
        self.assertFalse(ReorderLevel.objects.exists())
        changes = [entry.changes for entry in AuditLog.objects.filter(entity_type='storage location',
                                                                      entity_id=str(self.store.pk))]
        self.assertIn({'Reorder levels': [None, 'Grower 4 (GR-4): 2000 kg']}, changes)


class AccessTests(StoreTestCase):
    def test_the_menu_the_role_matrix_and_the_permissions(self):
        self.assertEqual(navigation.place('inventory.view_inventoryoperation').path, 'Production · Operations')
        self.assertEqual(str(navigation.place('inventory.view_storagelocation').path), 'Company · Facility')
        offered = {(area.model, action) for area in access.areas() for action in area.actions}
        self.assertTrue({('inventory.InventoryOperation', 'view'), ('inventory.InventoryOperation', 'add'),
                         ('inventory.InventoryOperation', 'delete')} <= offered)
        self.assertNotIn(('inventory.InventoryOperation', 'change'), offered)
        reader = get_user_model().objects.create_user('ola', 'ola@example.com', 'x')
        reader.groups.add(role('Reader', 'view_inventoryoperation'))
        self.client.force_login(reader)
        self.receive('10')
        page = self.client.get(reverse('inventory:storage'))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, reverse('inventory:receive'))
        for url in (reverse('inventory:receive'), reverse('inventory:issue'), reverse('inventory:count'),
                    reverse('inventory:void', args=[InventoryOperation.objects.get().pk]),
                    reverse('inventory:storagelocation_list')):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        nobody = get_user_model().objects.create_user('per', 'per@example.com', 'x')
        self.client.force_login(nobody)
        self.assertEqual(self.client.get(reverse('inventory:storage')).status_code, 403)

    def test_the_activity_log_names_what_was_done(self):
        self.receive('100', reference='DN-1')
        delivery = InventoryOperation.objects.get()
        entry = AuditLog.objects.get(entity_type='inventory operation', action='create')
        self.assertEqual(entry.entity_label, f'Delivery · WH-1 · GR-4 L1 · {self.day(10).isoformat()}')
        self.assertIn('WH-1 · Grower 4 (GR-4) · lot L1', entry.changes['Lines'][1])
        services.void(self.user, delivery, 'Wrong supplier')
        void = AuditLog.objects.get(entity_type='inventory operation', action='void')
        self.assertEqual(void.changes, {'Reason for voiding': [None, 'Wrong supplier']})
        self.assertTrue(AuditLog.objects.filter(entity_type='lot', action='delete').exists())

    def test_the_database_viewer_lists_the_store(self):
        admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(admin)
        page = self.client.get(reverse('core:database'))
        for table in ('storage_locations', 'inventory_items', 'inventory_lots', 'inventory_operations',
                      'inventory_lines', 'inventory_reorder_levels'):
            self.assertContains(page, table)


class LanguageTests(StoreTestCase):
    def test_every_page_and_dialog_renders_in_each_language(self):
        self.receive('100', cost='1', currency='NOK')
        services.count(self.user, location=self.store, day=self.day(1), lines=[(self.lot(), D(90))])
        item, lot = InventoryItem.objects.get(), self.lot()
        storage = reverse('inventory:storage')
        urls = [storage, *(f'{storage}?tab={tab}' for tab in ('stock', 'movements', 'counts')),
                f'{storage}?tab=movements&kind=feeding', reverse('inventory:receive'), reverse('inventory:issue'),
                f'{reverse("inventory:write_off")}?location={self.store.pk}&lot={lot.pk}', reverse('inventory:return'),
                reverse('inventory:transfer'), f'{reverse("inventory:count")}?location={self.store.pk}',
                reverse('inventory:void', args=[InventoryOperation.objects.first().pk]),
                reverse('inventory:item', args=[item.pk]), reverse('inventory:lot', args=[lot.pk]),
                reverse('inventory:storagelocation_list'), reverse('inventory:storagelocation_create'),
                reverse('inventory:storagelocation_edit', args=[self.store.pk]),
                reverse('inventory:storagelocation_delete', args=[self.store.pk])]
        for language in ('en', 'tr', 'nb'):
            Profile.objects.update_or_create(user=self.user, defaults={'language': language})
            for url in urls:
                for headers in ({}, MODAL):
                    with self.subTest(language=language, url=url, modal=bool(headers)):
                        response = self.client.get(url, headers=headers)
                        self.assertEqual(response.status_code, 200)
                        self.assertNotIn('%(', response.content.decode())
        Profile.objects.update_or_create(user=self.user, defaults={'language': 'nb'})
        self.assertContains(self.client.get(storage), 'Lager')
