"""One format for every farm tab: list, create, edit and delete pages built from a `Resource`.

A tab declares its model, form, labels and list template once; these views add what every tab
needs the same way:
- permissions: the role must hold view/add/change/delete on the model (the platform admin holds all);
- audit log: every create, change and delete is recorded in the same transaction, in English whatever
  language the person uses (core.audit);
- optimistic locking: a save based on an outdated `version` is refused;
- soft delete: models with `soft_delete()` are hidden, not erased;
- modal or page: opened from a `data-modal` link the same view renders inside a dialog, opened
  directly it renders as a full page (see core/templates and static/js/components.js);
- languages: a tab's name, plural and group are translatable text (gettext_lazy); the pages put them
  into sentences, so write them in the lower case a noun has in the middle of a sentence;
- rows saved as a list: a tab's `row_lists` (a site's contacts) get their URL, their formset on the
  edit page and a logged save (RowList);
- files: a form with a file field gets the uploaded files (a library document's PDF);
- a read page: a tab with a `detail_template` gets a page that shows one record to everyone who may
  read the tab (the edit form needs the change permission), e.g. a document with its citation;
- a form sent twice creates once: every new-record form carries a key (TabbedForm), stored with the record it
  created in one table for every kind of record (core.models.EntryKey), and the same form sent again opens the
  record the first one created;
- a second place: a tab's `mounts` serve the same Resource, views and records again under another address and
  panel (HR's people pages under Production › Team); the request carries the mount it came by (`mount_of`), the
  tab's `scoped` narrows the rows to it, and every link and redirect stays in it;
- one writer: a tab whose records its area's service writes (`service_writes`) hands every write to that service, which
  checks its own rules, locks in its own order and logs; crud keeps the form, the verb, the scope, the version and the
  pages (core/tests_data_access.py, rule S, holds a record to one writer; a service tab with something crud would
  have saved beside the record is refused when it is declared).
"""
import copy
import uuid
from dataclasses import dataclass, field as dataclass_field
from functools import wraps
from urllib.parse import quote

from django import forms
from django.contrib import messages
from django.contrib.postgres.constraints import ExclusionConstraint
from django.core.exceptions import NON_FIELD_ERRORS, PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, models, transaction
from django.db.models import F, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.text import capfirst
from django.utils.translation import gettext as _

from . import audit, formpanels, formprops, listprops, navigation, softdelete
from .models import AuditedModel, AuditLog, EntryKey, violated_constraint
from .softdelete import plan_delete
from .ui import is_next
from .widgets import NONE


@dataclass(frozen=True)
class Mount:
    """A second place a tab is served: the same Resource, views and records under another address, in another panel of the
    menu (HR's leave requests under Production › Team as well as under Company › HR). `key` names it: it prefixes the URL
    names ('hr:production_leaverequest_list') and tells the tab's `scoped` which rows belong there; `url_prefix` is the
    address of the tab's list there ('production/team/leave'). A record outside the mount's rows is a 404 there, as any
    record out of scope; the record itself, its rules and its log are the same."""
    key: str
    url_prefix: str


def mounted_name(url_name, mount):
    """The name of the route `url_name` ('hr:punch') as served under `mount`: 'hr:production_punch'. Unchanged without one."""
    if mount is None:
        return url_name
    namespace, _separator, name = url_name.rpartition(':')
    return f'{namespace}:{mount.key}_{name}' if namespace else f'{mount.key}_{name}'


def mount_of(request):
    """The mount the request came by (`serve_mounted`); None for a plain route, or no request."""
    return getattr(request, 'mount', None)


def serve_mounted(view, mount):
    """`view` as served under `mount`: the request carries the mount (`mount_of`), so the scope, the page's heading and
    every link and redirect it builds are the mount's. Without a mount the view is returned as it is."""
    if mount is None:
        return view

    @wraps(view)
    def mounted(request, *args, **kwargs):
        request.mount = mount
        return view(request, *args, **kwargs)
    return mounted


def is_modal(request):
    return request.headers.get('X-Modal') == '1'


def render_page(request, template, context):
    """Renders `template` inside the console page or, for a modal request, inside the dialog."""
    context.setdefault('base_template', 'modal_base.html' if is_modal(request) else 'app_base.html')
    return render(request, template, context)


def flash(request, text, resource, obj):
    """Tells the person what happened to a record. `text` has %(name)s (the kind of record, capitalised
    as it starts the sentence) and %(object)s (the record)."""
    messages.success(request, text % {'name': capfirst(resource.name), 'object': obj})


def done(request, url, stay=False):
    """After a successful save. A page follows the redirect to `url`. A dialog either loads `url`
    into itself (`stay`, e.g. a new record opens for editing) or closes and reloads its page."""
    if is_modal(request):
        header = 'X-Modal-Load' if stay else 'X-Modal-Redirect'
        return HttpResponse(status=204, headers={header: url})
    return redirect(url)


# The marker of a posted form to render again with what was entered, nothing saved (TabbedForm.refresh_on).
DRAFT = '_draft'
# The hidden field of a new-record form that keys it (not a secret): the same form sent twice (a double click, a
# retried request) creates one record (core.models.EntryKey). The form carries it hidden (TabbedForm).
ENTRY_KEY = 'entry_key'


@dataclass(frozen=True)
class Fieldset:
    """Fields of an inner tab shown together under a heading, e.g. an equipment type's "Performance"."""
    label: str
    names: list = dataclass_field(default_factory=list)
    help: str = ''


