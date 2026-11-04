"""The data map: for every table of the project, which screen fills, changes, deletes and shows it, derived from
the code and checked by a test (`core.test_datamap.DataMapTests`), written to docs/data-map.md and docs/data-map.json by
`manage.py data_map` (`--check` fails when the committed files are stale).

What the code already says is read from it, never written down again:
- the tables, their columns, links (and what each link's `on_delete` does), constraints: the models;
- a tab (core.crud.Resource): its create, edit and delete pages, its list and read pages, its row lists (a site's
  contacts), the form each field is on and the inner tab it sits on, the delete plan and the restore in the admin;
- a many-to-many link: the field of the parent's form;
- the database viewer entry (config/database.py), the description of a table (the viewer's, shown here too),
  the routes (the URL configuration) and the tests that mention the model.

What it cannot say is declared once, next to the app that owns the table, in `<app>/screens.py`: a `SCREENS`
dict from a model's name to a `Screen`. Only a table that is not a tab (a record a dialog writes through a
service, a row a parent owns, a table the code fills) needs one, and it names the views: the dialog that writes it
and the pages that show it. A view is named by the function itself, so a renamed or unrouted view fails to import
or here. What is missing on purpose is said with `no(why)`; what is missing and should not be is said with
`gap(why)`, which is reported (docs/data-map.md, Gaps) and not forgotten. A column no form covers is said once in
`Screen.columns`: `computed`, `system`, `dynamic` or `gap`.

The rules the test enforces are `problems()`; a new app is picked up from INSTALLED_APPS, and its tables fail the
test until its `screens.py` declares them, with a message that names the model and where to declare it."""
import json
import re
import sys
from functools import cache
from dataclasses import dataclass, field
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path

from django import forms
from django.apps import apps
from django.conf import settings
from django.contrib import admin
from django.contrib.postgres.constraints import ExclusionConstraint
from django.db import connection, models
from django.urls import URLResolver, get_resolver
from django.utils import translation

from . import database
from .crud import ENTRY_KEY, Resource, constrained_fields
from .models import AuditedModel

CAPABILITIES = ('create', 'edit', 'delete', 'read')
DOCS = Path(settings.BASE_DIR) / 'docs'
MARKDOWN, JSON = DOCS / 'data-map.md', DOCS / 'data-map.json'
# How much a missing path weighs in the Gaps ranking: nobody can fill it, nobody can read it, ...
# In Screen.columns: the reason for every column that no form covers and nothing else says (a table the code writes).
ALL = '*'
WEIGHT = {'create': 4, 'edit': 3, 'read': 3, 'delete': 2, 'restore': 1, 'column': 1}


@dataclass(frozen=True)
class Reason:
    """A declared fact that is not a page. For a path (`Screen.create` and the others): `none` is missing on purpose,
    `gap` is missing and should not be. For a column (`Screen.columns`): `computed` is filled by the code from other
    data, `system` by the system as part of the work, `gap` is a column a person should fill and no form has."""
    kind: str
    why: str


def no(why):
    """No path on purpose: say why (a ledger is never edited, a void is its undo)."""
    return Reason('none', why)


def gap(why):
    """No path, and there should be one: a product gap, listed in docs/data-map.md."""
    return Reason('gap', why)


def computed(why):
    """A column the code fills from other data."""
    return Reason('computed', why)


def dynamic(why):
    """A column a form fills with fields it makes per record (the specifications of an equipment type, a water
    sample's parameters), so no field of the form carries its name."""
    return Reason('dynamic', why)


def system(why):
    """A column the system sets as part of the work (who, when, which parent)."""
    return Reason('system', why)


