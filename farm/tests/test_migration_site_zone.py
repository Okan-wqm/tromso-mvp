"""Migration farm/0030_site_timezone_required on a database with sites that have no time zone (they ran on the server's UTC
unseen): each is given the company's zone (settings.COMPANY_TIME_ZONE, as production has it: Europe/Oslo unless the
environment names another; never UTC unless the company's is), a site with one keeps it, and the database then refuses an
empty one. Going back leaves the zones as they are."""
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings

BEFORE = [('farm', '0026_production_form_other')]
AFTER = [('farm', '0030_site_timezone_required')]


class SiteZoneMigrationTests(TransactionTestCase):
    serialized_rollback = True

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def setUp(self):
        self.old = self.migrate(BEFORE)
        self.addCleanup(lambda: self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))

    def test_a_site_without_a_time_zone_is_given_the_companys_and_an_empty_one_is_refused_after(self):
        Site = self.old.get_model('farm', 'Site')
        blank = Site.objects.create(name='Bergen', code='BG', timezone='')
        tokyo = Site.objects.create(name='Tokyo', code='TK', timezone='Asia/Tokyo')
        Site = self.migrate(AFTER).get_model('farm', 'Site')
        self.assertEqual(dict(Site.objects.values_list('code', 'timezone')), {'BG': 'Europe/Oslo', 'TK': 'Asia/Tokyo'})
        with self.assertRaises(IntegrityError), transaction.atomic():
            Site.objects.filter(pk=blank.pk).update(timezone='')
        Site = self.migrate(BEFORE).get_model('farm', 'Site')
        self.assertEqual(Site.objects.get(pk=tokyo.pk).timezone, 'Asia/Tokyo')

    @override_settings(COMPANY_TIME_ZONE='Europe/Istanbul')
    def test_the_fill_is_the_company_zone_the_environment_names(self):
        Site = self.old.get_model('farm', 'Site')
        Site.objects.create(name='Izmir', code='IZ', timezone='')
        Site = self.migrate(AFTER).get_model('farm', 'Site')
        self.assertEqual(Site.objects.get(code='IZ').timezone, 'Europe/Istanbul')

    @override_settings(COMPANY_TIME_ZONE='Europe/Olso')
    def test_a_company_zone_that_is_no_zone_is_refused_not_written_into_the_sites(self):
        Site = self.old.get_model('farm', 'Site')
        Site.objects.create(name='Bergen', code='BG', timezone='')
        with self.assertRaisesMessage(ValueError, "COMPANY_TIME_ZONE 'Europe/Olso' is not a known time zone."):
            self.migrate(AFTER)
        self.assertEqual(self.old.get_model('farm', 'Site').objects.get(code='BG').timezone, '')

    @override_settings(COMPANY_TIME_ZONE='Asia/Kolkata')
    def test_its_list_of_zones_is_its_own_frozen_not_the_live_models(self):
        """A zone added to Site.TIMEZONES later does not change what this migration accepts (it never imports live code)."""
        from unittest import mock

        from farm.models import Site as LiveSite
        with mock.patch.object(LiveSite, 'TIMEZONES', [*LiveSite.TIMEZONES, ('Asia/Kolkata', 'Asia/Kolkata')]):
            with self.assertRaisesMessage(ValueError, "COMPANY_TIME_ZONE 'Asia/Kolkata' is not one a site may be given"):
                self.migrate(AFTER)
