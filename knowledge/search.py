"""Full-text search of the library and the knowledge entries (PostgreSQL).

**Stored side.** Every searchable text is a tsvector in a generated column, analysed with the `simple`
configuration (knowledge.models.common.SEARCH_CONFIG): lower case, every word as written, whatever the language,
so a Norwegian report with an English abstract is indexed as well as an English article. A document's own
vector holds its title (weight A), authors (B), abstract (C) and venue (D); the text of its PDF is a vector per
page (DocumentPage, D), so a page's text never meets PostgreSQL's 1 MB limit of one tsvector and a hit says
which page it is on. A knowledge entry's vector holds its statement (A), quote (B), section and citation (C)
and person (D). Each vector has a GIN index.

**Query side.** What a person types is split into words; each word is analysed with the English, Norwegian and
Turkish stemmers and with `simple`, and each stem is a prefix (`'diseas':*`), so "diseases" finds "disease"
and "diseased", "fiskene" finds "fisk" and "fiskehelse", "balıklarda" finds "balık". A word matches when any
of its four analyses does. Every word must match the record: a document when each word is in its own vector
or on one of its pages (they may be on different ones: "Olsen CO2" finds Olsen's article that speaks of CO₂);
an entry when each word is in its vector or in the vector of the document it cites. Stems shorter than three
letters and numbers match whole ("pH" is not "phosphorus", "15" is not "150").

**Ranking.** ts_rank of the record's own vector against any of the words (a title hit counts most, by the
weights above), plus the best page's rank for a document, or the cited document's rank for an entry; then the
list's own order.

The query is built from the stems as tsquery text with every lexeme quoted, so nothing a person types is ever
read as tsquery syntax.
"""
import unicodedata
from dataclasses import dataclass

from django.contrib.postgres.search import SearchConfig, SearchQueryField
from django.db import connection
from django.db.models import BooleanField, Exists, F, FloatField, Func, OuterRef, Q, Subquery, TextField, Value
from django.db.models.functions import Coalesce
from django.utils.html import escape
from django.utils.safestring import mark_safe

from .models import DocumentPage
from .models.common import SEARCH_CONFIG

QUERY_CONFIGS = ('english', 'norwegian', 'turkish', 'simple')
MAX_WORDS = 12
PREFIX_MIN = 3
# The highlight markers of a headline: control characters, which a stored text never holds (knowledge.extraction).
START, STOP = '\x02', '\x03'
HEADLINE_OPTIONS = f'StartSel={START}, StopSel={STOP}, MaxWords=30, MinWords=12, MaxFragments=2, FragmentDelimiter=" … "'


class TSQuery(Func):
    """A tsquery written in PostgreSQL's tsquery syntax, its lexemes taken as written (not analysed again)."""
    template = '%(expressions)s::tsquery'
    output_field = SearchQueryField()


class Matches(Func):
    """vector @@ query."""
    arg_joiner = ' @@ '
    template = '(%(expressions)s)'
    output_field = BooleanField()


class Rank(Func):
    function = 'ts_rank'
    output_field = FloatField()


class Headline(Func):
    """The best passages of a text for a query, the matched words between START and STOP."""
    function = 'ts_headline'
    output_field = TextField()

    def __init__(self, text, query):
        super().__init__(SearchConfig(SEARCH_CONFIG), text, query, Value(HEADLINE_OPTIONS))


@dataclass(frozen=True)
class Query:
    words: tuple      # one tsquery per word typed

    @property
    def every(self):
        """Every word (the records that match)."""
        return TSQuery(Value(' & '.join(self.words)))

    @property
    def any(self):
        """Any word (how well a record matches)."""
        return TSQuery(Value(' | '.join(self.words)))

    def each(self):
        return [TSQuery(Value(word)) for word in self.words]


def words(text):
    """The words typed, normalised as stored texts are (NFKC), each once, at most MAX_WORDS."""
    return list(dict.fromkeys(unicodedata.normalize('NFKC', text or '').split()))[:MAX_WORDS]


def lexeme(text):
    """A stem as a tsquery operand: quoted (so nothing in it is syntax), a prefix when it is a word of at least
    PREFIX_MIN characters."""
    quoted = "'" + text.replace('\\', '\\\\').replace("'", "''") + "'"
    return quoted + ':*' if len(text) >= PREFIX_MIN and any(ch.isalpha() for ch in text) else quoted


def parse(text):
    """The Query for what was typed, or None when no word of it can be searched (only punctuation)."""
    typed = words(text)
    if not typed:
        return None
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT w.n, c.cfg, tsvector_to_array(to_tsvector(c.cfg::regconfig, w.word)) '
            'FROM unnest(%s::text[]) WITH ORDINALITY AS w(word, n) CROSS JOIN unnest(%s::text[]) AS c(cfg)',
            [typed, list(QUERY_CONFIGS)])
        analysed = cursor.fetchall()
    readings = {}
    for number, _config, stems in analysed:
        if stems:
            readings.setdefault(number, set()).add(tuple(sorted(stems)))
    queries = []
    for number in sorted(readings):
        alternatives = sorted(readings[number])
        queries.append('(' + ' | '.join('(' + ' & '.join(lexeme(stem) for stem in stems) + ')'
                                        for stems in alternatives) + ')')
    return Query(tuple(queries)) if queries else None


def search_documents(documents, text):
    """The documents that match `text`, best first, each with `rank`, `hit_page` (the number of its best matching
    page, None when none) and `hit_text` (that page's passages, START/STOP around the words)."""
    query = parse(text)
    if query is None:
        return documents.none()
    pages = DocumentPage.objects.filter(document=OuterRef('pk'))
    for word in query.each():
        documents = documents.filter(Q(Matches(F('search_vector'), word))
                                     | Q(Exists(pages.filter(Matches(F('search_vector'), word)))))
    best = (pages.filter(Matches(F('search_vector'), query.any))
            .annotate(page_rank=Rank(F('search_vector'), query.any)).order_by('-page_rank', 'number'))
    return documents.annotate(
        rank=Rank(F('search_vector'), query.any) + Coalesce(Subquery(best.values('page_rank')[:1]), Value(0.0)),
        hit_page=Subquery(best.values('number')[:1]),
        hit_label=Subquery(best.values('label')[:1]),
        hit_text=Subquery(best.annotate(passage=Headline(F('text'), query.any)).values('passage')[:1]),
    ).order_by('-rank', *documents.model._meta.ordering)


def matching_pages(document, text, limit=10):
    """The pages of `document` that hold any word of `text`, best first, each with its passages (`passage`)."""
    query = parse(text)
    if query is None:
        return []
    return list(document.pages.filter(Matches(F('search_vector'), query.any))
                .annotate(page_rank=Rank(F('search_vector'), query.any), passage=Headline(F('text'), query.any))
                .order_by('-page_rank', 'number')[:limit])


def search_entries(entries, text):
    """The knowledge entries that match `text`, best first (`rank`): each word in the entry or in the document
    it cites."""
    query = parse(text)
    if query is None:
        return entries.none()
    for word in query.each():
        entries = entries.filter(Q(Matches(F('search_vector'), word))
                                 | Q(Matches(F('document__search_vector'), word)))
    return entries.annotate(
        rank=Rank(F('search_vector'), query.any)
        + Coalesce(Rank(F('document__search_vector'), query.any), Value(0.0)),
    ).order_by('-rank', *entries.model._meta.ordering)


def highlight(passage):
    """A headline as HTML: the text escaped, the matched words in <mark>."""
    if not passage:
        return ''
    return mark_safe(escape(passage).replace(START, '<mark>').replace(STOP, '</mark>'))