class TabbedForm(forms.ModelForm):
    """A model form whose fields are split over inner tabs: `tabs = [(key, label, [fields])]`, where a
    tab can group some of its fields under a heading (Fieldset) and say a word about itself (`tab_help`).
    `fixed_after_creation` names the fields chosen once: they are shown but cannot be changed on an
    existing record (a production department stays on its site); a form may open one again for a record that never
    got a value (a department a deleted site left without a site).

    `refresh_on` names fields whose value changes the form itself (an equipment type decides its
    specification fields): changing one posts the form with the `_draft` marker and the server renders
    it again with everything entered so far, validating and saving nothing (frontend/components.ts,
    data-refresh). The values travel in the request body, not the address, so long texts fit and stay out
    of access logs. They reach the form as a `draft`; an unbound form starts from them instead of the
    stored record. The marker carries the name of the field that changed, and the form opens again on
    that field's tab.

    A form can drop fields for one record (`del self.fields[name]` in `__init__`, e.g. the measures a
    pond does not have); the tabs then show the fields it kept, and a heading left without fields goes.

    A new record's form gets a hidden key (ENTRY_KEY); `note_sent()` stores it with the record it created
    (core.models.EntryKey) and `sent_before()` finds the record a form with the same key already created (CreateView)."""

    tabs = []
    fixed_after_creation = ()
    refresh_on = ()
    version = forms.IntegerField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, draft=None, **kwargs):
        self.draft = draft
        self.tab_help = {}
        super().__init__(*args, **kwargs)
        for name in self.refresh_on:
            self.fields[name].widget.attrs['data-refresh'] = DRAFT
        if not self.instance._state.adding:
            for name in self.fixed_after_creation:
                self.fields[name].disabled = True
                self.fields[name].required = False
        if not any(f.name == 'version' for f in self._meta.model._meta.fields):
            del self.fields['version']
        elif not self.instance._state.adding and not self.is_bound:
            self.initial['version'] = self.instance.version
        if self.instance._state.adding:
            self.fields[ENTRY_KEY] = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4, required=False)

    def get_initial_for_field(self, field, field_name):
        """A draft starts from the values it carries; a field it does not carry, or one that cannot be
        changed, from the record as usual."""
        key = self.add_prefix(field_name)
        if self.draft is not None and not field.disabled and not field.widget.value_omitted_from_data(self.draft, {}, key):
            return field.widget.value_from_datadict(self.draft, {}, key)
        return super().get_initial_for_field(field, field_name)

    def current(self, name):
        """A field's value as the form has it now (posted, drafted or stored), cleaned; None when it is not valid."""
        try:
            return self.fields[name].clean(self[name].value())
        except ValidationError:
            return None

    def clean(self):
        cleaned = super().clean()
        self._check_conditional_constraints(cleaned)
        return cleaned

    def sent_key(self):
        """The key the form was sent with, read from what was posted (before or without the form's checks); None for a
        form without one or a key that is not a key."""
        if ENTRY_KEY not in self.fields or not self.is_bound:
            return None
        try:
            return self.fields[ENTRY_KEY].clean(self[ENTRY_KEY].value())
        except ValidationError:
            return None

    def sent_before(self):
        """The record a form with this form's key already created (the same form sent twice); None for a
        first sending or a form without a key. It needs no check of the form: ask it first."""
        key = self.sent_key()
        return None if key is None else EntryKey.record_of(key, self._meta.model)

    def note_sent(self, record):
        """Stores the form's key with the record it created (in the creating transaction)."""
        key = self.sent_key()
        if key is not None:
            EntryKey.note(key, record)

    def _check_conditional_constraints(self, cleaned):
        """Conditional unique and exclusion constraints, e.g. "code unique among live records", "scientific
        name unique among live records whatever its case" (a constraint on an expression, Lower(...)), or "one
        protocol in force per unit among live assignments" (days that overlap). Django leaves them out of form
        validation when the condition uses a field the form does not edit (is_deleted), so check them here:
        the record as the form would save it, by the constraint itself. The error goes on the constraint's
        last field the form shows, with its message. An empty value never clashes in a unique constraint,
        unless it counts empty values as equal (`nulls_distinct=False`: one handling rule for every species, the
        one with no species); in an exclusion constraint it may mean something (an open end of a period), so it
        is checked too."""
        model = self._meta.model
        for constraint in model._meta.constraints:
            unique = isinstance(constraint, models.UniqueConstraint)
            if not (unique or isinstance(constraint, ExclusionConstraint)) or constraint.condition is None:
                continue
            names = constrained_fields(constraint)
            candidate = copy.copy(self.instance)
            for name in names:
                value = cleaned.get(name) if name in self.fields else getattr(self.instance, name, None)
                if unique and value in (None, '') and constraint.nulls_distinct is not False:
                    break
                setattr(candidate, name, value)
            else:
                error_field = next((f for f in reversed(names) if f in self.fields), None)
                if error_field is None or error_field in self.errors:
                    continue
                try:
                    constraint.validate(model, candidate)
                except ValidationError:
                    self.add_error(error_field, constraint.violation_error_message)

    def tab_list(self):
        """The inner tabs: their fieldsets of bound fields (fields outside a Fieldset form one without a
        heading), their help, and whether a field on them has an error. Fields the form dropped for
        this record are left out, and so is a fieldset left without fields."""
        tabs = []
        for key, label, names in self.tabs:
            fieldsets = []
            for item in names:
                if isinstance(item, Fieldset):
                    fieldsets.append({'label': item.label, 'help': item.help,
                                      'fields': [self[n] for n in item.names if n in self.fields]})
                elif item not in self.fields:
                    continue
                elif fieldsets and not fieldsets[-1]['label']:
                    fieldsets[-1]['fields'].append(self[item])
                else:
                    fieldsets.append({'label': '', 'help': '', 'fields': [self[item]]})
            names = tab_fields([(key, label, names)])
            tabs.append({'key': key, 'label': label, 'help': self.tab_help.get(key, ''),
                         'fieldsets': [fieldset for fieldset in fieldsets if fieldset['fields']],
                         'has_errors': any(name in self.errors for name in names)})
        return tabs

    def tab_of(self, name):
        """The key of the inner tab that shows the field `name`; '' when no tab shows it."""
        return next((key for key, label, names in self.tabs if name in tab_fields([(key, label, names)])), '')


class CodedFormMixin:
    """Name and code as the source validates them: both at least 2 characters, the code upper-case."""

    def clean_code(self):
        code = self.cleaned_data['code'].strip().upper()
        if len(code) < 2:
            raise ValidationError(_('Code must be at least 2 characters.'))
        return code

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if len(name) < 2:
            raise ValidationError(_('Name must be at least 2 characters.'))
        return name


def tab_fields(tabs):
    """Every field name of the tabs, the ones inside a Fieldset too."""
    return [name for _, _, names in tabs for item in names
            for name in (item.names if isinstance(item, Fieldset) else [item])]


def refusal_on_form(form, error):
    """Puts a ValidationError raised at the save (a service's refusal, a rule under a lock) on the form: each message on
    its field when the error names fields the form has, else above the form."""
    if hasattr(error, 'error_dict') and set(error.error_dict) <= {*form.fields, NON_FIELD_ERRORS}:
        form.add_error(None, error)
        return
    form.add_error(None, error.message_dict.get(NON_FIELD_ERRORS, error.messages) if hasattr(error, 'error_dict')
                   else error.messages)


