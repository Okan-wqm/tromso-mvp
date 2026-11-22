"""The pH window's scale is the farm's reference data, per water type (owner decision 15, 2026-11-16): one row for
each of the product's water types (farm.models.tank.WaterType: the class a unit's water already has), seeded with the
6.4 to 8.6 the code held; changed on Setup › Reference data › pH window scales, never added or deleted. The window, its
name in words and the off-scale rule read the row of the unit's water, once for a wall (no query per card); a water
whose row is gone says so and draws nothing rather than fall back on a number of the code."""
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core import access, navigation
from core.models import AuditLog
from farm.models.tank import WaterType

from .. import read
from ..cards import builtin, catalogue
from ..cards.resolve import Choice
from ..models import PhWindowScale
from . import ALL_RIGHTS
from .test_small import SmallCase, card_of, nodes, text

D = Decimal
SCALES = reverse('monitoring:phwindowscale_list')
TABLE = '"monitor_ph_window_scales"'


def window_of(html, unit):
    (window,) = nodes(card_of(html, unit), 'monitor-ph-window')
    return window


class SeedTests(SmallCase):
    def test_todays_scale_is_the_seeded_row_of_every_water_type(self):
        self.assertEqual({row.water_type: (row.ph_low, row.ph_high) for row in PhWindowScale.objects.all()},
                         {water: (D('6.4'), D('8.6')) for water in WaterType.values})
        self.assertFalse(hasattr(catalogue, 'PH_WINDOW'))            # the code holds no scale of its own any more

    def test_the_database_refuses_nonsense_a_second_row_and_a_deleted_one(self):
        fresh = PhWindowScale.objects.filter(water_type='freshwater')
        for values in ({'ph_low': D('8.0'), 'ph_high': D('7.0')}, {'ph_low': D('7.0'), 'ph_high': D('7.2')},
                       {'ph_low': D('-1')}, {'ph_high': D('14.5')}, {'is_deleted': True}, {'water_type': 'any'},
                       {'water_type': 'saltwater'}):
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                fresh.update(**values)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PhWindowScale.objects.create(water_type='freshwater', ph_low=D('6'), ph_high=D('9'))


class WindowTests(SmallCase):
    def scale(self, water, low, high):
        PhWindowScale.objects.filter(water_type=water).update(ph_low=D(low), ph_high=D(high))

    def test_the_mark_the_name_and_the_off_scale_rule_read_the_row_of_the_units_water(self):
        self.assertEqual(self.t2.water_type, 'freshwater')
        self.scale('freshwater', '6.0', '8.0')
        self.good_water(ph='7.20')
        window = window_of(self.page(), self.t2)
        (mark,) = nodes(window, 'chart-water')
        self.assertEqual(mark.attrs['cx'], '60.0%')                                  # (7.2 - 6.0) / (8.0 - 6.0)
        # 6.10 was off the code's scale (6.4): on this farm's it is a mark
        self.good_water(ph='6.10', alkalinity_mg_l='20')
        window = window_of(self.page(), self.t2)
        (mark,) = nodes(window, 'chart-water')
        self.assertEqual(mark.attrs['cx'], '5.0%')
        self.assertNotIn('off the scale', window.attrs['aria-label'])
        # and 8.10, on the code's scale, is beyond this farm's: the arrow and the number, the scale said in words
        self.good_water(ph='8.10')
        window = window_of(self.page(), self.t2)
        self.assertFalse(nodes(window, 'chart-water'))
        (off,) = [each for each in window.walk() if 'data-off-scale' in each.attrs]
        self.assertEqual(text(off), '8.10 ▶')
        self.assertIn('off the scale (6.0 to 8.0)', window.attrs['aria-label'])

    def test_each_water_type_has_its_own_scale(self):
        self.scale('saltwater', '7.5', '8.5')
        self.good_water(ph='7.20')
        self.t1.water_type = 'saltwater'
        self.t1.save()
        self.good_water(self.t1, ph='8.00', salinity_ppt='34')
        html = self.page()
        (sea,) = nodes(window_of(html, self.t1), 'chart-water')
        (fresh,) = nodes(window_of(html, self.t2), 'chart-water')
        self.assertEqual((sea.attrs['cx'], fresh.attrs['cx']), ('50.0%', f'{(7.2 - 6.4) / 2.2 * 100:.1f}%'))

    def test_a_water_whose_row_is_gone_says_so_and_draws_nothing(self):
        self.good_water()
        PhWindowScale.all_objects.filter(water_type='freshwater').delete()
        card = card_of(self.page(), self.t2)
        self.assertFalse(nodes(card, 'monitor-ph-window'))
        (refused,) = nodes(card, 'monitor-ph-refused')
        self.assertEqual(text(refused), 'The pH window cannot be drawn: no scale is set for freshwater.')
        self.assertFalse(PhWindowScale.all_objects.filter(water_type='freshwater').exists())    # a read writes nothing

    def test_a_wall_reads_the_scales_once_and_a_wall_without_the_window_never(self):
        units = self.farm_of(8)
        user = self.as_person('scale-budget', *ALL_RIGHTS)
        read.sections_for(user)
        counts = []
        for shown in (units[:2], units):
            with CaptureQueriesContext(connection) as log:
                read.cards(shown, user, Choice(view=builtin.SMALL))
            counts.append(sum(TABLE in query['sql'] for query in log))
        self.assertEqual(counts, [1, 1])
        for view in (builtin.BIG, builtin.SIMPLE):
            with CaptureQueriesContext(connection) as log:
                read.cards(units, user, Choice(view=view))
            self.assertEqual(sum(TABLE in query['sql'] for query in log), 0, view)


