"""The data-layering audit, L-1: a credential's rotation (sensors.credentials.rotate) and a dead letter's resolution
(sensors.services.resolve_dead_letter) are written by their write paths, which ask who may themselves; a stale rotation
is refused there."""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from core.crud import Crossed
from farm.tests.helpers import role

from .. import credentials, services
from ..models import Credential, DeadLetter
from . import SensorsCase


class WritePathTests(SensorsCase):
    def setUp(self):
        self.stranger = get_user_model().objects.create_user('stranger', 'stranger@example.com', 'x')
        self.keeper = get_user_model().objects.create_user('keeper', 'keeper@example.com', 'x')
        self.keeper.groups.add(role('Sensor keeper', 'change_credential', 'change_deadletter'))

    def test_a_rotation_asks_who_may_and_refuses_a_stale_version(self):
        credential = Credential.objects.create(username='gateway-l1')
        with self.assertRaises(PermissionDenied):
            credentials.rotate(self.stranger, credential.pk, credential.version)
        with self.assertRaises(Crossed):
            credentials.rotate(self.keeper, credential.pk, credential.version + 1)
        self.assertEqual(Credential.objects.get(pk=credential.pk).password_hash, credential.password_hash)
        rotated, secret = credentials.rotate(self.keeper, credential.pk, credential.version)
        self.assertTrue(credentials.verify(secret, rotated.password_hash))
        self.assertEqual(rotated.version, credential.version + 1)

    def test_a_resolution_asks_who_may(self):
        now = timezone.now()
        letter = DeadLetter.objects.create(connection_id=self.connection.pk, topic='farm/x', reason='not_json',
                                           payload_sha256='b' * 64, payload=b'x', payload_len=1, first_at=now,
                                           last_at=now, count=1)
        with self.assertRaises(PermissionDenied):
            services.resolve_dead_letter(self.stranger, letter.pk)
        self.assertIsNone(DeadLetter.objects.get(pk=letter.pk).resolved_at)
        self.assertEqual(services.resolve_dead_letter(self.keeper, letter.pk).resolved_by, self.keeper)
