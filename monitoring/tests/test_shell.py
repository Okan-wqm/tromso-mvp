"""Shell-first (live-arch stage 1): the page is drawn without its cards and the grid's first poll brings them.

- The shell: the toolbar, the grid's place with "Loading the cards…", the windows' place; no card, band, tally, state word
  or state colour, whatever the water says, so a page whose cards have not come never reads as all is well.
- It reads no card source: a source that fails leaves it a 200 (its first fill is then the 503), and it costs the same
  queries for any farm.
- Its first fill is always the cards: the grid's address carries no token, so the fragment answers 200 with the next
  address, never 204; a signed-out person gets the answer poll.ts reads as gone.
- The shell with its first answers put where frontend/poll.ts puts them is, byte for byte, the full page (`?full=1`, the
  page as it was), for the modes, the wall, a board, a flipped card and the pane: the old pages' tests, which now read
  `?full=1`, hold for what the browser shows.
- With a focus the pane's frame is drawn and its body filled the same way."""
import html as markup
import re
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from core.models import Profile

from .. import read
from ..models import MonitorBoard, MonitorBoardUnit
from . import MonitoringCase

PAGE, CARDS, PANE = reverse('monitoring:monitor'), reverse('monitoring:cards'), reverse('monitoring:pane')
GRID = re.compile(r'(<div class="monitor-grid"[^>]*>)(<div class="monitor-loading" data-key="loading">.*?</div>\n)(</div>)',
                  re.S)
BODY = re.compile(r'(<div class="monitor-window-body" data-window-body data-poll="[^"]*"[^>]*>)'
                  r'(<div class="monitor-loading" data-key="loading">.*?</div>\n)(</div>)', re.S)
# What a page holds that is not the page's own: the response's nonce, the form's token, the sign-in form's way back.
VOLATILE = ((re.compile(r'nonce="[^"]*"'), 'nonce=""'), (re.compile(r'name="csrfmiddlewaretoken" value="[^"]*"'), 'csrf'),
            (re.compile(r'name="next" value="[^"]*"'), 'next'))


def plain(text):
    for pattern, put in VOLATILE:
        text = pattern.sub(put, text)
    return text


def poll_of(opening):
    return markup.unescape(re.search(r'data-poll="([^"]*)"', opening).group(1))


class ShellCase(MonitoringCase):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(read, 'TOKEN_BUCKET', 10 ** 9)          # the minute does not roll over under the test
        patch.start()
        self.addCleanup(patch.stop)

    def shell(self, query=''):
        response = self.client.get(f'{PAGE}?{query}' if query else PAGE)
        self.assertEqual(response.status_code, 200, query)
        return response.content.decode()

    def fill(self, opening, query):
        """What poll.ts does with the element's first answer: asks its address (from the page), and the answer, its
        next address followed and the state live, replaces the placeholder. (opening, body) of the element."""
        response = self.client.get(poll_of(opening))
        self.assertEqual(response.status_code, 200, query)             # the first fill is always the cards
        after = response['X-Poll-Next']
        self.assertIn('after=', after)
        opening = re.sub(r'data-poll="[^"]*"', lambda _m: f'data-poll="{markup.escape(after)}"', opening, count=1)
        return opening.replace('data-poll-state="loading"', 'data-poll-state="live"', 1), response.content.decode()

    def spliced(self, query):
        """The shell of `query` with its grid's first answer, and its pane's when it has one, put in place."""
        page = self.shell(query)
        match = GRID.search(page)
        self.assertIsNotNone(match, query)
        opening, body = self.fill(match.group(1), query)
        page = page[:match.start()] + opening + body + match.group(3) + page[match.end():]
        match = BODY.search(page)
        if match is not None:
            opening, body = self.fill(match.group(1), query)
            page = page[:match.start()] + opening + body + match.group(3) + page[match.end():]
        return page

    def grid_of(self, page):
        return GRID.search(page).group(2)