class PagesTests(SmallCase):
    def edit(self, water='freshwater'):
        return reverse('monitoring:phwindowscale_edit', args=[PhWindowScale.objects.get(water_type=water).pk])

    def test_the_list_shows_a_row_per_water_type_and_only_change_exists(self):
        self.as_person('scales', 'view_phwindowscale', 'change_phwindowscale')
        listing = self.client.get(SCALES)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(sorted(row.water_type for row in listing.context['objects']), sorted(WaterType.values))
        html = listing.content.decode()
        for word in ('Freshwater', 'Saltwater', 'Brackish', '6.4', '8.6'):
            self.assertIn(word, html)
        names = {route.name for route in __import__('monitoring.urls', fromlist=['urlpatterns']).urlpatterns}
        self.assertIn('phwindowscale_edit', names)
        self.assertFalse({'phwindowscale_create', 'phwindowscale_delete'} & names)

    def test_a_change_through_the_page_is_stored_logged_and_drawn(self):
        user = self.as_person('scales', 'view_phwindowscale', 'change_phwindowscale')
        row = PhWindowScale.objects.get(water_type='freshwater')
        response = self.client.post(self.edit(), {'ph_low': '6.0', 'ph_high': '8.0', 'version': row.version})
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None) and response.context['form'].errors)
        row.refresh_from_db()
        self.assertEqual((row.ph_low, row.ph_high, row.updated_by, row.version), (D('6.0'), D('8.0'), user, 2))
        logged = AuditLog.objects.get(entity_type='pH window scale', action='update')
        self.assertEqual((logged.changes['From pH'], logged.changes['To pH']), (['6.4', '6.0'], ['8.6', '8.0']))
        self.client.force_login(self.reader)
        self.good_water(ph='7.20')
        (mark,) = nodes(window_of(self.page(), self.t2), 'chart-water')
        self.assertEqual(mark.attrs['cx'], '60.0%')

    def test_the_form_refuses_a_scale_that_cannot_be_a_scale(self):
        self.as_person('scales', 'view_phwindowscale', 'change_phwindowscale')
        row = PhWindowScale.objects.get(water_type='freshwater')
        for low, high, field in (('8.0', '7.0', 'ph_high'), ('7.0', '7.3', 'ph_high'), ('-0.5', '8.0', 'ph_low'),
                                 ('6.0', '14.5', 'ph_high')):
            with self.subTest(low=low, high=high):
                response = self.client.post(self.edit(), {'ph_low': low, 'ph_high': high, 'version': row.version})
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context['form'].errors)
        row.refresh_from_db()
        self.assertEqual((row.ph_low, row.ph_high), (D('6.4'), D('8.6')))

    def test_reading_and_changing_each_need_their_right(self):
        self.as_person('nobody', 'view_stockoperation')
        self.assertEqual(self.client.get(SCALES).status_code, 403)
        self.as_person('looker', 'view_phwindowscale')
        self.assertEqual(self.client.get(SCALES).status_code, 200)
        self.assertEqual(self.client.get(self.edit()).status_code, 403)
        self.assertEqual(self.client.post(self.edit(), {'ph_low': '6.0', 'ph_high': '8.0', 'version': 1}).status_code, 403)

    def test_the_menu_and_the_role_matrix_know_the_tab(self):
        place = navigation.page('monitoring:phwindowscale_list')
        self.assertEqual((str(place.entry.label), place.entry.perm),
                         ('pH window scales', 'monitoring.view_phwindowscale'))
        (area,) = [each for each in access.areas() if each.model == 'monitoring.PhWindowScale']
        self.assertEqual(tuple(area.actions), ('view', 'change'))
