"""Migration farm/0028_site_altitude_range on a database that already has sites (F-089): an altitude within 0 .. 5000 m
stays; one outside it (a slip: a minus sign, two zeros too many; the owner: no site of ours lies below sea level) is
moved into the site's notes with the day the migration ran and emptied, each change written to the activity log, so the
oxygen is worked out at sea-level pressure and the pages say so, never at an impossible pressure; the database then
holds the range, and going back puts every moved altitude back from the log."""
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

BEFORE = [('farm', '0026_production_form_other')]
AFTER = [('farm', '0028_site_altitude_range')]
D = Decimal


class AltitudeMigrationTests(TransactionTestCase):
    serialized_rollback = True

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def setUp(self):
        self.old = self.migrate(BEFORE)
        self.addCleanup(lambda: self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))

    def sites(self, apps):
        Site = apps.get_model('farm', 'Site')
        return (Site.objects.create(name='Fjell', code='FJ', altitude=D('812.50')),
                Site.objects.create(name='Shore', code='SH', altitude=D('0')),
                Site.objects.create(name='Dead Sea', code='DS', altitude=D('-430')),
                Site.objects.create(name='Typo', code='TY', altitude=D('50000'), notes='Hall B is new.'),
                Site.objects.create(name='Minus', code='MI', altitude=D('-5000')))

    def test_an_altitude_off_the_range_goes_to_the_notes_with_a_log_entry_and_the_rest_stay(self):
        kept, sea, low, typo, minus = self.sites(self.old)
        new = self.migrate(AFTER)
        Site, AuditLog = new.get_model('farm', 'Site'), new.get_model('core', 'AuditLog')
        self.assertEqual(Site.objects.get(pk=kept.pk).altitude, D('812.50'))
        self.assertEqual(Site.objects.get(pk=sea.pk).altitude, D('0'))
        today = timezone.localdate().isoformat()
        for site, typed in ((typo, '50000.00'), (minus, '-5000.00'), (low, '-430.00')):
            row = Site.objects.get(pk=site.pk)
            self.assertIsNone(row.altitude)
            self.assertIn(f'Altitude before migration 0028 ({today}), outside 0 .. 5000 m: {typed}', row.notes)
            entry = AuditLog.objects.get(entity_type='site', entity_id=str(site.pk))
            self.assertEqual((entry.action, entry.user_name, entry.entity_label), ('update', 'system', site.name))
            self.assertEqual(entry.changes['Altitude (m)'], [typed, None])
        self.assertEqual(AuditLog.objects.filter(entity_type='site').count(), 3)       # the sites in range: none
        self.assertTrue(Site.objects.get(pk=typo.pk).notes.startswith('Hall B is new.\n'))
        with self.assertRaisesMessage(IntegrityError, 'chk_sites_altitude_range'), transaction.atomic():
            Site.objects.filter(pk=kept.pk).update(altitude=D('5001'))

    def test_going_back_puts_each_moved_altitude_and_its_notes_back(self):
        kept, sea, low, typo, minus = self.sites(self.old)
        self.migrate(AFTER)
        old = self.migrate(BEFORE)
        Site = old.get_model('farm', 'Site')
        for site, altitude, notes in ((typo, D('50000'), 'Hall B is new.'), (minus, D('-5000'), ''),
                                      (low, D('-430'), ''), (kept, D('812.50'), '')):
            row = Site.objects.get(pk=site.pk)
            self.assertEqual((row.altitude, row.notes), (altitude, notes))

    def test_going_back_leaves_a_site_corrected_since_alone(self):
        """Second cross review, finding 7: going back restores only a site that still holds what the migration left (no
        altitude and the notes it wrote); an altitude or notes entered since stay, never overwritten by the old slip."""
        kept, sea, low, typo, minus = self.sites(self.old)
        new = self.migrate(AFTER)
        Site = new.get_model('farm', 'Site')
        Site.objects.filter(pk=typo.pk).update(altitude=D('812'))                   # the right altitude entered since
        notes = Site.objects.get(pk=low.pk).notes
        Site.objects.filter(pk=low.pk).update(notes=f'{notes}\nChecked by the site manager.')   # notes edited since
        old = self.migrate(BEFORE)
        Site = old.get_model('farm', 'Site')
        self.assertEqual(Site.objects.get(pk=typo.pk).altitude, D('812'))
        self.assertIsNone(Site.objects.get(pk=low.pk).altitude)
        self.assertTrue(Site.objects.get(pk=low.pk).notes.endswith('Checked by the site manager.'))
        self.assertEqual((Site.objects.get(pk=minus.pk).altitude, Site.objects.get(pk=minus.pk).notes), (D('-5000'), ''))