def constraint_error(form, error):
    """Puts a database constraint's refusal (`error`, an IntegrityError) on the form, on the constraint's last field
    the form shows, with its message. False when the error names no constraint of the form's model."""
    constraint = violated_constraint(form._meta.model, error)
    if constraint is None:
        return False
    names = []
    if isinstance(constraint, (models.UniqueConstraint, ExclusionConstraint)):
        names = [item for item in constrained_fields(constraint) if item in form.fields]
    form.add_error(names[-1] if names else None, constraint.violation_error_message)
    return True


def refusal_text(error):
    """What the database said when it refused a write (an IntegrityError): its own message."""
    return str(getattr(getattr(error.__cause__, 'diag', None), 'message_primary', '') or error)


def trigger_refusal(form, error):
    """Puts a constraint trigger's refusal (a check violation whose constraint is a trigger, `trg_...`: a rule across
    tables, e.g. a unit not moved to another site while a sensor is placed in it) on the form, with the database's
    message. False for any other error."""
    diag = getattr(error.__cause__, 'diag', None)
    if getattr(diag, 'sqlstate', '') != '23514' or not (getattr(diag, 'constraint_name', '') or '').startswith('trg_'):
        return False
    form.add_error(None, refusal_text(error))
    return True


def constrained_fields(constraint):
    """The fields a unique or exclusion constraint covers: its `fields`, or the fields its expressions read
    (Lower('scientific_name') covers scientific_name; an assignment's daterange its first and last day)."""
    if getattr(constraint, 'fields', None):
        return list(constraint.fields)
    expressions = [item[0] if isinstance(item, tuple) else item for item in constraint.expressions]
    nodes = [node for expression in expressions
             for node in ([expression] if isinstance(expression, F) else expression.flatten())]
    return list(dict.fromkeys(node.name for node in nodes if isinstance(node, F)))


class RowFormSet(forms.BaseInlineFormSet):
    """The rows of a RowList."""

    def kept_rows(self):
        """Cleaned data of the rows to keep: not marked for removal and not an untouched blank row."""
        return [
            form.cleaned_data for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get('DELETE')
            and (form.instance.pk or form.has_changed())
        ]


class RowList:
    """Rows a record owns that are edited as one list on a tab of the record's form and saved
    together, replacing the stored rows: a site's contacts, a feeder's calibrations. Saving needs the
    record's change permission and is logged on the record as one change, the list before and after
    (`describe` each row, in English like every log row). Declare it in the Resource's `row_lists`;
    its URL, its formset on the edit page and its save follow from there."""

    key = ''          # 'contacts': URL part, formset prefix and the edit page's context name
    tab = ''          # the inner tab it is shown on
    label = ''        # how the activity log names the list, e.g. _('Contacts')
    formset = None    # an inline formset over the row model (RowFormSet); the rows have `created_by`
    saved = ''        # the flash message: ngettext_lazy('%(count)d ... saved.', '...', 'count')
    question_field = None   # the box that answers what its save may ask first (`save`'s `seen`), when it may
    # Its panel on the record's page in the new look (core/formpanels.py), in the words its classic template says
    # (crud/_row_list.html's): the heading and tab, the help, the sentence of no rows, the two buttons, the sentence said
    # instead of the list while the record cannot have one ('' says nothing), one row's name for a screen reader (the
    # heading when ''), whether the panel stands on the record's own tab `tab` (a site's contacts on Contact), and a
    # field's words in a row besides its label.
    title = help_text = empty_text = add_label = save_label = pending_text = legend = ''
    on_record_tab = False
    field_labels = {}

    @classmethod
    def words(cls, obj):
        """The panel's words for `obj` (None: a new record): a list may say another `pending` for a record it does not
        apply to yet (a piece of equipment whose type takes no calibrations)."""
        return {'title': cls.title, 'help': cls.help_text, 'empty': cls.empty_text, 'add': cls.add_label,
                'save': cls.save_label, 'pending': cls.pending_text, 'legend': cls.legend or cls.title}

    @classmethod
    def field_words(cls):
        """The words of a row's fields that the template says in place of their labels: Remove for the DELETE box."""
        return {'DELETE': _('Remove'), **cls.field_labels}

    @classmethod
    def applies_to(cls, obj):
        """Whether the record has this list at all (only a feeder has calibrations)."""
        return True

    @classmethod
    def allowed(cls, request, obj):
        """Whether the person may save this list of the record, beyond editing the record (an experiment's team: its
        lead alone). The default allows it."""
        return True

    @classmethod
    def describe(cls, row):
        """One row as the activity log shows it."""
        return str(row)

    @classmethod
    def rows(cls, obj):
        return cls.formset.model.objects.filter(**{cls.formset.fk.name: obj})

    @classmethod
    def summary(cls, obj):
        return '; '.join(cls.describe(row) for row in cls.rows(obj)) or None

    @classmethod
    def values(cls, user, row, fields):
        """The stored row's values from one cleaned row: the form's model fields as they are. A list whose
        rows choose something the stored row reaches through another record (a storage location's reorder
        levels choose a feed and store its item of the store) maps it here, as `user`."""
        return {name: row[name] for name in fields}

    @classmethod
    def severity(cls, obj):
        """The severity of the log entry of a change of the list: normal; a list whose change protects or endangers fish
        or food says critical (a medicine's withdrawal already given, audit F-196)."""
        return AuditLog.Severity.NORMAL

    @classmethod
    def save(cls, user, obj, rows, entity_type, seen=None):
        """Replaces the stored rows with `rows` (cleaned data) and logs the change on `obj`."""
        model, link = cls.formset.model, cls.formset.fk.name
        # The row's own fields; an inline formset adds the link to its parent to the form's fields.
        fields = [name for name in cls.formset.form._meta.fields if name != link]
        with transaction.atomic(), audit.source_language():
            before = cls.summary(obj)
            cls.rows(obj).delete()
            model.objects.bulk_create([
                model(**{link: obj, 'created_by': user}, **cls.values(user, row, fields)) for row in rows
            ])
            after = cls.summary(obj)
            if before != after:
                audit.record(user, AuditLog.Action.UPDATE, obj, {str(cls.label): [before, after]},
                             entity_type=entity_type, severity=cls.severity(obj))


