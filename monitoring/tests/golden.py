"""The characterisation of the monitoring cards: a fixed farm of twenty units in every state a card can be in, and an
extractor that reads what a card SAYS out of its HTML (state, reasons, every labelled figure, every other text, every
title and the card's links), whatever the markup around it. The golden file (`golden_cards.json`) was recorded from the
cards as they were before card templates; the built-in templates Simple and Detailed must say the same, value for value.

A figure is a (label, value) pair: the text of a <dt> and of the first <dd> after it. The pairs must stay EQUAL; every
other text and title recorded must still be on the card (a template may add, e.g. a reading's origin and age, never take
away). What changes with the clock (dates, times, ages) and the database (ids, batch codes) is replaced by a stable mark
before the comparison, so the file does not age."""
import json
import os
import re
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl

from django.utils import formats

GOLDEN = Path(__file__).with_name('golden_cards.json')
# GOLDEN_WRITE=1 records the file again (only on the code the file characterises: never to make a test pass).
WRITE = os.environ.get('GOLDEN_WRITE') == '1'
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []

    @property
    def classes(self):
        return (self.attrs.get('class') or '').split()

    def text(self):
        return ''.join(child if isinstance(child, str) else child.text() for child in self.children)

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()


class Tree(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = self.current = Node('root', (), None)
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(Node(tag, attrs, self.current))

    def handle_endtag(self, tag):
        node = self.current
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.current = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


def squash(text):
    return ' '.join(text.replace('\xa0', ' ').split())


class Normaliser:
    """Replaces what the clock and the database decide with stable marks: unit ids by their codes, batch codes by
    their order, dates and times by their distance from today, ages by <age>."""

    def __init__(self, units, batches, today, others=()):
        self.pairs = [(str(unit.pk), unit.code) for unit in units] + [(str(key), mark) for key, mark in others]
        ordered = sorted(batches, key=lambda code: (-len(code), code))       # a longer code first: no prefix clash
        self.pairs += [(code, f'<batch-{number}>') for number, code in enumerate(ordered)]
        self.dates = []
        for offset in range(-400, 400):
            day = today + timedelta(days=offset)
            self.dates.append((formats.date_format(day, 'DATE_FORMAT'), f'<day{offset:+d}>'))
            self.dates.append((day.isoformat(), f'<iso{offset:+d}>'))
        self.dates.sort(key=lambda pair: len(pair[0]), reverse=True)
        # The SHORT day a fitted card prints (day.month: the withdrawal's first day of harvest, the day a value
        # arrived): within half a year of today it names one day. Only where a card prints one (after "harvest from",
        # before a time): a figure like 10.11 mg/L is never taken for a day.
        self.short = {f'{today + timedelta(days=offset):%d.%m}': f'<short{offset:+d}>' for offset in range(-180, 181)}

    def __call__(self, text):
        text = squash(text)
        for old, new in self.pairs:
            text = text.replace(old, new)
        text = re.sub(r'\b\d{1,2}:\d{2}\b', '<time>', text)
        text = re.sub(r'(?:(?<=harvest from )|(?<=harvest from about ))\d\d\.\d\d\b(?!\.\d)|\b\d\d\.\d\d(?= <time>)',
                      lambda found: self.short.get(found.group(0), found.group(0)), text)
        for old, new in self.dates:
            if old in text:
                text = text.replace(old, new)
        # A card's age band under an hour (render.age_text) depends on how long the test takes: one mark for all.
        text = re.sub(r'\b(just now|\d+ s ago|\d+ min ago)', '<recent>', text)
        return re.sub(r'\d+ (minute|hour|day|week|month|year)s?(, \d+ (minute|hour|day|week|month)s?)?', '<age>', text)


def link(url, norm):
    """An address, normalised: its ids by codes, and the lists of ids (`flip`, `units`, sorted by id in the address)
    sorted by code, so the comparison does not depend on the ids the database drew."""
    path, _, query = url.partition('?')
    pairs = []
    for name, value in parse_qsl(query, keep_blank_values=True):
        pairs.append((name, ','.join(sorted(norm(item) for item in value.split(','))) if ',' in value else norm(value)))
    return norm(path) + ('?' + '&'.join(f'{name}={value}' for name, value in pairs) if query else '')


def _leaves(node, skip):
    """The texts of a node's own runs (a text with no element between it and the node), outside the `skip` nodes."""
    for child in node.children:
        if isinstance(child, str):
            if child.strip():
                yield child
        elif child not in skip:
            yield from _leaves(child, skip)


def card_says(article, norm):
    """What one <article> says, normalised: {'state', 'reasons', 'pairs', 'texts', 'titles', 'links'}."""
    nodes = list(article.walk())
    state = next((norm(node.text()) for node in nodes if 'monitor-state-word' in node.classes), '')
    reasons = [norm(node.text()) for node in nodes
               if node.tag == 'li' and node.parent is not None and 'monitor-reasons' in node.parent.classes]
    pairs, taken = [], set()
    for node in nodes:
        if node.tag != 'dt':
            continue
        siblings = [child for child in node.parent.children if isinstance(child, Node)]
        after = siblings[siblings.index(node) + 1:]
        value = next((each for each in after if each.tag == 'dd'), None)
        pairs.append([norm(node.text()), norm(value.text()) if value is not None else ''])
        taken.add(node)
        if value is not None:
            taken.add(value)
    skip = taken | {node for node in nodes if 'monitor-state-word' in node.classes
                    or (node.tag == 'ul' and 'monitor-reasons' in node.classes)}
    texts = sorted(norm(text) for text in _leaves(article, skip) if norm(text))
    titles = sorted(norm(node.attrs['title']) for node in nodes if node.attrs.get('title'))
    links = {}
    for node in nodes:
        if 'monitor-flip' in node.classes:
            links['flip'] = [norm(node.text()), link(node.attrs.get('href', ''), norm),
                             link(node.attrs.get('data-poll-url', ''), norm)]
        if node.attrs.get('data-window'):
            links['chart'] = [link(node.attrs['data-window'], norm), norm(node.attrs.get('data-window-title', ''))]
        if node.tag == 'h3':
            anchor = next((each for each in node.walk() if each.tag == 'a'), None)
            if anchor is not None:
                links['unit'] = [norm(anchor.text()), link(anchor.attrs.get('href', ''), norm)]
    return {'state': state, 'reasons': reasons, 'pairs': sorted(pairs), 'texts': texts, 'titles': titles, 'links': links}


def cards_say(html, norm):
    """{unit code: what its card says} of a page or a fragment, in the page's order (the key is the article's)."""
    found = {}
    for node in Tree(html).root.walk():
        if node.tag == 'article' and node.attrs.get('data-key', '').startswith('card:'):
            found[norm(node.attrs['data-key'][len('card:'):])] = card_says(node, norm)
    return found


def _root(html, scope):
    """The node a page's facts are read from: the first element with the `scope` id or class, else <main>, else the
    whole document (a report of its own)."""
    nodes = list(Tree(html).root.walk())
    if scope:
        found = next((node for node in nodes if node.attrs.get('id') == scope or scope in node.classes), None)
        if found is not None:
            return found
    return next((node for node in nodes if node.tag == 'main'), nodes[0])


def page_says(html, norm, scope=''):
    """What a page SAYS, whatever its markup (the cards' rule, `card_says`, for a whole page or report): {'headings':
    the h1-h4 and captions, 'pairs': every (dt, dd) and every row's (th, td...) as label and values, 'texts': every
    other run of text, 'links': (text, address) of every link}, each sorted and normalised. A redesign of the page must
    still say every item (`multiset_missing` of the old in the new is empty); it may add. Scripts, styles, SVG text
    (a chart's geometry and its labels are compared by the chart's own tests) and hidden templates are left out."""
    root = _root(html, scope)
    skip = {node for node in root.walk() if node.tag in ('script', 'style', 'svg', 'template', 'noscript')}
    for node in list(skip):
        skip |= set(node.walk())
    nodes = [node for node in root.walk() if node not in skip]
    taken, pairs = set(skip), []
    headings = sorted(norm(node.text()) for node in nodes if node.tag in ('h1', 'h2', 'h3', 'h4', 'caption')
                      and norm(node.text()))
    taken |= {each for node in nodes if node.tag in ('h1', 'h2', 'h3', 'h4', 'caption') for each in node.walk()}
    for node in nodes:
        if node.tag == 'dt':
            siblings = [child for child in node.parent.children if isinstance(child, Node)]
            value = next((each for each in siblings[siblings.index(node) + 1:] if each.tag == 'dd'), None)
            pairs.append([norm(node.text()), norm(value.text()) if value is not None else ''])
            taken |= set(node.walk()) | (set(value.walk()) if value is not None else set())
        elif node.tag == 'tr':
            cells = [child for child in node.children if isinstance(child, Node) and child.tag in ('th', 'td')]
            if cells:
                pairs.append([norm(cell.text()) for cell in cells])
                taken |= {each for cell in cells for each in cell.walk()}
    texts = sorted(norm(text) for text in _leaves(root, taken) if norm(text))
    links = sorted([norm(node.text()), link(node.attrs['href'], norm)] for node in nodes
                   if node.tag == 'a' and node.attrs.get('href'))
    return {'headings': headings, 'pairs': sorted(pairs), 'texts': texts, 'links': links}


def says_missing(old, new):
    """{part: items} of what `old` (page_says) says that `new` does not: empty when the new page says it all."""
    return {part: missing for part in old if (missing := multiset_missing(old[part], new.get(part, [])))}


def multiset_missing(old, new):
    """The items of `old` that `new` does not have (as many times as `old` has them)."""
    left = list(new)
    missing = []
    for item in old:
        if item in left:
            left.remove(item)
        else:
            missing.append(item)
    return missing


def load():
    return json.loads(GOLDEN.read_text(encoding='utf-8')) if GOLDEN.exists() else {}


def save(data):
    GOLDEN.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
