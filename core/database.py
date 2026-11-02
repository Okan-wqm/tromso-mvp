"""The database as the viewer shows it (Administration › Database): which tables there are, how they
are grouped, which columns are never shown, and what the database itself says about a table's
structure, matched with the model. The project's choices live in config/database.py.

Tables come from the models of the apps the project lists, so a tab that is ported later appears
without any new code; the tables of every other app (sessions, the Django admin's log) are not
shown. Nothing here writes."""
import inspect
import re
from dataclasses import dataclass, field

from django.apps import apps
from django.conf import settings
from django.db import connection
from django.db.models import Count, Q
from django.utils.module_loading import import_string
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _

PERMISSION = 'core.browse_database'


@dataclass(frozen=True)
class Section:
    label: str       # 'Facility' (as in the rail menu)
    apps: tuple      # the apps whose tables it holds


@dataclass(frozen=True)
class Viewer:
    sections: list
    excluded: tuple = ()                               # tables left out although their app is shown
    masked: dict = field(default_factory=dict)         # table -> columns never read, shown or exported
    descriptions: dict = field(default_factory=dict)   # table -> one line, where the docstring says it otherwise


def viewer():
    return import_string(settings.DATABASE_VIEWER)


@dataclass(frozen=True)
class Reference:
    """A foreign key as one table sees it. Outgoing (a column's `reference`): `column` of this table
    points at `other_column` of `table`. Incoming: `other_column` of `table` points at `column` of this
    one. `enforced` is false for a link the database does not check (db_constraint=False); `linked`
    when the other table is one the viewer shows."""
    column: str
    table: str
    other_column: str
    enforced: bool
    linked: bool


@dataclass(frozen=True)
class Column:
    name: str          # as the database spells it
    type: str          # 'varchar(150)'
    nullable: bool
    default: str       # the database's default, empty when it has none
    field: object      # the model's field; None when the model does not have the column
    masked: bool
    reference: Reference = None

    @property
    def primary_key(self):
        return self.field is not None and self.field.primary_key


@dataclass(frozen=True)
class Constraint:
    name: str
    kind: str          # 'Primary key', 'Unique', 'Foreign key', 'Check'
    definition: str    # as the database prints it: 'CHECK (capacity >= 0)'


@dataclass(frozen=True)
class Index:
    name: str
    unique: bool
    definition: str    # 'btree (code) WHERE (NOT is_deleted)'


@dataclass(frozen=True)
class Structure:
    columns: list
    constraints: list
    indexes: list
    referenced_by: list

    @property
    def references(self):
        return [column.reference for column in self.columns if column.reference]


@dataclass(frozen=True)
class Table:
    name: str          # the PostgreSQL table, 'site_contacts'
    model: type
    section: str
    description: str
    masked: frozenset  # column names

    @property
    def app(self):
        return self.model._meta.app_label

    @property
    def model_name(self):
        return self.model._meta.object_name

    @property
    def soft_deletable(self):
        return any(f.column == 'is_deleted' for f in self.model._meta.concrete_fields)

    def counts(self):
        """{'rows': n, 'deleted': n}, the soft-deleted rows counted among the rows; 'deleted' is None
        for a table that does not soft-delete."""
        counted = {'rows': Count('pk')}
        if self.soft_deletable:
            counted['deleted'] = Count('pk', filter=Q(is_deleted=True))
        counts = self.model._base_manager.aggregate(**counted)
        return {'deleted': None, **counts}

    def structure(self):
        """What the database says about the table, with each column matched to the model's field."""
        name = connection.ops.quote_name(self.name)
        with connection.cursor() as cursor:
            cursor.execute(COLUMNS_SQL, [name])
            described = cursor.fetchall()
            cursor.execute(CONSTRAINTS_SQL, [name])
            constraints = cursor.fetchall()
            cursor.execute(INDEXES_SQL, [name])
            indexes = cursor.fetchall()
        shown = {table.name for _, tables in sections() for table in tables}
        fields = {f.column: f for f in self.model._meta.concrete_fields}
        outgoing = {
            f.column: Reference(f.column, f.related_model._meta.db_table, f.target_field.column,
                                f.db_constraint, f.related_model._meta.db_table in shown)
            for f in fields.values() if f.is_relation
        }
        incoming = [
            Reference(f.target_field.column, other._meta.db_table, f.column, f.db_constraint,
                      other._meta.db_table in shown)
            for other in apps.get_models(include_auto_created=True)
            for f in other._meta.concrete_fields
            if f.is_relation and f.related_model is self.model
        ]
        return Structure(
            columns=[Column(column, short(sql_type), nullable, default or '', fields.get(column),
                            column in self.masked, outgoing.get(column))
                     for column, sql_type, nullable, default in described],
            constraints=[Constraint(constraint, CONSTRAINT_KINDS[kind], definition)
                         for constraint, kind, definition in constraints],
            indexes=[Index(index, unique, definition.partition(' USING ')[2])
                     for index, unique, definition in indexes],
            referenced_by=sorted(incoming, key=lambda r: (r.table, r.other_column)),
        )


