"""What a page says, whatever its markup: the characterisation a new page (`?ui=next`) is held to against the old one.

A page's content is its <main>. What it says is every run of text in it (outside <script>, <style> and <template>), every
link's address and every form control's name: one item each, whitespace squashed. A new page draws its body from a JSON
payload in the browser, so the new page's server answer is checked through that payload: every item the old page says
must be a string of the payload, as many times as the old page says it, or (text longer than three characters, never a
bare figure) inside one (`unsaid`). Text the old page draws from several values in one element
("920 kg" then "1 lot") is two runs, so each is looked for on its own. An address must be carried exactly.

The comparison runs in one test on one fixture, the old page and the new one side by side, so nothing is recorded and
nothing ages: a page that drops a fact (a column, a warning, a count, a link) fails, a page that adds one does not."""
import json
from collections import Counter
from html.parser import HTMLParser

SILENT = {'script', 'style', 'template'}
VALUE_CELLS = {'td', 'dd', 'output'}      # cells that hold a value: one holding only "—" says "no value"
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}


def squash(text):
    return ' '.join(str(text).replace('\xa0', ' ').split())


class _Main(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth, self.silent, self.stack, self.items = 0, 0, [], []
        self.cells = []             # the words of the value cells open now (td, dd, output): [[text, …], …]

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'main':
            self.depth += 1
        if not self.depth:
            return
        if tag in SILENT:
            self.silent += 1
        if not self.silent:
            if tag == 'a' and attrs.get('href'):
                self.items.append(('href', attrs['href']))
            if tag in ('input', 'select', 'textarea', 'button') and attrs.get('name') \
                    and attrs.get('type') != 'hidden':
                self.items.append(('control', attrs['name']))
            for name in ('aria-label', 'title', 'placeholder'):
                if attrs.get(name):
                    self.items.append(('text', squash(attrs[name])))
        if tag in VALUE_CELLS:
            self.cells.append([])
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.depth:
            return
        if tag in SILENT and self.silent:
            self.silent -= 1
        if tag == 'main':
            self.depth -= 1
        if tag in VALUE_CELLS and self.cells:
            words = squash(''.join(self.cells.pop()))
            # A value cell that says only a mark ("—": no value, "–") says a fact: the mark is the value. Between words
            # the same mark is a separator (handle_data).
            if words and not any(char.isalnum() for char in words) and not self.silent:
                self.items.append(('text', words))
        while self.stack and self.stack.pop() != tag:
            pass

    def handle_data(self, data):
        # A run of only punctuation or symbols ("·" between two facts, "→" from an old value to a new one) is a separator,
        # layout and not a fact: the new page draws its own; a run with a letter or a digit is said. A value cell holding
        # nothing but such a mark is the exception (handle_endtag).
        for cell in self.cells:
            cell.append(data)
        if self.depth and not self.silent and any(char.isalnum() for char in data):
            self.items.append(('text', squash(data)))


def says(html):
    """[(kind, value)] of a page's <main>, in reading order: 'text' runs, 'href' addresses, 'control' names."""
    parser = _Main()
    parser.feed(html if isinstance(html, str) else html.decode())
    parser.close()
    return parser.items


def strings(payload):
    """Every string of a JSON payload (keys too), squashed."""
    found = []

    def walk(value):
        if isinstance(value, str):
            found.append(squash(value))
        elif isinstance(value, dict):
            for key, item in value.items():
                found.append(squash(key))
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
        elif value is not None and not isinstance(value, bool):
            found.append(str(value))
    walk(json.loads(payload) if isinstance(payload, (str, bytes)) else payload)
    return found


def unsaid(old_html, payload, ignore=(), new_html=None, once=()):
    """The items of the old page that the new page does not carry: [] when the new page can say all the old one said.
    The new page is its island's payload and, given `new_html`, what its own server-rendered <main> says around the island
    (the page head: its heading). `ignore` are texts the new page says by design in another way, each named with its
    reason by the caller's test. `once` are texts the old page repeats as layout (a form's tab label on its tab and again
    as its panel's heading) that the new page must say, once at least. A control's name is one control, however many
    boxes carry it (a group of boxes): it must be carried, not counted."""
    carried = strings(payload) + ([value for _kind, value in says(new_html)] if new_html is not None else [])
    left, present = Counter(carried), set(carried)
    missing = []
    for kind, value in says(old_html):
        if value in ignore:
            continue
        if (kind == 'control' or value in once) and value in present:
            continue
        if left[value] > 0:                     # a value of its own, as many times as the old page says it
            left[value] -= 1
            continue
        if kind == 'text' and len(value) > 3 and any(value in each for each in carried):
            continue                            # a run inside a longer sentence of the payload, never a bare figure
        missing.append((kind, value))
    return missing
