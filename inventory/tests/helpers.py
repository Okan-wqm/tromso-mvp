"""What the store's tests share: two sites with storage locations, a feed and its mill, a keeper's role, and
the forms' data as the pages post them."""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from farm.models import Feed, ProductionDepartment, Site, Supplier
from farm.stock.dates import site_today
from farm.tests.helpers import role, rows_data

from .. import integrity, read, services
from ..models import InventoryItem, StorageLocation

STORE_KEEPER = ('view_inventoryoperation', 'add_inventoryoperation', 'delete_inventoryoperation',
                'view_storagelocation', 'add_storagelocation', 'change_storagelocation', 'delete_storagelocation',
                'view_auditlog')
D = Decimal


def location_data(site, **overrides):
    data = {'site': str(site.pk), 'name': 'Feed store 1', 'code': 'fs-01', 'kind': 'warehouse', 'status': 'active',
            'feeder': '', 'capacity': '', 'capacity_unit': '', 'notes': ''}
    data.update(overrides)
    return data


class StoreFixtures:
    """Two sites, three locations, a feed, its mill and a vet; a keeper signed in."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('kari', 'kari@example.com', 'eski-sifre-123')
        self.user.groups.add(role('Store keeper', *STORE_KEEPER))
        self.client.force_login(self.user)
        self.bergen = Site.objects.create(name='Bergen', code='BG')
        self.tromso = Site.objects.create(name='Tromso', code='TR')
        self.hall = ProductionDepartment.objects.create(site=self.bergen, name='Hall A', code='HA')
        self.mill = Supplier.objects.create(name='Feed mill AS', code='FM', supplies=['feed', 'transport'])
        self.vet = Supplier.objects.create(name='Vet AS', code='VET', supplies=['medicines'])
        self.feed = Feed.objects.create(name='Grower 4', code='GR-4', feed_type='grower', pellet_size_mm=D(4))
        self.store = StorageLocation.objects.create(site=self.bergen, name='Feed store', code='WH-1', kind='warehouse')
        self.silo = StorageLocation.objects.create(site=self.bergen, name='Silo 1', code='SI-1', kind='silo')
        self.far = StorageLocation.objects.create(site=self.tromso, name='Tromso store', code='TR-1', kind='warehouse')
        self.today = site_today(self.bergen)

    def day(self, days_ago):
        return self.today - timedelta(days=days_ago)

    def receive(self, quantity, days_ago=10, number='L1', expiry_in=60, location=None, cost=None, currency='',
                feed=None, supplier=None, **fields):
        expiry = None if expiry_in is None else self.today + timedelta(days=expiry_in)
        return services.receive(self.user, supplier=supplier or self.mill, day=self.day(days_ago), lines=[
            (feed or self.feed, number, expiry, location or self.store, D(quantity),
             None if cost is None else D(cost), currency)], **fields)

    def lot(self, number='L1'):
        return InventoryItem.objects.get(feed=self.feed).lots.get(number=number)

    def on_hand(self, location, number='L1', day=None):
        item = InventoryItem.objects.get(feed=self.feed)
        fold = read.folds([item])[item.pk]
        return fold.balance((location.pk, self.lot(number).pk), day or self.today)

    def refused(self, call, *args, **kwargs):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError) as caught:
            call(*args, **kwargs)
        return caught.exception.message_dict

    def assertStoreAddsUp(self):
        self.assertEqual(integrity.problems(), [])


class StoreTestCase(StoreFixtures, TestCase):
    pass


def receipt_data(test, rows, **fields):
    data = {'token': str(uuid.uuid4()), 'supplier': str(test.mill.pk), 'date': test.day(2).isoformat(),
            'reference': '', 'notes': '', **fields}
    data.update(rows_data('lines', rows))
    return data


def receipt_row(test, **fields):
    return {'feed': str(test.feed.pk), 'lot_number': 'L1', 'expiry_date': (test.today + timedelta(days=60)).isoformat(),
            'location': str(test.store.pk), 'quantity': '1000', 'unit_cost': '', 'currency': '', **fields}


def departure_data(test, location, lot, **fields):
    return {'token': str(uuid.uuid4()), 'source': f'{location.pk}:{lot.pk}', 'date': test.day(1).isoformat(),
            'quantity': '10', 'notes': '', **fields}