class ShellTests(ShellCase):
    def critical(self):
        """T-02's oxygen far under its critical limit: the full page draws it critical, in the band and on its card."""
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7)
        self.sample(self.t2, hours=1, temperature_c='9.5', oxygen_mg_l='3.1', ph='7.2')
        full = self.client.get(PAGE, {'full': '1'}).content.decode()
        self.assertIn('data-state="critical"', full)
        self.assertIn('class="monitor-tally', full)

    def test_the_page_is_the_shell_with_no_card_band_tally_state_or_colour(self):
        self.critical()
        for query in ('', 'mode=detailed', 'mode=small', 'mode=big', 'wall=1', 'occupancy=all', f'focus={self.t2.pk}'):
            with self.subTest(query=query):
                page = self.shell(query)
                grid = self.grid_of(page)
                self.assertIn('Loading the cards…', grid)
                for absent in ('data-key="band"', 'data-key="card:', 'class="monitor-tally', 'monitor-shape', '<article',
                               'computed at', 'units shown', 'No unit matches', '3.10', 'data-state="'):
                    self.assertNotIn(absent, page)
                # what the screen shows (the grid and the pane; the announcer's hidden list of the state words aside)
                shown = grid + re.search(r'<aside class="monitor-dock".*?</aside>', page, re.S).group(0)
                for absent in ('Critical', 'Warning', 'OK', 'No recent data', 'monitor-critical', 'monitor-warning',
                               'monitor-ok', 'monitor-blind'):
                    self.assertNotIn(absent, shown)
                opening = GRID.search(page).group(1)
                self.assertIn('data-poll-state="loading"', opening)
                self.assertNotIn('after=', poll_of(opening))                # no token: the first answer is the cards
                self.assertEqual(poll_of(opening), f'{CARDS}?{query}' if query else CARDS)
                # without script: the way to the page drawn with its cards
                link = re.search(r'<noscript><p><a href="([^"]+)">([^<]+)</a></p></noscript>', grid)
                self.assertEqual(markup.unescape(link.group(1)), f'{PAGE}?{query}&full=1' if query else f'{PAGE}?full=1')
                self.assertEqual(link.group(2), 'JavaScript is off: show the full page with the cards')
                # what the page says when its first answer fails, shown by static/css/monitor.css only then
                self.assertIn('<p data-unread>The cards cannot be read just now. The page tries again by itself.</p>',
                              grid)

    def test_the_shell_reads_no_card_source_and_costs_the_same_for_any_farm(self):
        with mock.patch.object(read, 'cards', side_effect=AssertionError('the shell read the cards')), \
                mock.patch.object(read, 'change_token', side_effect=AssertionError('the shell read a token')):
            self.shell()
            self.shell(f'focus={self.t2.pk}&mode=small')
        self.shell()                                                        # warm
        with CaptureQueriesContext(connection) as few:
            self.shell()
        self.farm_of(12)
        with CaptureQueriesContext(connection) as many:
            self.shell()
        self.assertEqual(len(many), len(few))
        tables = ' '.join(query['sql'] for query in many)
        for table in ('"stock_movements"', '"water_measurements"', '"feeding_records"', '"batches"', '"audit_log"'):
            self.assertNotIn(table, tables)
        verbs = {query['sql'].lstrip().split(None, 1)[0].upper() for query in many}
        self.assertLessEqual(verbs, {'SELECT'})                             # the shell writes nothing

    def test_a_source_that_fails_leaves_the_shell_and_makes_its_first_fill_the_503(self):
        read.FAILED_AT.clear()
        with mock.patch.object(read.stock_read, 'stock_of', side_effect=RuntimeError('down')), \
                self.assertLogs('monitoring.read', 'ERROR'):
            page = self.shell()
            self.assertIn('Loading the cards…', page)
            first = self.client.get(poll_of(GRID.search(page).group(1)))
            self.assertEqual((first.status_code, first['Cache-Control'], first['Retry-After']), (503, 'no-store', '30'))
            self.assertNotIn(b'data-key="card:', first.content)
            self.assertEqual(self.client.get(PAGE, {'full': '1'}).status_code, 503)     # the page drawn with them: as before

    def test_the_first_fill_is_never_a_204_and_its_answer_leads_to_the_204s(self):
        address = poll_of(GRID.search(self.shell()).group(1))
        first = self.client.get(address)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.client.get(first['X-Poll-Next']).status_code, 204)     # nothing changed since
        again = self.client.get(address)                                    # a reload, a second screen: the cards again
        self.assertEqual((again.status_code, again['X-Poll-Next']), (200, first['X-Poll-Next']))
        self.assertEqual(again.content, first.content)

    def test_a_signed_out_first_fill_is_an_answer_poll_reads_as_gone(self):
        address = poll_of(GRID.search(self.shell()).group(1))
        self.client.logout()
        response = self.client.get(address)
        self.assertIn(response.status_code, (302, 401, 403))                # poll.ts: a redirect, 401 or 403 is gone
        if response.status_code == 302:
            self.assertIn(reverse('login'), response['Location'])
        self.assertNotIn(b'data-key="card:', response.content)

    def test_the_shell_in_norwegian_and_turkish(self):
        for language, words in {'nb': ('Laster kortene …', 'Kortene kan ikke leses akkurat nå. Siden prøver igjen av seg selv.',
                                       'JavaScript er slått av: vis hele siden med kortene'),
                                'tr': ('Kartlar yükleniyor…', 'Kartlar şu anda okunamıyor. Sayfa kendiliğinden yeniden deniyor.',
                                       'JavaScript kapalı: kartlarla birlikte tam sayfayı göster')}.items():
            Profile.objects.update_or_create(user=self.reader, defaults={'language': language})
            grid = self.grid_of(self.shell())
            for text in words:
                self.assertIn(markup.escape(text), grid, language)