@dataclass(frozen=True)
class Screen:
    """What the code cannot say about a table that is not a tab. `create`, `edit`, `delete` and `read` are each the
    views (functions) that do it, or a `no`/`gap` reason; a tab, a row list and a many-to-many link have theirs from
    the code, and what is declared is added to them.

    part_of   'farm.StockOperation': written with that record, so its create, edit and delete are that record's
    forms     form classes that are not model forms of this table but fill its columns by the same name (a dialog's
              form: the service writes the row), and the model forms the table's own tab does not use
    fills     form field -> the column or columns it fills, where the names differ (a count typed in a dialog is the
              ledger line's `count_delta`; an amount and a unit are stored as hours)
    columns   column -> computed / system / dynamic / gap, for a column no form covers; '*' for all the rest
    extra_fields   a form field that is not a column and fills none -> why (a form's token, a choice that only
              narrows another)
    restore   for a record that is deleted softly and that the admin does not restore: `no(why)` (the admin restores
              the records of a tab; a voided record is entered again, a left member added again)
    note      one line on how it works that the paths do not say (voiding a stocking voids its batch)"""
    create: object = ()
    edit: object = ()
    delete: object = ()
    read: object = ()
    part_of: str = ''
    forms: tuple = ()
    fills: dict = field(default_factory=dict)
    columns: dict = field(default_factory=dict)
    extra_fields: dict = field(default_factory=dict)
    restore: object = None
    note: str = ''


# --- what the code says --------------------------------------------------------------------------------------

@cache
def project_apps():
    """The apps that are the project's own: the ones whose code lives under the project directory and not
    in the Python environment (a virtual environment kept inside the project, as on a developer's machine,
    holds Django's own apps under the project directory too)."""
    root = Path(settings.BASE_DIR).resolve()
    environment = Path(sys.prefix).resolve()
    return [config for config in apps.get_app_configs()
            if root in Path(config.path).resolve().parents and environment not in Path(config.path).resolve().parents]


@cache
def project_models():
    """Every concrete model of the project's apps, the tables Django makes for a many-to-many link included."""
    result = []
    for config in project_apps():
        result.extend(model for model in config.get_models(include_auto_created=True)
                      if model._meta.managed and not model._meta.proxy)
    return result


def framework_models():
    own = set(project_models())
    return [model for model in apps.get_models(include_auto_created=True)
            if model not in own and model._meta.managed and not model._meta.proxy]


def declarations():
    """{model: Screen} from every project app's screens.py (SCREENS: model name -> Screen)."""
    found = {}
    for config in project_apps():
        if find_spec(f'{config.name}.screens') is None:
            continue
        for name, screen in getattr(import_module(f'{config.name}.screens'), 'SCREENS', {}).items():
            found[f'{config.label}.{name}'] = screen
    return found


def unwrapped(view):
    while hasattr(view, '__wrapped__'):
        view = view.__wrapped__
    return view


@dataclass
class Routes:
    by_name: dict = field(default_factory=dict)      # 'farm:site_list' -> 'sites/'
    by_view: dict = field(default_factory=dict)      # view function -> ['farm:stock_mortality', ...]


def routes():
    """The URL configuration as names and routes, and the names each view function answers to."""
    result = Routes()

    def walk(patterns, prefix, namespace):
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                walk(pattern.url_patterns, prefix + str(pattern.pattern),
                     namespace + (f'{pattern.namespace}:' if pattern.namespace else ''))
            elif pattern.name:
                name = namespace + pattern.name
                result.by_name[name] = '/' + prefix + str(pattern.pattern)
                result.by_view.setdefault(unwrapped(pattern.callback), []).append(name)

    walk(get_resolver().url_patterns, '', '')
    return result


def tabs_of(model):
    return [tab for tab in Resource.registry if tab.model is model]


def model_forms(model):
    """The model forms of a table found in the code: a tab's form, the forms of its row lists, and any other model
    form of it (a dialog's)."""
    found = {}
    for form in all_model_forms():
        if getattr(getattr(form, 'Meta', None), 'model', None) is model:
            found[form] = None
    for tab in tabs_of(model):
        found[tab.form_class] = None
    for tab in Resource.registry:
        for rows in tab.row_lists:
            if rows.formset.model is model:
                found[rows.formset.form] = None
    return sorted(found, key=lambda form: (form.__module__, form.__qualname__))


def link_lists(model):
    """[(form, field name, field)] of the link lists (core.links.LinkList) that save rows of this table with their
    parent's form."""
    from .links import LinkList
    return [(form, name, item) for form in all_model_forms() for name, item in form.base_fields.items()
            if isinstance(item, LinkList) and item.through is model]