# The database's own catalog, so what the Structure tab shows is what is really there and not what
# the models intend. The table name is a parameter, never part of the SQL text.
COLUMNS_SQL = """
SELECT a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull,
       CASE WHEN a.attidentity <> '' THEN 'identity' ELSE pg_get_expr(d.adbin, d.adrelid) END
FROM pg_attribute a
LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE a.attrelid = to_regclass(%s) AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY a.attnum
"""
CONSTRAINTS_SQL = """
SELECT conname, contype, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid = to_regclass(%s) AND contype <> 'n'
ORDER BY array_position(ARRAY['p', 'u', 'f', 'c', 'x'], contype::text), conname
"""
INDEXES_SQL = """
SELECT c.relname, i.indisunique, pg_get_indexdef(i.indexrelid)
FROM pg_index i
JOIN pg_class c ON c.oid = i.indexrelid
WHERE i.indrelid = to_regclass(%s)
ORDER BY i.indisprimary DESC, c.relname
"""
CONSTRAINT_KINDS = {'p': _('Primary key'), 'u': _('Unique'), 'f': _('Foreign key'), 'c': _('Check'), 'x': _('Exclusion')}
SHORT_TYPES = {
    'character varying': 'varchar', 'character': 'char', 'double precision': 'float8',
    'timestamp with time zone': 'timestamptz', 'timestamp without time zone': 'timestamp',
    'time with time zone': 'timetz', 'time without time zone': 'time',
}


def short(sql_type):
    """'character varying(150)' as 'varchar(150)'."""
    base, bracket, rest = sql_type.partition('(')
    return SHORT_TYPES.get(base.strip(), base.strip()) + bracket + rest


def describe(model, override=''):
    """One line for the overview: the configured text, else the first sentence of the model's
    docstring, else its name (Django gives a model without a docstring its own field list)."""
    if override:
        return override
    doc = inspect.getdoc(model) or ''
    if doc.startswith(f'{model.__name__}('):
        return capfirst(model._meta.verbose_name_plural)
    return ' '.join(re.split(r'(?<=\.)\s', doc, maxsplit=1)[0].split())


def sections():
    """[(section label, [Table, ...])] in the configured order, the tables of a section by name."""
    config = viewer()
    result = []
    for section in config.sections:
        models = [model for label in section.apps
                  for model in apps.get_app_config(label).get_models(include_auto_created=True)
                  if model._meta.managed and not model._meta.proxy and model._meta.db_table not in config.excluded]
        tables = [Table(model._meta.db_table, model, section.label,
                        describe(model, config.descriptions.get(model._meta.db_table, '')),
                        frozenset(config.masked.get(model._meta.db_table, ())))
                  for model in models]
        result.append((section.label, sorted(tables, key=lambda table: table.name)))
    return result


def find(name):
    """The table called `name` in the database, or None when the viewer does not show it."""
    return next((table for _, tables in sections() for table in tables if table.name == name), None)
