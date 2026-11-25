"""A unit's and a system's water history as data (farm:water_unit_chart and farm:water_system_chart with
`?view=history`), what Tank › Water and System › Water draw: the window (24 h, 7 d, 30 d, from and to, or the 12 hours
each side of an alarm), one chart per parameter on that window with the fish's limit bands, the NH₃-N worked out per
sample, the events each for the person who may read them, the Deffeyes replay of the same window; a system's points
side by side. A time that is not one is refused, never read as another window; the old fragment is unchanged."""
import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from alarms.models import Alarm

from .helpers import role
from .test_water import WaterTestCase


class HistoryPageTests(WaterTestCase):
    def setUp(self):
        super().setUp()
        self.stock()
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7)
        self.sample(self.t1, hours=3, oxygen_mg_l='6.50', tan_mg_l='0.500', ph='7.20', temperature_c='12.0')
        self.url = reverse('farm:water_unit_chart', args=[self.t1.pk])

    def history(self, **query):
        response = self.client.get(self.url, {'view': 'history', **query})
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response.json()

    def test_the_default_window_is_the_last_24_hours_with_every_parameter_on_it(self):
        found = self.history()
        self.assertEqual(found['range'], '24h')
        self.assertEqual(found['end'] - found['start'], 24 * 3600)
        (place,) = found['places']
        codes = [chart['quantity']['code'] for chart in place['charts']]
        self.assertEqual(sorted(codes), ['oxygen_mg_l', 'ph', 'tan_mg_l', 'temperature_c'])
        self.assertEqual({(chart['start'], chart['end']) for chart in place['charts']}, {(found['start'], found['end'])})
        oxygen = next(chart for chart in place['charts'] if chart['quantity']['code'] == 'oxygen_mg_l')
        self.assertEqual(oxygen['bands'], {'critical_low': 6.0, 'warning_low': 7.0})
        self.assertEqual([sample['value'] for sample in oxygen['samples']], [6.5])
        # each sample judged as the history page judges it, and said in words (review of batch 1, S1)
        self.assertEqual([(sample['status'], sample['status_text']) for sample in oxygen['samples']], [('warning', 'Warning')])
        (nh3,) = place['worked']['nh3_n_mg_l']['values']
        self.assertGreater(nh3['value'], 0)

    def test_the_presets_and_a_custom_window(self):
        week = self.history(range='7d')
        self.assertEqual(week['end'] - week['start'], 7 * 86400)
        start = (timezone.now() - timedelta(days=2)).strftime('%Y-%m-%dT%H:%M')
        end = (timezone.now() - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')
        found = self.history(start=start, end=end)
        self.assertEqual((found['range'], found['end'] - found['start']), ('custom', 86400))
        self.assertEqual(found['places'][0]['charts'], [])           # nothing in that day: no chart, never an OK one

    def test_a_window_that_is_not_one_is_refused(self):
        for query in ({'start': 'yesterday', 'end': '2026-01-01T00:00'}, {'start': '2026-01-02T00:00',
                                                                          'end': '2026-01-01T00:00'},
                      {'start': '2020-01-01T00:00', 'end': '2026-01-01T00:00'}, {'around': 'x'},
                      {'around': '2050-01-01T00:00'}, {'around': '01.01.2100 00:00'}):   # no window after now
            with self.subTest(query=query):
                self.assertEqual(self.client.get(self.url, {'view': 'history', **query}).status_code, 400)

    def test_the_12_hours_around_an_alarm(self):
        opened = (timezone.now() - timedelta(days=1)).replace(second=0, microsecond=0)
        found = self.history(around=opened.strftime('%Y-%m-%dT%H:%M'))
        self.assertEqual((found['start'], found['end']), (int((opened - timedelta(hours=12)).timestamp()),
                                                          int((opened + timedelta(hours=12)).timestamp())))

    def test_the_events_each_for_the_person_who_may_read_them(self):
        Alarm.objects.create(source='water_limit', point=self.mid1, parameter='oxygen_mg_l', severity='critical',
                             site=self.bergen, opened_at=timezone.now() - timedelta(hours=2), summary='O₂ 5.9 mg/L')
        self.assertEqual(self.history()['events'], [])                        # a water keeper reads no alarm
        self.user.groups.add(role('Alarm reader', 'view_alarm'))
        self.user = get_user_model().objects.get(pk=self.user.pk)            # the rights read again
        self.client.force_login(self.user)
        (event,) = self.history()['events']
        self.assertEqual((event['kind'], event['label'], event['severity']), ('alarm', 'O₂ 5.9 mg/L', 'critical'))
        self.assertTrue(event['url'].startswith('/alarms/'))

    def test_the_sensor_values_need_their_right_and_the_chart_says_so(self):
        oxygen = next(chart for chart in self.history()['places'][0]['charts']
                      if chart['quantity']['code'] == 'oxygen_mg_l')
        self.assertEqual(oxygen['buckets']['avg'], [])
        self.assertIn('Sensor values are not shown', ' '.join(oxygen['notes']))
        self.assertEqual(self.history()['deffeyes'], '')

    def test_a_system_shows_each_of_its_points_side_by_side(self):
        self.sample(self.ras, hours=2, oxygen_mg_l='8.00')
        response = self.client.get(reverse('farm:water_system_chart', args=[self.ras.pk]), {'view': 'history'})
        places = response.json()['places']
        self.assertEqual(places[0]['kind'], 'middle')                          # the loop first
        self.assertEqual([sample['value'] for sample in places[0]['charts'][0]['samples']], [8.0])

    def test_reading_needs_the_water_right(self):
        other = get_user_model().objects.create_user('other', 'other@example.com', 'x')
        other.groups.add(role('Stock reader', 'view_stockoperation'))
        self.client.force_login(other)
        self.assertEqual(self.client.get(self.url, {'view': 'history'}).status_code, 403)

    def test_without_view_the_fragment_is_the_old_one(self):
        response = self.client.get(self.url)
        self.assertTemplateUsed(response, 'farm/_unit_chart.html')
        self.assertEqual(response['Content-Type'].split(';')[0], 'text/html')



class LinksIntoTankWaterTests(WaterTestCase):
    """The links into Tank › Water (`farm:tank_water`, the one home of a tank's water history), in the new look only: a
    unit's row on Water chemistry's latest page, and an alarm's detail with the 12 hours each side of its opening
    (`?around=` on the site's clock, dd.mm.yyyy HH:MM). The classic look keeps its links (the history page)."""

    def setUp(self):
        super().setUp()
        self.stock()

    def look(self, value):
        if value is None:
            self.client.cookies.pop('ui', None)
        else:
            self.client.cookies['ui'] = value

    def test_a_units_row_on_the_water_page_opens_tank_water_in_the_new_look(self):
        tank_water = reverse('farm:tank_water', args=[self.t1.pk])
        self.look('next')
        self.assertContains(self.client.get(reverse('farm:water')), f'href="{tank_water}"')
        self.look(None)
        page = self.client.get(reverse('farm:water'))
        self.assertNotContains(page, f'href="{tank_water}"')
        self.assertContains(page, 'href="/operations/water/?point=')                  # the history page, as before

    def test_an_alarms_detail_opens_its_units_water_around_its_opening_in_the_new_look(self):
        self.user.groups.add(role('Alarm reader', 'view_alarm'))
        self.user = get_user_model().objects.get(pk=self.user.pk)
        self.client.force_login(self.user)
        opened = timezone.now().replace(second=0, microsecond=0) - timedelta(hours=5)
        alarm = Alarm.objects.create(source='water_limit', point=self.mid1, parameter='oxygen_mg_l', severity='critical',
                                     site=self.bergen, opened_at=opened, summary='O₂ 5.9 mg/L')
        detail = reverse('alarms:alarm_detail', args=[alarm.pk])
        around = f"{reverse('farm:tank_water', args=[self.t1.pk])}?around={opened:%d.%m.%Y}+{opened:%H}%3A{opened:%M}"
        self.look('next')
        self.assertContains(self.client.get(detail), f'href="{around}"')       # the site's clock is UTC here
        found = self.client.get(around).context['props']
        self.assertEqual(found['start'], int((opened - timedelta(hours=12)).timestamp()))
        self.assertLessEqual(found['end'] - found['start'], 24 * 3600)                     # clipped at now
        self.look(None)
        self.assertNotContains(self.client.get(detail), 'around=')
        loop = Alarm.objects.create(source='water_limit', point=self.loop, parameter='oxygen_mg_l', severity='critical',
                                    site=self.bergen, opened_at=opened, summary='O₂ 5.9 mg/L')
        self.look('next')
        self.assertNotContains(self.client.get(reverse('alarms:alarm_detail', args=[loop.pk])), 'around=')


class AroundOnAClockThatChangesTests(WaterTestCase):
    """Review C4: an alarm's link carries its opening on the site's clock as a wall time (dd.mm.yyyy HH:MM). In the autumn
    night the clocks show 02:00 to 03:00 twice: such a time is read as the earlier of the two (the window, 12 hours each
    side, holds the opening either way), never refused. The spring night has no 02:00 to 03:00: no alarm opens at such a
    wall time, so its link never names one; typed by hand it is refused (400)."""

    look = LinksIntoTankWaterTests.look

    def setUp(self):
        super().setUp()
        self.stock()
        self.bergen.timezone = 'Europe/Oslo'
        self.bergen.save()
        self.user.groups.add(role('Alarm reader', 'view_alarm'))
        self.user = get_user_model().objects.get(pk=self.user.pk)
        self.client.force_login(self.user)
        self.look('next')

    def window_of_alarm_opened(self, opened):
        alarm = Alarm.objects.create(source='water_limit', point=self.mid1, parameter='oxygen_mg_l', severity='critical',
                                     site=self.bergen, opened_at=opened, summary='O₂ 5.9 mg/L')
        page = self.client.get(reverse('alarms:alarm_detail', args=[alarm.pk])).content.decode()
        link = re.search(r'href="([^"]*around=[^"]*)"', page).group(1).replace('&amp;', '&')
        response = self.client.get(link)
        self.assertEqual(response.status_code, 200, link)
        props = response.context['props']
        return link, props['start'], props['end']

    def test_an_alarm_in_the_autumn_nights_repeated_hour_gets_a_working_link(self):
        from datetime import datetime, timezone as tz
        for opened in (datetime(2026, 10, 25, 0, 30, tzinfo=tz.utc), datetime(2026, 10, 25, 1, 30, tzinfo=tz.utc)):
            with self.subTest(opened=opened):                       # 02:30 CEST, then 02:30 CET: the same wall time
                link, start, end = self.window_of_alarm_opened(opened)
                self.assertIn('around=25.10.2026+02%3A30', link)
                self.assertLessEqual(start, opened.timestamp())
                self.assertGreaterEqual(end, opened.timestamp())

    def test_an_alarm_after_the_spring_nights_skipped_hour_gets_its_own_time(self):
        from datetime import datetime, timezone as tz
        opened = datetime(2026, 3, 29, 1, 30, tzinfo=tz.utc)                  # 03:30 CEST, the hour after the gap
        link, start, end = self.window_of_alarm_opened(opened)
        self.assertIn('around=29.03.2026+03%3A30', link)
        self.assertEqual(start, int(opened.timestamp()) - 12 * 3600)
        skipped = reverse('farm:tank_water', args=[self.t1.pk]) + '?around=29.03.2026+02%3A30'
        self.assertEqual(self.client.get(skipped).status_code, 400)