def m2m_links(model):
    """[(parent model, many-to-many field)] whose rows this table holds: the link table Django makes, or a `through`
    model; the parent's form saves them with the field."""
    return [(parent, link) for parent in project_models() for link in parent._meta.many_to_many
            if link.remote_field.through is model]


def all_subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from all_subclasses(sub)


def all_model_forms():
    return sorted(all_subclasses(forms.ModelForm), key=lambda form: (form.__module__, form.__qualname__))


def form_fields(form):
    """{field name: inner tab label} of a form; '' for a form without inner tabs."""
    from .crud import tab_fields
    tabs = {}
    for key, label, names in getattr(form, 'tabs', []):
        for name in tab_fields([(key, label, names)]):
            tabs.setdefault(name, str(label))
    return {name: tabs.get(name, '') for name in form.base_fields}


AUDIT_COLUMNS = {f.name for f in AuditedModel._meta.fields}


def system_reason(model, column, parents):
    """Why a column is not on a form because the system owns it, from the column itself; '' when it is a column
    people fill."""
    if column.primary_key:
        return 'primary key'
    if column.name in AUDIT_COLUMNS:
        return 'author, time, version or delete mark'
    if column.name in parents:
        return f'the {column.related_model._meta.verbose_name} the row belongs to'
    if getattr(column, 'auto_now', False) or getattr(column, 'auto_now_add', False):
        return 'set when saved'
    if not column.editable:
        return 'not editable: set by the code'
    if isinstance(column, models.GeneratedField):
        return 'generated by the database'
    return ''


def column_type(column):
    return column.db_type(connection) or column.get_internal_type()


def constraints_of(model):
    result = []
    for constraint in model._meta.constraints:
        if isinstance(constraint, models.UniqueConstraint):
            kind, fields = 'unique', constrained_fields(constraint)
        elif isinstance(constraint, ExclusionConstraint):
            kind, fields = 'exclusion', constrained_fields(constraint)
        else:
            kind, fields = 'check', []
        result.append({'name': constraint.name, 'kind': kind, 'fields': fields,
                       'conditional': getattr(constraint, 'condition', None) is not None and kind != 'check'})
    for names in model._meta.unique_together:
        result.append({'name': 'unique together', 'kind': 'unique', 'fields': list(names), 'conditional': False})
    return result


@cache
def test_modules():
    """{relative path: the words in it} of every test module of the project's apps."""
    root = Path(settings.BASE_DIR).resolve()
    found = {}
    for config in project_apps():
        for path in sorted(Path(config.path).rglob('*.py')):
            parts = path.relative_to(config.path).parts
            if 'migrations' in parts or not (path.name.startswith('test') or 'tests' in parts[:-1]):
                continue
            found[path.relative_to(root).as_posix()] = frozenset(re.findall(r'\w+', path.read_text(encoding='utf-8')))
    return found


def descriptions():
    config = database.viewer()
    return {model: str(database.describe(model, str(config.descriptions.get(model._meta.db_table, ''))))
            for model in project_models()}


# --- the map ----------------------------------------------------------------------------------------------------