class Resource:
    """A farm tab. Subclass and set the attributes; `urls()` gives its URL patterns."""

    registry = []         # every declared tab; the tab rules in core/tests.py check each one

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.service_writes:
            dropped = cls.left_to_crud()
            if dropped:
                raise TypeError(f'{cls.__name__} has service_writes, so crud saves nothing beside the record, and it has '
                                f'{", ".join(dropped)}: the service writes those too, or the tab is not a service tab.')
        Resource.registry.append(cls)

    @classmethod
    def left_to_crud(cls):
        """What crud would save or run beside the record and does not for a tab with `service_writes`: refused when
        the tab is declared, so nothing is dropped without a word."""
        found = []
        if cls.form_class is not None and cls.model is not None:
            # the fields the form really has (`fields = '__all__'` and `exclude` too), not what its Meta spells
            found += [f'the many-to-many field {field.name} on its form (form.save_m2m)'
                      for field in cls.model._meta.many_to_many if field.name in cls.form_class.base_fields]
        if cls.row_lists:
            found.append('row lists')
        for hook in ('after_save', 'change_severity'):
            if getattr(cls, hook).__func__ is not getattr(Resource, hook).__func__:
                found.append(f'its own {hook}')
        return found

    model = None
    form_class = None
    name = ''             # _('site'), translatable like plural
    plural = ''           # _('sites')
    url_prefix = ''       # 'sites'
    search_fields = []
    list_template = ''    # extends crud/list.html and fills the `items` block
    form_template = 'crud/form.html'
    icon = 'plus'         # shown in the empty list
    namespace = ''        # URL namespace; defaults to the model's app label
    actions = ('add', 'change', 'delete')   # what this tab offers besides the list
    create_view = None    # the add page's view; None is CreateView (a dialog that writes several rows has its own)
    row_lists = ()        # RowList classes edited on the record's tabs (a site's contacts)
    page_size = None      # rows per page of the list; None lists every record on one page (nested lists)
    detail_template = ''  # a read page for one record (extends crud/detail.html); '' for none
    private_fields = ()   # form fields holding a person's own text (a leave reason): the activity log says
                          # "Private text" for a filled one and never stores the words
    mounts = ()           # Mount: the other places the tab is served, its rows there narrowed by `scoped`
    # The list in the new look (core/listprops.py): `list_rows(view, objects, context)` gives its table (a classmethod;
    # None keeps the classic list in the new look too). The search box's placeholder and the empty list's sentence when
    # the tab's list template has its own (its blocks `search_placeholder` and `empty_text`): the same msgid.
    list_rows = None
    list_above_next = ''      # a template the server draws above the new look's list (a safety notice the classic list
                              # draws in its `above` block: Alarm rules' {% alarm_watch %}); '' for none
    list_template_next = ''   # the new look's page of a tab whose list is not a table (Scheduling settings), drawn by
                              # the server from the same context; '' for none
    list_next_props = None    # its island's props, when the page is an island: (view, objects, context) -> dict
    search_placeholder = ''
    empty_text = ''

    # --- names derived from the model -------------------------------------------------------
    @classmethod
    def perm(cls, action):
        meta = cls.model._meta
        return f'{meta.app_label}.{action}_{meta.model_name}'

    @classmethod
    def url_name(cls, action, mount=None):
        return mounted_name(f'{cls.namespace or cls.model._meta.app_label}:{cls.model._meta.model_name}_{action}', mount)

    @classmethod
    def menu_place(cls, mount=None):
        """Where the tab's page sits in the menu: the entry read with its permission or, under a mount, the entry of its
        mounted list (one permission has an entry in each panel then)."""
        if mount is not None:
            return navigation.page(cls.url_name('list', mount))
        return navigation.place(cls.perm('view'))

    @classmethod
    def group(cls, mount=None):
        """The menu heading the tab's page sits under, shown above its title: its group, e.g. _('Facility'), or the
        section of an entry in a group without a label (navigation.Place.heading)."""
        return cls.menu_place(mount).heading

    @classmethod
    def title(cls, mount=None):
        """The page's heading: the menu entry's label, so the page is called what the menu calls it
        (e.g. Tanks, ponds & cages, whose records are units)."""
        return cls.menu_place(mount).entry.label

    @classmethod
    def allows(cls, action):
        return action == 'view' or action in cls.actions

    @classmethod
    def entity_type(cls):
        """How the activity log names this kind of record: its English name, shown translated."""
        return audit.english(cls.name or audit.entity_type_of(cls.model))

    # --- extension points ---------------------------------------------------------------------
    @classmethod
    def queryset(cls):
        return cls.model._default_manager.all()

    @classmethod
    def list_queryset(cls, request):
        """The records the list starts from, before its search and filters: the live ones (queryset). A tab
        whose records are voided rather than deleted can show the voided ones too when asked."""
        return cls.queryset()

    @classmethod
    def scoped(cls, request, objects):
        """The records the person may reach at all: `objects` narrowed to the rows their relationship to the
        data allows (HR: their own team). The role matrix says which verbs; this says which rows. A record
        outside it does not exist for them: its page, its edit, its delete and its lists are a 404, whatever
        the address or the query. The default is every row. It is applied to the list, to every record
        lookup and to the locks a save takes, so a rule written here holds on every verb. Under a mount
        (`mount_of(request)`) it narrows to the mount's rows as well."""
        return objects

    @classmethod
    def allowed(cls, request, obj, action):
        """Whether the person may `action` ('change' or 'delete') this record they can reach: the verbs and the rows are
        settled by the role and `scoped`; this is for a rule about the record itself (HR: not one's own attendance or plan).
        The default allows it."""
        return True

    @classmethod
    def visible(cls, request):
        """Every live record of the tab the person may reach: `queryset` narrowed by `scoped`."""
        return cls.scoped(request, cls.queryset())

    @classmethod
    def form(cls, request, *args, **kwargs):
        """The tab's form; override to hand it more, e.g. who is editing."""
        return cls.form_class(*args, **kwargs)

    @classmethod
    def edit_extras(cls, request, obj):
        """Extra context for the edit page: the formsets of its row lists, and whatever a tab adds."""
        return {rows.key: rows.formset(instance=obj, prefix=rows.key) for rows in cls.row_lists if rows.applies_to(obj)}

    # The context of the edit page (edit_extras) that `next_panels` draws, besides the formsets of its row lists.
    next_extras = frozenset()

    @classmethod
    def next_panels(cls, view, form, obj, extra):
        """The new look of what the tab's own form template (form_template) adds to crud/form.html: its panels as
        core/formpanels.py words them, from the page's context `extra` (edit_extras, a refused list's formset). None keeps
        the classic page in the new look (a template not ported); the shared template adds nothing."""
        return [] if cls.form_template == 'crud/form.html' else None

    @classmethod
    def snapshot(cls, obj):
        """What the audit log compares before and after a save: the form's fields under its labels."""
        return audit.snapshot(obj, tab_fields(cls.form_class.tabs), getattr(cls.form_class.Meta, 'labels', {}),
                              private=cls.private_fields)

    @classmethod
    def recorded(cls, obj):
        """The snapshot as the audit log stores it, built in the source language."""
        with audit.source_language():
            return cls.snapshot(obj)

    @classmethod
    def change_severity(cls, before, obj):
        """The severity of the log entry of an edit, from the record as stored before it (`before`) and as saved (`obj`):
        normal; an edit that turns off something protecting fish says critical (a default sensor alarm rule switched
        off, sensors/resources.py), as the activity log shows apart."""
        return AuditLog.Severity.NORMAL

    @classmethod
    def after_save(cls, request, obj, created):
        """Runs inside the save transaction, after the audit row; e.g. invite a new user. A ValidationError raised here
        rolls the save back and is shown on the form (a rule checked under a lock the form could not hold). Never run
        for a tab whose service writes its records (`service_writes`): the service does what follows its write."""

    # One writer (the architecture audit of 26.11.2026, H-5): the records of a tab with `service_writes` are written by
    # their area's service only, never by crud beside it. crud reads the form (the fields, their parsing and the model's
    # own checks), the verb, the scope, the record's lock and its version, and then hands the write to these, which call
    # the service: it checks its rules itself, locks in its own order and writes its own audit row. A ValidationError
    # it raises is shown on the form, each message on its field when the field is there; a PermissionDenied is a 403.
    # crud saves nothing beside the record for such a tab (no form.save_m2m, no row list, no change_severity, no
    # after_save): a tab that has one of them is refused when it is declared (left_to_crud).
    service_writes = False

    @classmethod
    def create_record(cls, request, form):
        """The new record from the valid `form`, written by the service; returns it."""
        raise NotImplementedError(f'{cls.__name__} has service_writes and offers Create: say which service writes it')

    @classmethod
    def change_record(cls, request, form, current):
        """The edit `form` asks of `current` (the record as locked now, its version checked), written by the service;
        returns the saved record."""
        raise NotImplementedError(f'{cls.__name__} has service_writes and offers Edit: say which service writes it')

    @classmethod
    def delete_record(cls, request, record):
        """Deletes (voids) `record`, as the person reached it, through the service."""
        raise NotImplementedError(f'{cls.__name__} has service_writes and offers Delete: say which service deletes it')

    @classmethod
    def after_commit(cls, request, obj, created):
        """Runs once the save's transaction has committed, before the page is answered: for what must not happen
        inside it, or for a record that might still be rolled back (handing a new user's invitation to the mail
        worker). Not called for a save that failed. It cannot undo the save. "After the commit" holds while no
        transaction wraps the whole request: ATOMIC_REQUESTS is refused for that (core.E006)."""

    # When a save may ask something first (`edited`, below): the template the edit page shows the question with, and the
    # name of the box that answers it.
    question_template = None
    question_field = None

    @classmethod
    def edited(cls, request, record, write, seen):
        """Makes an edit of `record` (as read before the edit, not locked yet): `write()` as it is, which locks the
        record, checks that it has not changed since and saves it. A tab whose records feed a rule that must ask
        before a change stands wraps it (the medicine withdrawal: farm.health.withdrawal.guarded), locking what the
        rule reads before `write()` locks the record; `seen` is the value of the edit form's box for that question.
        A refusal is a ValidationError, shown on the form with what it carries (`change`, as `question` in the
        page)."""
        return write()

    @classmethod
    def search(cls, objects, query):
        """The records that match what was typed in the list's search box: by default those with the
        text in one of `search_fields`. A tab with a better search (full text, ranked) overrides it."""
        condition = Q()
        for field in cls.search_fields:
            condition |= Q(**{f'{field}__icontains': query})
        return objects.filter(condition)

    @classmethod
    def filter_list(cls, request, objects):
        """Narrows the list by the tab's own filters; returns the objects and context for the filter bar."""
        return objects, {}

    @classmethod
    def list_filters(cls, view, context):
        """The list's filters in the new look (core.listprops.choice), from the values `filter_list` put in `context`."""
        return []

    @classmethod
    def detail_extras(cls, request, obj):
        """Extra context for the read page (detail_template)."""
        return {}

    # --- URLs ---------------------------------------------------------------------------------
    @classmethod
    def urls(cls):
        """The tab's routes, then the same routes under each of its mounts (named with the mount's key first)."""
        return [route for mount in (None, *cls.mounts) for route in cls.routes(mount)]

    @classmethod
    def routes(cls, mount=None):
        p = mount.url_prefix if mount is not None else cls.url_prefix
        n = (f'{mount.key}_' if mount is not None else '') + cls.model._meta.model_name
        pk = 'uuid:pk' if isinstance(cls.model._meta.pk, models.UUIDField) else 'int:pk'

        def view(view_class, **initkwargs):
            return serve_mounted(view_class.as_view(resource=cls, **initkwargs), mount)
        routes = {
            'list': path(f'{p}/', view(ListView), name=f'{n}_list'),
            'add': path(f'{p}/new/', view(cls.create_view or CreateView), name=f'{n}_create'),
            'change': path(f'{p}/<{pk}>/', view(UpdateView), name=f'{n}_edit'),
            'delete': path(f'{p}/<{pk}>/delete/', view(DeleteView), name=f'{n}_delete'),
        }
        rows = [path(f'{p}/<{pk}>/{row_list.key}/', view(RowListView, rows=row_list),
                     name=f'{n}_{row_list.key}') for row_list in cls.row_lists] if cls.allows('change') else []
        detail = [path(f'{p}/<{pk}>/view/', view(DetailView), name=f'{n}_detail')
                  ] if cls.detail_template else []
        return [route for action, route in routes.items() if action == 'list' or cls.allows(action)] + rows + detail