class FocusTests(ShellCase):
    def test_a_focus_draws_the_panes_frame_and_its_body_fills_at_once(self):
        page = self.shell(f'focus={self.t2.pk}&mode=small')
        frame = re.search(r'<aside class="monitor-dock".*?</aside>', page, re.S).group(0)
        self.assertIn('aria-label="Focus: T-02"', frame)
        self.assertIn(f'data-dock-unit="{self.t2.pk}"', frame)
        self.assertIn(f'href="{PAGE}?mode=small"', frame)                   # closing is a link, as on the full page
        self.assertNotIn('<article', frame)                                 # its card comes with the first poll
        opening = BODY.search(frame).group(1)
        self.assertIn('data-poll-state="loading"', opening)
        self.assertEqual(poll_of(opening), f'{PANE}?focus={self.t2.pk}&mode=small')
        self.assertIn('Loading…', BODY.search(frame).group(2))
        self.assertNotIn('<noscript>', BODY.search(frame).group(2))         # the grid's placeholder says it once
        self.assertEqual(self.client.get(poll_of(opening)).status_code, 200)

    def test_a_focus_on_a_unit_that_is_not_there_draws_no_pane_as_the_full_page(self):
        query = 'focus=5f1c2a6e-0000-4000-8000-0000000000aa'
        self.assertRegex(self.shell(query), r'<aside class="monitor-dock"[^>]*></aside>')
        self.assertRegex(self.client.get(f'{PAGE}?{query}&full=1').content.decode(),
                         r'<aside class="monitor-dock"[^>]*></aside>')


class ParityTests(ShellCase):
    """The shell with its first answers in place is the full page, byte for byte (with the clock pinned, so the cards
    and the tokens are the same in both)."""

    def test_the_shell_with_its_first_answers_is_the_full_page(self):
        self.limit('oxygen_mg_l', critical_low=6, warning_low=7)
        self.sample(self.t2, hours=1, temperature_c='9.5', oxygen_mg_l='3.1', ph='7.2')
        board = MonitorBoard.objects.create(name='Hall wall', default_mode='detailed')
        MonitorBoardUnit.objects.create(board=board, unit=self.t1, mode='simple')
        with mock.patch('django.utils.timezone.now', return_value=timezone.now()):
            for query in ('', 'mode=detailed', 'mode=small', 'mode=big', 'occupancy=all', 'occupancy=empty', 'wall=1',
                          'mode=small&wall=1', f'flip={self.t1.pk}', 'chart=full&mode=big', f'board={board.pk}',
                          f'focus={self.t2.pk}&mode=small', f'focus={self.t1.pk}', 'q=nothing-matches'):
                with self.subTest(query=query):
                    full = self.client.get(f'{PAGE}?{query}&full=1' if query else f'{PAGE}?full=1')
                    self.assertEqual(full.status_code, 200)
                    self.assertNotIn('data-key="loading"', full.content.decode())
                    self.assertEqual(plain(self.spliced(query)), plain(full.content.decode()))