class Map:
    """Everything the generator and the test need, built once from the code."""

    def __init__(self):
        self.routes = routes()
        self.screens = declarations()
        self.problems = []
        self.resolved = {}
        self.test_modules = test_modules()
        self.viewer = {table.name: (str(table.section), sorted(table.masked))
                       for _, tables in database.sections() for table in tables}
        self.models = {model._meta.label: model for model in project_models()}
        self.tables = {}
        for label in sorted(self.models, key=lambda label: (self.models[label]._meta.app_label,
                                                            self.models[label]._meta.db_table)):
            self.tables[label] = self.table(self.models[label])
        for label in self.screens:
            if label not in self.models:
                app = label.partition('.')[0]
                self.problems.append(
                    f'{app}/screens.py declares {label}, which is not a table of the project: remove it, or fix '
                    f'the model name.')

    # -- paths ---------------------------------------------------------------------------------------------------
    def view_paths(self, label, capability, views):
        """The paths of declared views, a view being a function (a route answers to it) or a tab (a Resource class);
        a view that no route answers to is a problem."""
        paths = []
        for view in views:
            if isinstance(view, type) and issubclass(view, Resource):
                paths.append(self.tab_path(view, capability))
                continue
            if isinstance(view, str):
                if view not in self.routes.by_name:
                    self.problems.append(f'{label}: the {capability} URL name {view!r} is not routed.')
                else:
                    paths.append(self.url_paths('view', view, [view]))
                continue
            names = self.routes.by_view.get(unwrapped(view))
            if not names:
                self.problems.append(
                    f'{label}: the {capability} view {getattr(view, "__module__", "?")}.'
                    f'{getattr(view, "__qualname__", view)} has no route: add it to the app urls.py or declare '
                    f'another view in screens.py.')
                continue
            paths.append({'how': 'view', 'label': f'{view.__module__}.{view.__qualname__}', 'url_names': sorted(names),
                          'routes': [self.routes.by_name[name] for name in sorted(names)]})
        return paths

    def tab_path(self, tab, capability):
        """A tab as the place where something is done: its pages for the capability (read: its list, its read page
        and its form, which shows the record)."""
        names = {'create': ['create'], 'edit': ['edit'], 'delete': ['delete'], 'read': ['list', 'detail', 'edit']}
        urls = [tab.url_name(action) for action in names[capability]
                if action != 'detail' or tab.detail_template]
        return self.url_paths('tab', f'{tab.plural} tab', urls)

    def url_paths(self, how, label, names):
        return {'how': how, 'label': label, 'url_names': names, 'routes': [self.routes.by_name.get(n, '') for n in names]}

    def derived(self, model):
        """{capability: [paths]} the code gives a table: its tabs, the row lists that rows belong to, the field of
        a many-to-many link on the parent's form."""
        paths = {capability: [] for capability in CAPABILITIES}
        for tab in tabs_of(model):
            name = str(tab.plural)
            if tab.allows('add'):
                paths['create'].append(self.url_paths('tab', f'{name} tab', [tab.url_name('create')]))
            if tab.allows('change'):
                paths['edit'].append(self.url_paths('tab', f'{name} tab', [tab.url_name('edit')]))
            if tab.allows('delete'):
                paths['delete'].append(self.url_paths('tab', f'{name} tab', [tab.url_name('delete')]))
            read = [tab.url_name('list')] + ([tab.url_name('detail')] if tab.detail_template else [])
            paths['read'].append(self.url_paths('tab', f'{name} tab', read))
        for tab in Resource.registry:
            for rows in tab.row_lists:
                if rows.formset.model is not model or not tab.allows('change'):
                    continue
                label = f'{rows.label} list on the {tab.plural} tab'
                saved = self.url_paths('rowlist', label, [tab.url_name(rows.key)])
                for capability in ('create', 'edit', 'delete'):
                    paths[capability].append(saved)
                paths['read'].append(self.url_paths('rowlist', label, [tab.url_name('edit')]))
        for parent, link in m2m_links(model):
            for form in self.forms_with(parent, link.name):
                label = f'field {link.name} of {form.__name__}'
                tabs = [tab for tab in tabs_of(parent) if tab.form_class is form]
                for tab in tabs:
                    for capability, allowed in (('create', 'add'), ('edit', 'change'), ('delete', 'change'),
                                                ('read', 'view')):
                        if tab.allows(allowed):
                            path = self.tab_path(tab, 'edit' if capability == 'delete' else capability)
                            paths[capability].append({**path, 'how': 'm2m', 'label': f'{label}: {path["label"]}'})
                if not tabs:
                    # A dialog's form: the link is made when the dialog records the parent; what changes or shows
                    # it afterwards is not in the code.
                    for path in self.resolve(parent._meta.label)['paths']['create']:
                        paths['create'].append({**path, 'how': 'm2m', 'label': f'{label}: {path["label"]}'})
        return paths

    def forms_with(self, model, name):
        return [form for form in self.all_forms(model) if name in form.base_fields]

    def all_forms(self, model):
        screen = self.screens.get(model._meta.label)
        declared = list(screen.forms) if screen else []
        return model_forms(model) + [form for form in declared if form not in model_forms(model)]

    def resolve(self, label, seen=()):
        """The paths of a table for each capability, with the declaration added to what the code says."""
        if label in self.resolved:
            return self.resolved[label]
        model = self.models[label]
        screen = self.screens.get(label, Screen())
        paths = self.derived(model)
        verdicts = {}
        parent = self.models.get(screen.part_of) if screen.part_of else None
        if screen.part_of and parent is None:
            self.problems.append(f'{label}: part_of {screen.part_of} is not a table of the project.')
        for capability in CAPABILITIES:
            declared = getattr(screen, capability)
            if isinstance(declared, Reason):
                verdicts[capability] = declared
            else:
                paths[capability].extend(self.view_paths(label, capability, declared))
            if capability != 'read' and parent is not None and not paths[capability] and capability not in verdicts \
                    and parent._meta.label not in seen:
                inherited = self.resolve(parent._meta.label, seen + (label,))
                if capability in inherited['verdicts']:
                    verdicts[capability] = inherited['verdicts'][capability]
                else:
                    paths[capability] = [{**path, 'how': 'with-parent',
                                          'label': f'with {parent._meta.object_name}: {path["label"]}'}
                                         for path in inherited['paths'][capability]]
        self.resolved[label] = {'paths': paths, 'verdicts': verdicts}
        return self.resolved[label]

    # -- one table -----------------------------------------------------------------------------------------------
    def table(self, model):
        label = model._meta.label
        screen = self.screens.get(label, Screen())
        resolution = self.resolve(label)
        capabilities = {}
        for capability in CAPABILITIES:
            paths, verdict = resolution['paths'][capability], resolution['verdicts'].get(capability)
            if paths:
                capabilities[capability] = {'status': 'paths', 'paths': paths, 'why': ''}
            elif verdict is not None:
                capabilities[capability] = {'status': verdict.kind, 'paths': [], 'why': verdict.why}
            else:
                capabilities[capability] = {'status': 'undeclared', 'paths': [], 'why': ''}
                self.problems.append(
                    f'{label} has no {capability} path: declare it in {model._meta.app_label}/screens.py '
                    f'(SCREENS[{model._meta.object_name!r}] = Screen({capability}=<views> | no(why) | gap(why)); '
                    f'see "Data map" in the README).')
        columns = self.columns(model, screen)
        soft = issubclass(model, AuditedModel)
        db_table = model._meta.db_table
        section, masked = self.viewer.get(db_table, (None, []))
        # A table config/database.py leaves out on purpose (the sensor readings: billions of rows) is said so, not missed.
        left_out = db_table in database.viewer().excluded
        if section is None and not left_out:
            self.problems.append(
                f'{label}: the database viewer does not show {db_table}: add the app {model._meta.app_label!r} to a '
                f'section of config/database.py.')
        mentioned = [path for path, words in self.test_modules.items() if model._meta.object_name in words]
        return {
            'app': model._meta.app_label,
            'model': model._meta.object_name,
            'table': db_table,
            'description': descriptions_cache()[model],
            'columns': columns,
            'constraints': constraints_of(model),
            'screens': capabilities,
            'note': screen.note,
            'forms': [{'form': form.__name__, 'module': form.__module__, 'fields': form_fields(form)}
                      for form in self.all_forms(model)],
            'delete_kind': ('soft delete through the delete plan' if soft else
                            'no soft-delete column: a row goes, or stays, with what owns it'),
            'soft_delete': soft,
            'restore': self.restore(model, screen, soft),
            'viewer': {'section': section, 'masked': masked, 'left_out': left_out},
            'tests': mentioned,
        }

    def restore(self, model, screen, soft):
        """How a soft-deleted record comes back: the admin's Restore action, or why not."""
        if not soft:
            return {'status': 'n/a', 'why': ''}
        registered = admin.site._registry.get(model)
        if registered is not None and 'restore' in registered.actions:
            return {'status': 'admin', 'why': 'the Restore action in the admin (platform admin)'}
        if isinstance(screen.restore, Reason):
            return {'status': screen.restore.kind, 'why': screen.restore.why}
        if registered is not None:
            return {'status': 'none', 'why': 'listed read-only in the admin: a voided record is entered again on its '
                                             'page, where the checks run'}
        return {'status': 'gap', 'why': 'deleted rows are not in the admin, so nothing brings them back'}

    def columns(self, model, screen):
        label = model._meta.label
        parents = {rows.formset.fk.name for tab in Resource.registry for rows in tab.row_lists
                   if rows.formset.model is model}
        forms_here = self.all_forms(model)
        covered = {}
        for form in forms_here:
            for name, tab in form_fields(form).items():
                covered.setdefault(name, [])
                text = f'{form.__name__}' + (f' › {tab}' if tab else '')
                if text not in covered[name]:
                    covered[name].append(text)
        for key, targets in screen.fills.items():
            form_name, _, field_name = key.rpartition('.')
            holders = [form for form in forms_here if field_name in form.base_fields
                       and (not form_name or form.__name__ == form_name)]
            if not holders:
                self.problems.append(f'{label}: Screen.fills names the form field {key!r}, which no form of the table '
                                     f'has.')
            for column in ([targets] if isinstance(targets, str) else targets):
                if column not in {f.name for f in model._meta.concrete_fields}:
                    self.problems.append(f'{label}: Screen.fills sends {key!r} to {column!r}, which is not a '
                                         f'column of the table.')
                covered.setdefault(column, []).extend(
                    text for text in dict.fromkeys(f'{form.__name__}.{field_name}' for form in holders)
                    if text not in covered.get(column, []))
        for form, name, item in link_lists(model):
            for column in (item.target, item.primary, *item.detail_names):
                if column:
                    covered.setdefault(column, []).append(f'{form.__name__}.{name}')
        for parent, link in m2m_links(model):
            for form in self.forms_with(parent, link.name):
                for column in (link.m2m_field_name(), link.m2m_reverse_field_name()):
                    covered.setdefault(column, []).append(f'{form.__name__}.{link.name}')
        through = model._meta.auto_created
        link = next((f for f in through._meta.many_to_many if f.remote_field.through is model), None) if through else None
        reported = set()
        filled = {key.rpartition('.')[2] for key in screen.fills}
        exempt = set(screen.extra_fields) | filled
        for form in forms_here:
            if not issubclass(form, forms.ModelForm) or getattr(form.Meta, 'model', None) is not model:
                continue
            names = {f.name for f in model._meta.get_fields()} | AUDIT_COLUMNS | {ENTRY_KEY}
            for name in form.base_fields:
                if name not in names and name not in exempt and name not in reported:
                    reported.add(name)
                    self.problems.append(
                        f'{label}: the field {name!r} of {form.__name__} is not a column of {model._meta.db_table}: '
                        f'give it a model field or list it in Screen.extra_fields in '
                        f'{model._meta.app_label}/screens.py with the reason.')
        for name in screen.extra_fields:
            if not any(name in form.base_fields for form in forms_here):
                self.problems.append(f'{label}: Screen.extra_fields names {name!r}, which no form of the table has.')
            if name in filled:
                self.problems.append(f'{label}: {name!r} is in both Screen.fills and Screen.extra_fields.')
        result, undeclared, used_rest = [], [], False
        for column in model._meta.concrete_fields:
            entry = {'name': column.column, 'field': column.name, 'type': column_type(column), 'null': column.null,
                     'choices': [str(value) for value, _ in column.choices] if column.choices else [],
                     'link': None, 'on_form': [], 'how': '', 'why': ''}
            if column.is_relation:
                entry['link'] = {'table': column.related_model._meta.db_table,
                                 'model': column.related_model._meta.label,
                                 'on_delete': column.remote_field.on_delete.__name__}
            declared = screen.columns.get(column.name)
            rest = screen.columns.get(ALL)
            reason = system_reason(model, column, parents)
            if link is not None:
                entry.update(how='m2m', why=f'the link {link.name} of {through._meta.object_name}')
            elif reason:
                entry.update(how='system', why=reason)
                if declared is not None:
                    self.problems.append(
                        f'{label}.{column.name} is {reason}; the declaration in screens.py is not needed: remove it.')
            elif column.name in covered:
                entry.update(how='form', on_form=covered[column.name])
                if declared is not None:
                    self.problems.append(
                        f'{label}.{column.name} is on a form ({covered[column.name][0]}); the declaration in '
                        f'screens.py is stale: remove it.')
            elif declared is not None or rest is not None:
                entry.update(how=(declared or rest).kind, why=(declared or rest).why)
                used_rest = used_rest or declared is None
            else:
                entry.update(how='undeclared')
                undeclared.append(column.name)
            result.append(entry)
        if undeclared:
            self.problems.append(
                f'{label}: {", ".join(undeclared)} {"is" if len(undeclared) == 1 else "are"} on no form and nothing '
                f'says why: put the field on a form, or declare it in {model._meta.app_label}/screens.py '
                f'(SCREENS[{model._meta.object_name!r}] = Screen(columns={{<column>: computed(why) | system(why) | '
                f'gap(why)}})).')
        if ALL in screen.columns and not used_rest:
            self.problems.append(f'{label}: Screen.columns[{ALL!r}] covers no column: remove it.')
        names = {column.name for column in model._meta.concrete_fields} | {ALL}
        for name in screen.columns:
            if name not in names:
                self.problems.append(f'{label}: Screen.columns names {name!r}, which is not a column of the table.')
        return result

    # -- the output ----------------------------------------------------------------------------------------------
    def gaps(self):
        """Every table or column with no frontend path, ranked: nobody can fill it, nobody can read it, ..."""
        found = []
        for label, table in self.tables.items():
            for capability, screen in table['screens'].items():
                if screen['status'] == 'gap':
                    found.append({'table': label, 'what': capability, 'why': screen['why'],
                                  'weight': WEIGHT[capability]})
            for column in table['columns']:
                if column['how'] == 'gap':
                    found.append({'table': label, 'what': f'column {column["field"]}', 'why': column['why'],
                                  'weight': WEIGHT['column']})
            if table['restore']['status'] == 'gap':
                found.append({'table': label, 'what': 'restore', 'why': table['restore']['why'],
                              'weight': WEIGHT['restore']})
        return sorted(found, key=lambda item: (-item['weight'], item['table'], item['what']))

    def framework(self):
        """One line for each table Django owns: where it is handled, when a tab of ours does."""
        lines = {}
        for model in framework_models():
            tabs = tabs_of(model)
            owner = model._meta.auto_created
            if tabs:
                lines[model._meta.db_table] = f'the {tabs[0].plural} tab'
            elif owner and tabs_of(owner):
                lines[model._meta.db_table] = f'a field of the {tabs_of(owner)[0].plural} tab'
            else:
                lines[model._meta.db_table] = 'framework-internal'
        return dict(sorted(lines.items()))

    def document(self):
        return {'tables': list(self.tables.values()), 'gaps': self.gaps(), 'framework': self.framework()}