class ResourceView:
    resource = None
    action = 'view'

    @classmethod
    def as_view(cls, **initkwargs):
        def view(request, *args, **kwargs):
            self = cls()
            for key, value in initkwargs.items():
                setattr(self, key, value)
            self.request = request
            if not self.resource.allows(self.action) or not request.user.has_perm(self.resource.perm(self.action)):
                raise PermissionDenied
            handler = getattr(self, request.method.lower(), None)
            if handler is None:
                return HttpResponse(status=405)
            return handler(request, *args, **kwargs)
        return view

    @classmethod
    def as_page(cls, resource, request):
        """An instance for reuse from another view that already checked its own permission."""
        self = cls()
        self.resource, self.request = resource, request
        return self

    @property
    def mount(self):
        return mount_of(self.request)

    def url(self, action, *args):
        """The address of one of the tab's routes, under the mount the page came by."""
        return reverse(self.resource.url_name(action, self.mount), args=args)

    def context(self, **extra):
        r, user = self.resource, self.request.user
        return {
            'resource': r, 'name': r.name, 'plural': r.plural, 'group': r.group(self.mount),
            'title': r.title(self.mount), 'empty_icon': r.icon,
            'list_url': self.url('list'),
            'create_url': self.url('create') if r.allows('add') else '',
            **{f'can_{action}': r.allows(action) and user.has_perm(r.perm(action))
               for action in ('add', 'change', 'delete')},
            **extra,
        }

    def get_object(self, pk):
        obj = get_object_or_404(self.resource.visible(self.request), pk=pk)
        if self.action in ('change', 'delete') and not self.resource.allowed(self.request, obj, self.action):
            raise PermissionDenied
        return obj

    def locked_object(self, pk):
        """The record, locked for the caller's transaction (not the rows it is joined to); 404 when it was deleted or
        left the person's reach since the page was opened (F-009: not a server error)."""
        return get_object_or_404(self.resource.visible(self.request).select_for_update(of=('self',)), pk=pk)


