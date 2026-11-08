"""One order for every lock a write takes on the farm's structure (cross review of the merge, finding 1): the fish first
(batches, then units), then the place going up (production departments, then sites). Two writes that both follow it wait
for each other and never deadlock. Checked with two real transactions on two connections."""
import threading
import time as clock

from django.contrib.auth import get_user_model
from django.db import connections, transaction
from django.test import Client, TransactionTestCase
from django.urls import reverse

from ..models import ProductionDepartment, Site, Tank
from .test_stock import make_unit


class LockOrderTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.site = Site.objects.create(name='Bergen', code='BG')
        self.hall = ProductionDepartment.objects.create(site=self.site, name='Hall B', code='HB')
        self.unit = make_unit('T-50', self.hall)

    def run_together(self, *jobs):
        results = []

        def run(name, job):
            try:
                job()
                results.append((name, 'ok'))
            except Exception as error:      # noqa: BLE001 - the outcome is what the test is about
                results.append((name, f'{type(error).__name__}: {str(error)[:100]}'))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=run, args=job) for job in jobs]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        return sorted(results)

    def test_a_department_deleted_while_one_of_its_units_is_saved_waits_and_never_deadlocks(self):
        held = threading.Event()

        def save_the_unit():
            with transaction.atomic():
                unit = Tank.all_objects.select_for_update(of=('self',)).get(pk=self.unit.pk)   # as an edit locks it
                held.set()
                clock.sleep(1)                                     # the delete reaches its locks meanwhile
                unit.notes = 'edited'
                unit.save()                                        # its site and department locked by the save

        def delete_the_department():
            held.wait(10)
            client = Client(raise_request_exception=True)
            client.force_login(self.user)
            response = client.post(reverse('farm:productiondepartment_delete', args=[self.hall.pk]))
            assert response.status_code in (200, 302), response.status_code

        self.assertEqual(self.run_together(('save', save_the_unit), ('delete', delete_the_department)),
                         [('delete', 'ok'), ('save', 'ok')])
        self.assertTrue(ProductionDepartment.all_objects.get(pk=self.hall.pk).is_deleted)
        self.assertEqual(Tank.all_objects.get(pk=self.unit.pk).notes, 'edited')