_descriptions = {}


def descriptions_cache():
    if not _descriptions:
        _descriptions.update(descriptions())
    return _descriptions


def build():
    """The map, as the code says it now: (Map, the Markdown, the JSON text). English, whatever language is active."""
    _descriptions.clear()
    with translation.override('en'):
        built = Map()
        document = built.document()
        return built, markdown(built, document), json.dumps(document, indent=2, ensure_ascii=False) + '\n'


def problems():
    """What the rules find wrong: a table, a column or a form field without a declared or derived screen."""
    return build()[0].problems


# --- Markdown ---------------------------------------------------------------------------------------------------

def cell(text):
    return str(text).replace('|', '\\|').replace('\n', ' ')


def path_text(path):
    routes = ', '.join(f'`{route}`' for route in path['routes'] if route)
    return f'{path["label"]} ({routes})' if routes else path['label']


def capability_text(screen):
    if screen['status'] == 'paths':
        return '; '.join(path_text(path) for path in screen['paths'])
    return {'none': 'none, by design: ', 'gap': '**GAP**: '}.get(screen['status'], screen['status'] + ': ') + screen['why']


def markdown(built, document):
    lines = [
        '# Data map', '',
        'Generated by `manage.py data_map` from the models, the tabs (`core.crud.Resource`), the routes, the forms and '
        'each app\'s `screens.py`; do not edit. `manage.py data_map --check` (and `core.test_datamap.DataMapTests`) fail when '
        'this file is stale. What a table needs to be on the map is in the README, "Data map".', '',
        f'{len(document["tables"])} tables in {len({t["app"] for t in document["tables"]})} apps; '
        f'{len(document["gaps"])} gaps (last section).', '', '## Contents', '',
    ]
    by_app = {}
    for table in document['tables']:
        by_app.setdefault(table['app'], []).append(table)
    for app, tables in by_app.items():
        lines.append(f'- [{app}](#{app}) ({len(tables)} tables): ' + ', '.join(
            f'[{t["model"]}](#{anchor(t)})' for t in tables))
    lines += ['- [Django\'s own tables](#djangos-own-tables)', '- [Gaps](#gaps)', '']
    for app, tables in by_app.items():
        lines += [f'## {app}', '']
        for table in tables:
            lines += table_block(table)
    lines += ['## Django\'s own tables', '', 'Not mapped further; one line each.', '']
    lines += [f'- `{name}`: {where}' for name, where in document['framework'].items()]
    lines += ['', '## Gaps', '',
              'Every table or column with no frontend path, heaviest first (a table nobody can fill 4, edit or read 3, '
              'delete 2, a row nothing can restore or a column 1). Each says what is missing and why; fixing one means building the page, then '
              'changing its declaration in `<app>/screens.py`.', '']
    if document['gaps']:
        lines += ['| # | Table | Missing | Why |', '|---|---|---|---|']
        lines += [f'| {i} | {g["table"]} | {g["what"]} | {cell(g["why"])} |' for i, g in enumerate(document['gaps'], 1)]
    else:
        lines.append('None.')
    return '\n'.join(lines) + '\n'


