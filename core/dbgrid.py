"""One visit to a table in the database viewer: what the query string asks for (search, column
filters, sort, deleted rows, page), the rows that answer it, and how each value is shown.

Everything the query string names is checked against the table's real columns and anything else is
ignored, and the rows come through the ORM, never from SQL built out of the request. A masked column
is never read from the database: its cells hold a placeholder, it cannot be sorted or filtered (that
would reveal it) and the export leaves it out."""
import json
import uuid
from dataclasses import dataclass, field
from functools import cached_property, reduce
from operator import or_
from urllib.parse import urlencode

from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import models
from django.db.models import FETCH_PEERS, F, Q
from django.db.models.functions import Cast
from django.db.models.lookups import IContains
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

PAGE_SIZE = 100
EXPORT_LIMIT = 50_000
DELETED_MODES = [('show', _('Show deleted rows')), ('hide', _('Hide deleted rows')), ('only', _('Only deleted rows'))]
SHORT_TEXT = 80          # characters of a long value a cell shows; the rest opens on click
FULL_TEXT = 5_000        # characters of it the page carries; the export has everything
UUID_SHOWN = 8
BOOLEANS = {'true': True, 't': True, '1': True, 'false': False, 'f': False, '0': False}
FORMULA_STARTS = ('=', '+', '-', '@', '\t', '\r')


def formula_safe(text):
    """Text as a CSV cell may hold it: text a spreadsheet would run as a formula is marked with a leading
    apostrophe. For free text only: a number keeps its sign (a temperature of -0.4 °C stays a number)."""
    return f"'{text}" if text.startswith(FORMULA_STARTS) else text

# Numbers, identifiers, booleans and links are matched whole; everything else by the text it is stored as.
EXACT_FIELDS = (models.UUIDField, models.IntegerField, models.DecimalField, models.FloatField, models.BooleanField)
NUMERIC_FIELDS = (models.IntegerField, models.DecimalField, models.FloatField)


def holds(column):
    """The field that says what a column holds: a generated column's output field (a volume worked out
    by the database is a number), any other column's own field."""
    return column.field.output_field if column.field.generated else column.field


def is_numeric(column):
    return isinstance(holds(column), NUMERIC_FIELDS) and not column.field.is_relation


def is_exact(column):
    return column.field.is_relation or isinstance(holds(column), EXACT_FIELDS)


def match(column, term):
    """The condition "this column matches `term`": the whole value for numbers, identifiers, booleans
    and links (None when `term` cannot be one, e.g. letters in a number), contained text for the rest."""
    field = column.field
    if isinstance(field, models.BooleanField):
        value = BOOLEANS.get(term.lower())
        return None if value is None else Q(**{field.attname: value})
    if is_exact(column):
        try:
            value = (field.target_field if field.is_relation else holds(column)).clean(term, None)
        except ValidationError:
            return None
        return Q(**{field.attname: value})
    return Q(IContains(Cast(field.attname, models.TextField()), term))


def select(column):
    """What the grid reads: the stored value; timestamps and arrays ({feed,equipment}) as the database
    prints them, which is the text a filter matches."""
    name = column.field.attname
    return Cast(name, models.TextField()) if isinstance(column.field, (models.DateTimeField, ArrayField)) else name


def raw(column, value):
    """A value as it is stored, as text: not localised, JSON on one line."""
    if isinstance(column.field, models.JSONField):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def shorten(value, text):
    return f'{text[:UUID_SHOWN]}…' if isinstance(value, uuid.UUID) else text


@dataclass(frozen=True)
class Cell:
    kind: str          # null, masked, bool, number, uuid, text, long, fk
    text: str = ''     # what the cell shows
    full: str = ''     # the whole value: the hover text of a shortened one, the body of a long one
    label: str = ''    # a link cell's record; None when no such record exists
    href: str = ''     # where a link cell goes


@dataclass(frozen=True)
class Header:
    column: object
    numeric: bool
    exact: bool        # the filter matches the whole value rather than text contained in it
    sort_href: str     # empty for a masked column
    direction: str     # 'ascending' or 'descending' for the column the rows are sorted by, else ''
    filter_param: str  # the query parameter of the column's filter; empty for a masked column
    filter_value: str


@dataclass(frozen=True)
class Row:
    number: int
    deleted: bool
    cells: list = field(default_factory=list)


def clean(value):
    return value.replace('\0', '').strip()   # PostgreSQL text cannot hold NUL


