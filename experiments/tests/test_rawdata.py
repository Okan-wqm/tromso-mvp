"""The raw data of an experiment as one CSV for its team (owner 2026-11-24, experiments/rawdata.py): every value recorded
on its tanks on their days, dates dd.mm.yyyy, voided records out; whoever reads its data downloads it, each download in
the read log; a grantee of another part is refused (logged), and for an outsider the address answers as an unknown one."""
import csv
import io
import uuid
from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AccessEvent
from farm.models import FeedingRecord

from .. import rawdata
from ..models import ExperimentShare
from . import world


def address(experiment_id):
    return reverse('experiments:experiment_raw_data', args=[experiment_id])


class RawDataTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        world.build_open(cls)
        world.build_sealed(cls)

    def download(self, user, experiment_id=None):
        client = Client()
        client.force_login(user)
        return client.get(address(experiment_id or self.experiment.pk))

    def table(self, response):
        text = response.content.decode('utf-8-sig')
        return list(csv.reader(io.StringIO(text)))

    def test_the_team_downloads_every_value_of_its_tanks_with_dates_as_the_farm_writes_them(self):
        response = self.download(self.lead)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn(f'{self.experiment.code}-raw-data-', response['Content-Disposition'])
        header, *rows = self.table(response)
        self.assertEqual(tuple(header), rawdata.HEADER)
        yesterday = (self.today - timedelta(days=1)).strftime('%d.%m.%Y')
        tank = self.sealed_tanks[0].code
        self.assertIn([yesterday, '', 'XQZ group SQZ DQZ', 'R1', tank, 'feeding', 'GR-4', 'amount_kg', '1.500'], rows)
        self.assertIn([yesterday, '', 'XQZ group SQZ DQZ', 'R1', tank, 'lice', '', 'adult_females', '2'], rows)
        self.assertTrue(any(row[4] == tank and row[5] == 'water' and row[7] == 'ph' and row[8] == '7.30' for row in rows))
        self.assertTrue(any(row[4] == tank and row[5] == 'stock' and row[7] == 'count_delta' for row in rows))
        self.assertFalse([row for row in rows if row[4] not in {each.code for each in self.sealed_tanks}])

    def test_a_voided_record_is_not_in_it(self):
        FeedingRecord.objects.filter(pk=self.feeding.pk).update(is_deleted=True, void_reason='Typed twice')
        rows = self.table(self.download(self.lead))[1:]
        self.assertFalse([row for row in rows if row[5] == 'feeding'])

    def test_every_download_is_in_the_read_log_the_teams_too(self):
        self.download(self.lead)
        event = AccessEvent.objects.get(entity_id=str(self.experiment.pk), kind=AccessEvent.Kind.EXPORT)
        self.assertEqual((event.user_id, event.part), (self.lead.pk, 'data'))

    def test_a_grantee_of_the_data_downloads_it_a_grantee_of_the_water_is_refused_and_logged(self):
        until = timezone.now() + timedelta(days=5)
        ExperimentShare.objects.create(experiment=self.experiment, user=self.researcher, part='water', reason='Audit',
                                       valid_until=until)
        self.assertEqual(self.download(self.researcher).status_code, 403)
        self.assertTrue(AccessEvent.objects.filter(user_id=self.researcher.pk, kind=AccessEvent.Kind.DENIED,
                                                   part='data').exists())
        ExperimentShare.objects.create(experiment=self.experiment, user=self.researcher, part='data', reason='Analysis',
                                       valid_until=until)
        self.assertEqual(self.download(self.researcher).status_code, 200)

    def test_for_an_outsider_the_address_answers_as_an_unknown_one(self):
        sealed, unknown = self.download(self.researcher), self.download(self.researcher, uuid.UUID(int=0xFEED))
        self.assertEqual((sealed.status_code, unknown.status_code), (404, 404))
        self.assertFalse(AccessEvent.objects.filter(user_id=self.researcher.pk).exists())

    def test_the_data_tab_offers_it(self):
        client = Client()
        client.force_login(self.lead)
        page = client.get(reverse('experiments:experiment_detail', args=[self.experiment.pk]) + '?tab=data')
        self.assertContains(page, address(self.experiment.pk))