# NONE (core.widgets, imported above): a list filter's value for "records without one" (production departments
# without a site), the value a DependentSelect's source takes for the same.


def filter_by(request, objects, param, choices, lookup, allow_none=False):
    """Narrows `objects` to the value chosen in the `param` query parameter: a record of `choices` (a
    queryset) or one of `choices` given as (value, label) pairs; or (`allow_none`) to those without
    one. Anything else, a stale or malformed value, shows everything.
    Returns the objects and the value the filter shows as chosen."""
    chosen = request.GET.get(param, '')
    if allow_none and chosen == NONE:
        return objects.filter(**{f'{lookup}__isnull': True}), chosen
    if isinstance(choices, models.QuerySet):
        allowed = {str(pk) for pk in choices.values_list('pk', flat=True)}
    else:
        allowed = {str(value) for value, _label in choices}
    if chosen in allowed:
        return objects.filter(**{lookup: chosen}), chosen
    return objects, ''


class ListView(ResourceView):
    def get(self, request):
        query = request.GET.get('q', '').strip()
        objects = self.resource.list_queryset(request)
        if isinstance(objects, models.QuerySet):
            # A tab whose list is not a queryset (a union of two kinds, a week) narrows it to the rows the person may
            # reach in its own read; it cannot be narrowed afterwards.
            objects = self.resource.scoped(request, objects)
        if query:
            objects = self.resource.search(objects, query)
        objects, filters = self.resource.filter_list(request, objects)
        if isinstance(objects, models.QuerySet) and not objects.ordered:
            # A filter that counts with a GROUP BY drops the model's ordering (Django leaves Meta.ordering
            # out of such queries); the list is read and paged in it all the same, the key last. (A tab that
            # returns a list, e.g. in tree order, has put it in its order itself.)
            objects = objects.order_by(*self.resource.model._meta.ordering, 'pk')
        page = None
        if self.resource.page_size:
            # Paged on the server, after the search and the filters; the page links keep both.
            page = Paginator(objects, self.resource.page_size).get_page(request.GET.get('page'))
            objects = page.object_list
        kept = request.GET.copy()
        kept.pop('page', None)
        context = self.context(objects=objects, query=query, page=page, pager_query=kept.urlencode(), **filters)
        if self.resource.list_rows is not None and is_next(request):
            # The new look's list page (core/listprops.py): the same rows, read by the same view, drawn by the island.
            return render_page(request, 'crud/list_next.html',
                               {**context, 'props': listprops.list_props(self, objects, context),
                                'list_above': self.resource.list_above_next})
        if self.resource.list_template_next and is_next(request):
            props = self.resource.list_next_props(self, objects, context) if self.resource.list_next_props else None
            return render_page(request, self.resource.list_template_next, {**context, 'props': props})
        return render_page(request, self.resource.list_template, context)


class FormView(ResourceView):
    def page(self, form, obj=None, **extra):
        """The record's form as a page. `form_action` is where the record's own form posts: its edit address, or the
        create address for a new record, never "the address of this page": the page is also shown from another address
        (a refused row list, a protocol's table, an experiment's team: `UpdateView.as_page`), and the record's Save
        then went to that address and failed (flow fault B-04)."""
        r = self.resource
        history = []
        if obj is not None:
            history = AuditLog.objects.filter(entity_type=r.entity_type(), entity_id=str(obj.pk))[:20]
            extra = {**r.edit_extras(self.request, obj), **extra}
        # A tab without the route (it cannot be edited, or created) never shows this form from another address.
        if obj is not None and obj.pk is not None and r.allows('change'):
            action = self.url('edit', obj.pk)
        else:
            action = self.url('create') if obj is None and r.allows('add') else self.request.path
        panels = r.next_panels(self, form, obj, extra) if not is_modal(self.request) and is_next(self.request) else None
        if formprops.drawable(r, form, extra, panels):
            # The new look's record form (core/formprops.py): the same form, view and address, drawn by the island, with
            # the panels the tab's own template adds (core/formpanels.py) and the question a refused save asks.
            return render_page(self.request, 'crud/form_next.html', self.context(
                form=form, object=obj, props=formprops.record_form_props(
                    self.request, form, action=action, name=r.name, obj=obj, list_url=self.url('list'),
                    delete_url=self.url('delete', obj.pk) if obj is not None and obj.pk is not None and r.allows('delete')
                    and self.request.user.has_perm(r.perm('delete')) and r.allowed(self.request, obj, 'delete') else '',
                    history=history,
                    history_url=f"{reverse('core:activity_log')}?type={quote(r.entity_type(), safe='/')}&q={quote(str(obj), safe='/')}"
                    if obj is not None else '', open_tab=extra.get('open_tab', ''), panels=panels,
                    question=formpanels.question(extra.get('withdrawal_change')) if extra.get('question_template') else None)))
        # The words of the tab's row lists (RowList.words): one source for both looks, read by crud/_row_list.html and
        # farm/_contacts.html as `row_words.<key>`.
        row_words = {rows.key: formpanels.template_words(formpanels.list_words(rows, obj)) for rows in r.row_lists}
        return render_page(self.request, r.form_template, self.context(
            form=form, object=obj, history=history, form_action=action, row_words=row_words, **extra))

    def draft_page(self, form, obj=None):
        """The form rendered again from a draft (TabbedForm.refresh_on), open on the tab of the field
        whose change asked for it: the draft marker carries that field's name."""
        return self.page(form, obj, open_tab=form.tab_of(self.request.POST.get(DRAFT, '')))