def anchor(table):
    return f'{table["app"]}{table["model"]}'.lower()


def table_block(table):
    lines = [f'<a id="{anchor(table)}"></a>', f'### {table["app"]}.{table["model"]} (`{table["table"]}`)', '',
             table['description'], '']
    for capability in CAPABILITIES:
        lines.append(f'- **{capability}**: {capability_text(table["screens"][capability])}')
    if table['note']:
        lines.append(f'- **how it works**: {table["note"]}')
    viewer = table['viewer']
    shown = (f'{viewer["section"]} › {table["table"]}' if viewer['section']
             else 'left out on purpose (config/database.py)' if viewer.get('left_out') else 'not shown')
    masked = f' (never shown: {", ".join(viewer["masked"])})' if viewer['masked'] else ''
    restore = table['restore']
    back = {'admin': 'restored in the admin', 'none': f'not restored: {restore["why"]}',
            'gap': f'**GAP**: {restore["why"]}'}.get(restore['status'], '')
    lines.append(f'- **delete kind**: {table["delete_kind"]}' + (f'; {back}' if back else '')
                 + f'; **database viewer**: {shown}{masked}')
    if table['forms']:
        lines.append('- **forms**: ' + ', '.join(f'`{f["form"]}`' for f in table['forms']))
    constraints = [f'{c["name"]} ({c["kind"]}{": " + ", ".join(c["fields"]) if c["fields"] else ""})'
                   for c in table['constraints']]
    if constraints:
        lines.append('- **constraints**: ' + '; '.join(constraints))
    if table['tests']:
        shown_tests = ', '.join(f'`{t}`' for t in table['tests'][:3])
        more = f' and {len(table["tests"]) - 3} more' if len(table['tests']) > 3 else ''
        lines.append(f'- **tests that mention it**: {shown_tests}{more}')
    lines += ['', '| Column | Type | Null | Link (on delete) | On a form / why not |', '|---|---|---|---|---|']
    for column in table['columns']:
        link = column['link']
        target = f'{link["table"]} ({link["on_delete"]})' if link else ''
        if column['how'] == 'form':
            where = ', '.join(column['on_form'])
        else:
            where = f'{column["how"]}: {column["why"]}' if column['why'] else column['how']
        lines.append(f'| {column["name"]} | {column["type"]} | {"yes" if column["null"] else ""} | {target} | '
                     f'{cell(where)} |')
    return lines + ['']
