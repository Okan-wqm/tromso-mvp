"""Migration farm/0030_site_timezone_required on a database with sites that have no time zone (they ran on the company's,
settings.TIME_ZONE, unseen): each is given the company's zone, stored, a site with one keeps it, and the database then
refuses an empty one. Going back leaves the zones as they are."""
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

    @override_settings(TIME_ZONE='Europe/Oslo')
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