class CreateView(FormView):
    action = 'add'

    def get(self, request):
        return self.page(self.resource.form(request))

    def created(self, obj):
        """Where the person goes once the record exists: its edit page when they may edit it; else its own page when the
        tab has one; else the list. A person whose role creates and does not edit (a worker filing a leave request) was
        sent to the edit page and met a refusal (flow fault M-18)."""
        r, request = self.resource, self.request
        if r.allows('change') and request.user.has_perm(r.perm('change')) and r.allowed(request, obj, 'change'):
            return done(request, self.url('edit', obj.pk), stay=True)
        if r.detail_template:
            return done(request, self.url('detail', obj.pk))
        return done(request, self.url('list'))

    def refused(self, form):
        """The form again after a refusal at the save (the database, the service, a rule under a lock): 422, as an
        edit's refusal answers; a form that is not valid is the page again as before."""
        response = self.page(form)
        response.status_code = 422
        return response

    def post(self, request):
        r = self.resource
        if DRAFT in request.POST:    # TabbedForm.refresh_on: the form again with what was entered
            return self.draft_page(r.form(request, draft=request.POST))
        form = r.form(request, request.POST, request.FILES)
        # Looked up before the form is checked again: a second sending would be refused as a clash with its own first
        # record (a code taken).
        sent = form.sent_before()
        if sent is None and not form.is_valid():
            return self.page(form)
        if sent is None:
            try:
                with transaction.atomic():
                    if r.service_writes:
                        obj = r.create_record(request, form)
                        form.note_sent(obj)
                    else:
                        obj = form.save(commit=False)
                        for field in ('created_by', 'updated_by'):
                            if hasattr(obj, field):
                                setattr(obj, field, request.user)
                        obj.save()
                        form.note_sent(obj)
                        form.save_m2m()
                        audit.record_create(request.user, obj, r.recorded(obj), entity_type=r.entity_type())
                        r.after_save(request, obj, created=True)
            except IntegrityError as error:
                # The same form sent twice at once: the other request's insert held the key's unique index until it
                # committed, so its record is there now.
                sent = form.sent_before()
                if sent is None:
                    # Two people saving the same record at once both pass the form's checks; the database's constraint
                    # refuses the second, and it is told why on the form instead of a server error; so is a rule the
                    # database holds across tables (a unit in a department being deleted, farm 0030). Any other
                    # refusal is a fault.
                    if not (constraint_error(form, error) or trigger_refusal(form, error)):
                        raise
                    form.instance._state.adding = True     # the page is the new-record form again
                    return self.refused(form)
            except ValidationError as error:
                # Its key stands for a record of another kind (EntryKey.note), the service refused it, or a rule
                # `after_save` checks under its lock refused it: nothing was written.
                refusal_on_form(form, error)
                form.instance._state.adding = True
                return self.refused(form)
            else:
                r.after_commit(request, obj, created=True)
                # Translators: %(name)s is the kind of record, capitalised (e.g. Site); %(object)s is the record.
                flash(request, _('%(name)s “%(object)s” created.'), r, obj)
                return self.created(obj)
        # Sent before: the record the first sending created, as that sending showed it.
        if getattr(sent, 'is_deleted', False):
            return done(request, self.url('list'))
        return self.created(sent)


class Crossed(Exception):
    """The record changed between the edit's first read and its lock: the edit crossed another one."""


class Clashed(Exception):
    """The edit's save met a database constraint another save just took (two records given one code): the form says
    which (F-034)."""


class UpdateView(FormView):
    action = 'change'

    def get(self, request, pk):
        obj = self.get_object(pk)
        return self.page(self.resource.form(request, instance=obj), obj)

    def post(self, request, pk):
        r = self.resource
        obj = self.get_object(pk)
        if DRAFT in request.POST:    # TabbedForm.refresh_on: the form again with what was entered
            return self.draft_page(r.form(request, instance=obj, draft=request.POST), obj)
        form = r.form(request, request.POST, request.FILES, instance=obj)
        if not form.is_valid():
            return self.page(form, obj)
        versioned = 'version' in form.fields
        try:
            with transaction.atomic():
                # What the edit may reach is worked out from the record as read here, and what it reaches is locked
                # first (Resource.edited: the fish before the record, as a stock operation locks them). The record is
                # locked in write(): changed meanwhile (its version moved), the edit is refused as any edit that
                # crossed another; deleted meanwhile, it is not found (404, F-009).
                read = get_object_or_404(r.visible(request), pk=pk)

                def write():
                    current = self.locked_object(pk)
                    if versioned and form.cleaned_data.get('version') != current.version \
                            or getattr(read, 'version', None) != getattr(current, 'version', None):
                        raise Crossed
                    if r.service_writes:
                        return r.change_record(request, form, current)
                    before = r.recorded(current)
                    obj = form.save(commit=False)
                    if versioned:
                        obj.version = current.version + 1
                    if hasattr(obj, 'updated_by'):
                        obj.updated_by = request.user
                    try:
                        with transaction.atomic():
                            obj.save()
                    except IntegrityError as error:
                        # Two people giving two records the same code at once both pass the form's checks; the
                        # database's constraint refuses the second, told on the form as on a new record (F-034). Any
                        # other refusal goes on to the trigger check below.
                        if not constraint_error(form, error):
                            raise
                        raise Clashed from None
                    form.save_m2m()
                    audit.record_update(request.user, obj, before, r.recorded(obj), entity_type=r.entity_type(),
                                        severity=r.change_severity(current, obj))
                    r.after_save(request, obj, created=False)
                    return obj

                obj = r.edited(request, read, write,
                               request.POST.get(r.question_field, '') if r.question_field else None)
        except Clashed:
            return self.page(form, self.get_object(pk))
        except Crossed:
            # Translators: %(name)s is the kind of record in lower case (e.g. site).
            messages.error(request, _('Someone else changed this %(name)s while you were editing it. '
                                      'The form now shows their version; make your changes again.')
                           % {'name': r.name})
            return done(request, self.url('edit', pk))
        except ValidationError as error:
            # The save asked something first (Resource.edited), or the service refused it: the form again with the
            # question or the reason, nothing saved.
            refusal_on_form(form, error)
            response = self.page(form, self.get_object(pk), withdrawal_change=getattr(error, 'change', None),
                                 question_template=r.question_template)
            response.status_code = 422
            return response
        except IntegrityError as error:
            # A rule the database holds across tables refused the change: said on the form, nothing saved.
            if not trigger_refusal(form, error):
                raise
            return self.page(form, self.get_object(pk))
        r.after_commit(request, obj, created=False)
        # Translators: %(name)s is the kind of record, capitalised (e.g. Site); %(object)s is the record.
        flash(request, _('%(name)s “%(object)s” saved.'), r, obj)
        return done(request, self.url('list'))


