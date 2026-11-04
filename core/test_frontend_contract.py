"""The contract between the templates and the browser code that polls (frontend/poll.ts): the attributes a template may
put on an element are the ones the script documents and reads, Messages (appending rows) and the water calculator
(a live form) keep their hooks, `watch` is what other scripts import, and the compiled entry scripts are checked
when the server starts. The script's behaviour is checked in a browser (README, Browser code)."""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from . import checks

ROOT = Path(settings.BASE_DIR)
POLL = (ROOT / 'frontend' / 'poll.ts').read_text(encoding='utf-8')
HOOK = re.compile(r'\b(data-(?:poll[a-z-]*|live[a-z-]*|scroll-end|submit-on-enter))\b')


def templates():
    return sorted((ROOT / 'templates').rglob('*.html'))


def documented():
    """The attributes poll.ts documents in its header: a comment line that starts with one."""
    header = POLL[:POLL.index('const NEAR_END')]
    return set(re.findall(r'^//\s+`?(data-[a-z-]+)', header, flags=re.M))


def code():
    """poll.ts without its comments."""
    return '\n'.join(line.split('//')[0] for line in POLL.splitlines())


def camel(attribute):
    first, *rest = attribute.removeprefix('data-').split('-')
    return first + ''.join(word.capitalize() for word in rest)


class PollContractTests(SimpleTestCase):
    def test_every_hook_a_template_uses_is_one_the_script_documents(self):
        known = documented()
        self.assertTrue({'data-poll', 'data-poll-every', 'data-poll-append', 'data-poll-merge', 'data-poll-skip-same',
                         'data-poll-state', 'data-live', 'data-live-delay'} <= known)
        for path in templates():
            for hook in set(HOOK.findall(path.read_text(encoding='utf-8'))):
                # (data-live-part, data-live-errors, data-error-for belong to the live form's answer.)
                if hook in ('data-live-part', 'data-live-errors'):
                    continue
                with self.subTest(template=path.name, hook=hook):
                    self.assertIn(hook, known, f'{path.name} uses {hook}, which frontend/poll.ts does not document')

    def test_every_documented_hook_is_read_by_the_script(self):
        text = code()
        for hook in documented():
            with self.subTest(hook=hook):
                self.assertTrue(hook in text or f'.{camel(hook)}' in text or f"'{hook}'" in text,
                                f'{hook} is documented in poll.ts but nothing reads it')

    def test_messages_still_append_rows_and_follow_the_end(self):
        inbox = (ROOT / 'templates' / 'messaging' / 'inbox.html').read_text(encoding='utf-8')
        for hook in ('data-poll="{{ poll_url }}"', 'data-poll-every="{{ poll_messages }}"', 'data-poll-append',
                     'data-scroll-end', 'data-poll="{{ list_url }}"', 'data-poll-every="{{ poll_list }}"'):
            self.assertIn(hook, inbox)
        self.assertIn('insertAdjacentHTML(\'beforeend\'', code())            # append mode adds, never replaces
        self.assertIn("X-Poll-Next", code())

    def test_the_calculator_form_is_still_live(self):
        page = (ROOT / 'templates' / 'farm' / 'water_calculator.html').read_text(encoding='utf-8')
        self.assertIn('data-live="{{ results_url }}"', page)
        for name in ('live', 'swapParts', 'showErrors'):
            self.assertIn(f'function {name}(', code())
        self.assertIn('[data-live-part=', code())

    def test_the_menu_badge_is_still_a_plain_poll(self):
        shell = (ROOT / 'templates' / 'app_base.html').read_text(encoding='utf-8')
        self.assertIn('data-poll="{{ entry.badge.url }}" data-poll-every="30"', shell)
        self.assertNotIn('data-poll-merge', shell)

    def test_watch_is_exported_and_the_one_visibility_listener_is_shared(self):
        text = code()
        self.assertIn('export function watch(element: HTMLElement)', text)
        self.assertEqual(text.count("addEventListener('visibilitychange'"), 1)
        self.assertIn('isConnected', text)                                  # an element that left the page is let go
        for event in ('poll:now', 'poll:gone'):
            self.assertIn(event, text)
        self.assertIn('TIMEOUT = 20000', text)
        self.assertIn('SLOWEST = 60000', text)

    def test_the_compiled_entry_scripts_include_the_poll_script(self):
        self.assertIn('js/poll.js', checks.ENTRY_SCRIPTS)
        base = (ROOT / 'templates' / 'app_base.html').read_text(encoding='utf-8')
        self.assertIn("{% asset 'js/poll.js' %}", base)