class Grid:
    """The columns, the filtered and sorted rows, and the links of one table view."""

    def __init__(self, table, structure, params):
        self.table = table
        self.columns = [column for column in structure.columns if column.field is not None]
        self.readable = [column for column in self.columns if not column.masked]
        self.by_name = {column.name: column for column in self.readable}

        self.search = clean(params.get('q', ''))
        self.deleted = params.get('deleted') if table.soft_deletable and params.get('deleted') in dict(DELETED_MODES) else 'show'
        self.filters = {name: term for name in self.by_name if (term := clean(params.get(f'f_{name}', '')))}
        sort = self.by_name.get(params.get('sort'))
        descending = params.get('dir') == 'desc'
        self.order = [(sort, descending)] if sort else self.default_order()
        self.params = {
            'q': self.search, 'deleted': '' if self.deleted == 'show' else self.deleted,
            **{f'f_{name}': term for name, term in self.filters.items()},
            'sort': sort.name if sort else '', 'dir': 'desc' if sort and descending else '',
        }
        self.page_number = max(int(params['page']), 1) if params.get('page', '').isdecimal() else 1

    def default_order(self):
        """The model's own ordering, where it names columns the viewer can sort by."""
        by_field = {column.field.name: column for column in self.by_name.values()}
        return [(by_field[item.lstrip('-')], item.startswith('-'))
                for item in self.table.model._meta.ordering
                if isinstance(item, str) and item.lstrip('-') in by_field]

    # --- the rows -----------------------------------------------------------------------------
    def queryset(self):
        rows = self.table.model._base_manager.all()   # soft-deleted rows included: this is the database
        if self.deleted != 'show':
            rows = rows.filter(is_deleted=self.deleted == 'only')
        for name, term in self.filters.items():
            condition = match(self.by_name[name], term)
            rows = rows.none() if condition is None else rows.filter(condition)
        if self.search:
            conditions = [condition for column in self.readable if (condition := match(column, self.search))]
            rows = rows.filter(reduce(or_, conditions)) if conditions else rows.none()
        order = [F(column.field.attname).desc(nulls_last=True) if descending else F(column.field.attname).asc(nulls_last=True)
                 for column, descending in self.order]
        return rows.order_by(*order, 'pk').values_list(*[select(column) for column in self.readable])

    @cached_property
    def page(self):
        return Paginator(self.queryset(), PAGE_SIZE).get_page(self.page_number)

    @cached_property
    def rows(self):
        values = list(self.page.object_list)
        labels = {column.name: self.labels(column, [row[i] for row in values])
                  for i, column in enumerate(self.readable) if column.reference}
        deleted = next((i for i, column in enumerate(self.readable) if column.name == 'is_deleted'), None)
        return [Row(number, deleted is not None and row[deleted], self.cells(row, labels))
                for number, row in enumerate(values, self.page.start_index())]

    def cells(self, row, labels):
        values = iter(row)
        return [Cell('masked') if column.masked else self.cell(column, next(values), labels.get(column.name))
                for column in self.columns]

    @staticmethod
    def labels(column, values):
        """{stored value: the record's name} for the records a link column points at."""
        target = column.field.target_field
        # A record's name may read its own links (any model's __str__): fetched once for the whole page (FETCH_PEERS),
        # where select_related() without fields, deprecated in Django 6.1, joined every non-null link up front.
        records = column.field.related_model._base_manager.filter(
            **{f'{target.attname}__in': {value for value in values if value is not None}}).fetch_mode(FETCH_PEERS)
        return {getattr(record, target.attname): str(record) for record in records}

    @staticmethod
    def cell(column, value, labels):
        if value is None:
            return Cell('null')
        text = raw(column, value)
        if column.reference:
            reference = column.reference
            href = ''
            if reference.linked:
                query = urlencode({f'f_{reference.other_column}': text})
                href = f'{reverse("core:database_table", args=[reference.table])}?{query}'
            return Cell('fk', shorten(value, text), text, labels.get(value), href)
        if isinstance(column.field, models.BooleanField):
            return Cell('bool', text)
        if isinstance(value, uuid.UUID):
            return Cell('uuid', shorten(value, text), text)
        if len(text) > SHORT_TEXT or '\n' in text:
            full = json.dumps(value, ensure_ascii=False, indent=2) if isinstance(column.field, models.JSONField) else text
            return Cell('long', ' '.join(text.split())[:SHORT_TEXT] + '…', full[:FULL_TEXT])
        return Cell('number' if is_numeric(column) else 'text', text)

    # --- the page's controls ----------------------------------------------------------------------
    def href(self, route, **changes):
        """The address of this view (or of its export) with `changes` applied to the query."""
        query = urlencode({key: value for key, value in {**self.params, **changes}.items() if value})
        return f'{reverse(route, args=[self.table.name])}{"?" if query else ""}{query}'

    @cached_property
    def headers(self):
        primary, descending = self.order[0] if self.order else (None, False)
        return [
            Header(
                column, is_numeric(column), is_exact(column),
                '' if column.masked else self.href(
                    'core:database_table', sort=column.name, dir='desc' if primary is column and not descending else ''),
                ('descending' if descending else 'ascending') if primary is column else '',
                '' if column.masked else f'f_{column.name}', self.filters.get(column.name, ''),
            )
            for column in self.columns
        ]

    @property
    def custom(self):
        """Whether the view differs from the table's plain one: a search, a filter, a sort or deleted rows."""
        return any(self.params.values())

    @property
    def export_href(self):
        return self.href('core:database_export')

    @cached_property
    def pager(self):
        page, last = self.page, self.page.paginator.num_pages
        link = lambda number: self.href('core:database_table', page=number if number > 1 else '')
        return {
            'first': link(1) if page.has_previous() else '',
            'previous': link(page.previous_page_number()) if page.has_previous() else '',
            'next': link(page.next_page_number()) if page.has_next() else '',
            'last': link(last) if page.has_next() else '',
        }

    # --- the export -----------------------------------------------------------------------------
    def export(self):
        """The header and then the rows of the current filter, as lists of text; masked columns left out."""
        yield [column.name for column in self.readable]
        for values in self.queryset()[:EXPORT_LIMIT].iterator():
            yield [self.export_text(column, value) for column, value in zip(self.readable, values)]

    @staticmethod
    def export_text(column, value):
        """Empty for NULL. Text a spreadsheet would run as a formula is marked with a leading apostrophe."""
        if value is None:
            return ''
        text = raw(column, value)
        if isinstance(column.field, (models.CharField, models.TextField)):
            return formula_safe(text)
        return text