class DetailView(ResourceView):
    """One record as a person who may read the tab sees it (Resource.detail_template), with links to edit
    and delete it for those who may."""

    def get(self, request, pk):
        r = self.resource
        obj = self.get_object(pk)
        urls = {f'{action}_url': self.url(action, obj.pk) for action in ('edit', 'delete')
                if r.allows({'edit': 'change'}.get(action, action))}
        return render_page(request, r.detail_template, self.context(object=obj, **urls, **r.detail_extras(request, obj)))


class DeleteView(ResourceView):
    action = 'delete'

    def get(self, request, pk):
        obj = self.get_object(pk)
        plan = plan_delete(obj) if isinstance(obj, AuditedModel) else None
        if not is_modal(request) and is_next(request):
            return render_page(request, 'crud/confirm_delete_next.html', self.context(
                object=obj, props=formprops.confirm_delete_props(request, obj, plan, name=self.resource.name,
                                                                 action=request.path, cancel=self.url('list'))))
        return render_page(request, 'crud/confirm_delete.html', self.context(object=obj, plan=plan))

    def post(self, request, pk):
        r = self.resource
        if r.service_writes:
            # The service locks in its own order (HR: the person before the record) and logs; a refusal is said.
            try:
                with transaction.atomic():
                    obj = self.get_object(pk)
                    r.delete_record(request, obj)
            except ValidationError as error:
                messages.error(request, ' '.join(error.messages))
                return done(request, self.url('list'))
            # Translators: %(name)s is the kind of record, capitalised (e.g. Site); %(object)s is the record.
            flash(request, _('%(name)s “%(object)s” deleted.'), r, obj)
            return done(request, self.url('list'))
        with transaction.atomic():
            # What the delete takes along is locked before the record itself, the deepest first (core.softdelete,
            # LOCK ORDER), as a unit's save locks the unit before its department.
            read = self.get_object(pk)
            if isinstance(read, AuditedModel):
                softdelete.lock_along(plan_delete(read))
            obj = self.locked_object(pk)
            if not r.allowed(request, obj, 'delete'):
                raise PermissionDenied
            if isinstance(obj, AuditedModel):
                plan = plan_delete(obj)
                if not plan.can_delete:
                    # Translators: %(name)s is the kind of record, capitalised (e.g. Site); %(object)s is the
                    # record; %(reasons)s are sentences saying what is in the way.
                    messages.error(request, _('%(name)s “%(object)s” cannot be deleted: %(reasons)s') % {
                        'name': capfirst(r.name), 'object': obj, 'reasons': ' '.join(plan.blockers)})
                    return done(request, self.url('list'))
                softdelete.execute(plan, request.user)
            else:
                try:
                    with transaction.atomic():
                        # Logged first: a hard delete clears the object's primary key.
                        audit.record_delete(request.user, obj, entity_type=r.entity_type())
                        obj.delete()
                except models.ProtectedError as error:
                    # A record that keeps pointing at it (a role an alarm recipient rule names) holds it: said, not a 500.
                    kinds = sorted({str(capfirst(record._meta.verbose_name_plural)) for record in error.protected_objects})
                    messages.error(request, _('%(name)s “%(object)s” cannot be deleted: %(reasons)s') % {
                        'name': capfirst(r.name), 'object': obj,
                        'reasons': _('%(records)s still use it.') % {'records': ', '.join(kinds)}})
                    return done(request, self.url('list'))
        # Translators: %(name)s is the kind of record, capitalised (e.g. Site); %(object)s is the record.
        flash(request, _('%(name)s “%(object)s” deleted.'), r, obj)
        return done(request, self.url('list'))


class RowListView(ResourceView):
    """Saves a RowList of a record. Editing its rows is part of editing the record, so it needs the
    record's change permission."""

    action = 'change'
    rows = None

    def get(self, request, pk):
        return redirect(self.url('edit', pk))

    def post(self, request, pk):
        r, rows = self.resource, self.rows
        obj = self.get_object(pk)
        if not rows.applies_to(obj):
            raise Http404
        if not rows.allowed(request, obj):
            raise PermissionDenied
        formset = rows.formset(request.POST, instance=obj, prefix=rows.key)
        if not formset.is_valid():
            page = UpdateView.as_page(r, request)
            return page.page(r.form(request, instance=obj), obj, **{rows.key: formset, 'open_tab': rows.tab})
        kept = formset.kept_rows()
        with transaction.atomic():
            # As an edit of the record: locked, refused when it changed since the list was opened (its version
            # travels with the list), its version moved on. Asked again under the lock whether the record has
            # the list: a report filed meanwhile has no answers to change any more.
            current = self.locked_object(pk)
            versioned = isinstance(current, AuditedModel)
            if versioned and request.POST.get('version') != str(current.version):
                # Translators: %(name)s is the kind of record in lower case (e.g. site).
                messages.error(request, _('Someone else changed this %(name)s while you were editing it. '
                                          'The form now shows their version; make your changes again.')
                               % {'name': r.name})
                return done(request, self.url('edit', pk), stay=True)
            if not rows.applies_to(current):
                raise Http404
            try:
                with transaction.atomic():
                    asked = {'seen': request.POST.get(rows.question_field, '')} if rows.question_field else {}
                    rows.save(request.user, current, kept, r.entity_type(), **asked)
            except ValidationError as error:
                # A list whose save asks something first (a medicine's withdrawal rows and the withdrawal guard): the
                # page again with the reason and what was found (`withdrawal_change`), nothing saved.
                formset._non_form_errors = formset.error_class(error.messages)
                page = UpdateView.as_page(r, request)
                response = page.page(r.form(request, instance=obj), obj, **{rows.key: formset, 'open_tab': rows.tab,
                                                                          'withdrawal_change': getattr(error, 'change', None)})
                response.status_code = 422
                return response
            if versioned:
                current.version += 1
                current.updated_by = request.user
                current.save(update_fields=['version', 'updated_by', 'updated_at'])
        messages.success(request, rows.saved % {'count': len(kept)})
        return done(request, self.url('edit', pk), stay=True)
