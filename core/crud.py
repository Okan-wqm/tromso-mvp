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
  edit page and a logged save (RowList).
"""
import copy
from dataclasses import dataclass, field as dataclass_field

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import models, transaction
from django.db.models import F, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.text import capfirst
from django.utils.translation import gettext as _

from . import audit, navigation, softdelete
from .models import AuditedModel, AuditLog
from .softdelete import plan_delete


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
    existing record (a production department stays on its site).

    `refresh_on` names fields whose value changes the form itself (an equipment type decides its
    specification fields): changing one posts the form with the `_draft` marker and the server renders
    it again with everything entered so far, validating and saving nothing (frontend/components.ts,
    data-refresh). The values travel in the request body, not the address, so long texts fit and stay out
    of access logs. They reach the form as a `draft`; an unbound form starts from them instead of the
    stored record. The marker carries the name of the field that changed, and the form opens again on
    that field's tab.

    A form can drop fields for one record (`del self.fields[name]` in `__init__`, e.g. the measures a
    pond does not have); the tabs then show the fields it kept, and a heading left without fields goes."""

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
        self._check_conditional_unique(cleaned)
        return cleaned

    def _check_conditional_unique(self, cleaned):
        """Conditional unique constraints, e.g. "code unique among live records", or "scientific name
        unique among live records whatever its case" (a constraint on an expression, Lower(...)).
        Django leaves them out of form validation when the condition uses a field the form does not
        edit (is_deleted), so check them here: the record as the form would save it, by the constraint
        itself. The error goes on the constraint's last field the form shows, with its message."""
        model = self._meta.model
        for constraint in model._meta.constraints:
            if not isinstance(constraint, models.UniqueConstraint) or constraint.condition is None:
                continue
            names = constrained_fields(constraint)
            candidate = copy.copy(self.instance)
            for name in names:
                value = cleaned.get(name) if name in self.fields else getattr(self.instance, name, None)
                if value in (None, ''):
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


def constrained_fields(constraint):
    """The fields a unique constraint covers: its `fields`, or the fields its expressions read
    (Lower('scientific_name') covers scientific_name)."""
    if constraint.fields:
        return list(constraint.fields)
    return [node.name for expression in constraint.expressions for node in expression.flatten()
            if isinstance(node, F)]


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

    @classmethod
    def applies_to(cls, obj):
        """Whether the record has this list at all (only a feeder has calibrations)."""
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
    def save(cls, user, obj, rows, entity_type):
        """Replaces the stored rows with `rows` (cleaned data) and logs the change on `obj`."""
        model, link = cls.formset.model, cls.formset.fk.name
        # The row's own fields; an inline formset adds the link to its parent to the form's fields.
        fields = [name for name in cls.formset.form._meta.fields if name != link]
        with transaction.atomic(), audit.source_language():
            before = cls.summary(obj)
            cls.rows(obj).delete()
            model.objects.bulk_create([
                model(**{link: obj, 'created_by': user}, **{name: row[name] for name in fields}) for row in rows
            ])
            after = cls.summary(obj)
            if before != after:
                audit.record(user, AuditLog.Action.UPDATE, obj, {str(cls.label): [before, after]},
                             entity_type=entity_type)


class Resource:
    """A farm tab. Subclass and set the attributes; `urls()` gives its URL patterns."""

    registry = []         # every declared tab; the tab rules in core/tests.py check each one

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        Resource.registry.append(cls)

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
    row_lists = ()        # RowList classes edited on the record's tabs (a site's contacts)
    page_size = None      # rows per page of the list; None lists every record on one page (nested lists)

    # --- names derived from the model -------------------------------------------------------
    @classmethod
    def perm(cls, action):
        meta = cls.model._meta
        return f'{meta.app_label}.{action}_{meta.model_name}'

    @classmethod
    def url_name(cls, action):
        return f'{cls.namespace or cls.model._meta.app_label}:{cls.model._meta.model_name}_{action}'

    @classmethod
    def group(cls):
        """The menu group the tab's page sits in, shown above its heading, e.g. _('Facility')."""
        return navigation.place(cls.perm('view')).group.label

    @classmethod
    def title(cls):
        """The page's heading: the menu entry's label, so the page is called what the menu calls it
        (e.g. Tanks, ponds & cages, whose records are units)."""
        return navigation.place(cls.perm('view')).entry.label

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
    def form(cls, request, *args, **kwargs):
        """The tab's form; override to hand it more, e.g. who is editing."""
        return cls.form_class(*args, **kwargs)

    @classmethod
    def edit_extras(cls, request, obj):
        """Extra context for the edit page: the formsets of its row lists, and whatever a tab adds."""
        return {rows.key: rows.formset(instance=obj, prefix=rows.key) for rows in cls.row_lists if rows.applies_to(obj)}

    @classmethod
    def snapshot(cls, obj):
        """What the audit log compares before and after a save: the form's fields under its labels."""
        return audit.snapshot(obj, tab_fields(cls.form_class.tabs), getattr(cls.form_class.Meta, 'labels', {}))

    @classmethod
    def recorded(cls, obj):
        """The snapshot as the audit log stores it, built in the source language."""
        with audit.source_language():
            return cls.snapshot(obj)

    @classmethod
    def after_save(cls, request, obj, created):
        """Runs inside the save transaction, after the audit row; e.g. invite a new user."""

    @classmethod
    def filter_list(cls, request, objects):
        """Narrows the list by the tab's own filters; returns the objects and context for the filter bar."""
        return objects, {}

    # --- URLs ---------------------------------------------------------------------------------
    @classmethod
    def urls(cls):
        p, n = cls.url_prefix, cls.model._meta.model_name
        pk = 'uuid:pk' if isinstance(cls.model._meta.pk, models.UUIDField) else 'int:pk'
        routes = {
            'list': path(f'{p}/', ListView.as_view(resource=cls), name=f'{n}_list'),
            'add': path(f'{p}/new/', CreateView.as_view(resource=cls), name=f'{n}_create'),
            'change': path(f'{p}/<{pk}>/', UpdateView.as_view(resource=cls), name=f'{n}_edit'),
            'delete': path(f'{p}/<{pk}>/delete/', DeleteView.as_view(resource=cls), name=f'{n}_delete'),
        }
        rows = [path(f'{p}/<{pk}>/{row_list.key}/', RowListView.as_view(resource=cls, rows=row_list),
                     name=f'{n}_{row_list.key}') for row_list in cls.row_lists] if cls.allows('change') else []
        return [route for action, route in routes.items() if action == 'list' or cls.allows(action)] + rows


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

    def context(self, **extra):
        r, user = self.resource, self.request.user
        return {
            'resource': r, 'name': r.name, 'plural': r.plural, 'group': r.group(), 'title': r.title(),
            'empty_icon': r.icon,
            'list_url': reverse(r.url_name('list')),
            'create_url': reverse(r.url_name('create')) if r.allows('add') else '',
            **{f'can_{action}': r.allows(action) and user.has_perm(r.perm(action))
               for action in ('add', 'change', 'delete')},
            **extra,
        }

    def get_object(self, pk):
        return get_object_or_404(self.resource.queryset(), pk=pk)


NONE = 'none'   # a list filter's value for "records without one" (production departments without a site)


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
        if query:
            condition = Q()
            for field in self.resource.search_fields:
                condition |= Q(**{f'{field}__icontains': query})
            objects = objects.filter(condition)
        objects, filters = self.resource.filter_list(request, objects)
        page = None
        if self.resource.page_size:
            # Paged on the server, after the search and the filters; the page links keep both.
            page = Paginator(objects, self.resource.page_size).get_page(request.GET.get('page'))
            objects = page.object_list
        kept = request.GET.copy()
        kept.pop('page', None)
        return render_page(request, self.resource.list_template, self.context(
            objects=objects, query=query, page=page, pager_query=kept.urlencode(), **filters))


class FormView(ResourceView):
    def page(self, form, obj=None, **extra):
        r = self.resource
        history = []
        if obj is not None:
            history = AuditLog.objects.filter(entity_type=r.entity_type(), entity_id=str(obj.pk))[:20]
            extra = {**r.edit_extras(self.request, obj), **extra}
        return render_page(self.request, r.form_template, self.context(form=form, object=obj, history=history, **extra))

    def draft_page(self, form, obj=None):
        """The form rendered again from a draft (TabbedForm.refresh_on), open on the tab of the field
        whose change asked for it: the draft marker carries that field's name."""
        return self.page(form, obj, open_tab=form.tab_of(self.request.POST.get(DRAFT, '')))


class CreateView(FormView):
    action = 'add'

    def get(self, request):
        return self.page(self.resource.form(request))

    def post(self, request):
        r = self.resource
        if DRAFT in request.POST:    # TabbedForm.refresh_on: the form again with what was entered
            return self.draft_page(r.form(request, draft=request.POST))
        form = r.form(request, request.POST)
        if not form.is_valid():
            return self.page(form)
        with transaction.atomic():
            obj = form.save(commit=False)
            for field in ('created_by', 'updated_by'):
                if hasattr(obj, field):
                    setattr(obj, field, request.user)
            obj.save()
            form.save_m2m()
            audit.record_create(request.user, obj, r.recorded(obj), entity_type=r.entity_type())
            r.after_save(request, obj, created=True)
        # Translators: %(name)s is the kind of record, capitalised (e.g. Site); %(object)s is the record.
        flash(request, _('%(name)s “%(object)s” created.'), r, obj)
        return done(request, reverse(r.url_name('edit'), args=[obj.pk]), stay=True)


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
        form = r.form(request, request.POST, instance=obj)
        if not form.is_valid():
            return self.page(form, obj)
        with transaction.atomic():
            current = r.queryset().select_for_update(of=('self',)).get(pk=pk)   # not the joined rows
            versioned = 'version' in form.fields
            if versioned and form.cleaned_data.get('version') != current.version:
                # Translators: %(name)s is the kind of record in lower case (e.g. site).
                messages.error(request, _('Someone else changed this %(name)s while you were editing it. '
                                          'The form now shows their version; make your changes again.')
                               % {'name': r.name})
                return done(request, reverse(r.url_name('edit'), args=[pk]))
            before = r.recorded(current)
            obj = form.save(commit=False)
            if versioned:
                obj.version = current.version + 1
            if hasattr(obj, 'updated_by'):
                obj.updated_by = request.user
            obj.save()
            form.save_m2m()
            audit.record_update(request.user, obj, before, r.recorded(obj), entity_type=r.entity_type())
            r.after_save(request, obj, created=False)
        # Translators: %(name)s is the kind of record, capitalised (e.g. Site); %(object)s is the record.
        flash(request, _('%(name)s “%(object)s” saved.'), r, obj)
        return done(request, reverse(r.url_name('list')))


class DeleteView(ResourceView):
    action = 'delete'

    def get(self, request, pk):
        obj = self.get_object(pk)
        plan = plan_delete(obj) if isinstance(obj, AuditedModel) else None
        return render_page(request, 'crud/confirm_delete.html', self.context(object=obj, plan=plan))

    def post(self, request, pk):
        r = self.resource
        with transaction.atomic():
            obj = get_object_or_404(r.queryset().select_for_update(of=('self',)), pk=pk)
            if isinstance(obj, AuditedModel):
                plan = plan_delete(obj)
                if not plan.can_delete:
                    # Translators: %(name)s is the kind of record, capitalised (e.g. Site); %(object)s is the
                    # record; %(reasons)s are sentences saying what is in the way.
                    messages.error(request, _('%(name)s “%(object)s” cannot be deleted: %(reasons)s') % {
                        'name': capfirst(r.name), 'object': obj, 'reasons': ' '.join(plan.blockers)})
                    return done(request, reverse(r.url_name('list')))
                softdelete.execute(plan, request.user)
            else:
                # Logged first: a hard delete clears the object's primary key.
                audit.record_delete(request.user, obj, entity_type=r.entity_type())
                obj.delete()
        # Translators: %(name)s is the kind of record, capitalised (e.g. Site); %(object)s is the record.
        flash(request, _('%(name)s “%(object)s” deleted.'), r, obj)
        return done(request, reverse(r.url_name('list')))


class RowListView(ResourceView):
    """Saves a RowList of a record. Editing its rows is part of editing the record, so it needs the
    record's change permission."""

    action = 'change'
    rows = None

    def get(self, request, pk):
        return redirect(reverse(self.resource.url_name('edit'), args=[pk]))

    def post(self, request, pk):
        r, rows = self.resource, self.rows
        obj = self.get_object(pk)
        if not rows.applies_to(obj):
            raise Http404
        formset = rows.formset(request.POST, instance=obj, prefix=rows.key)
        if not formset.is_valid():
            page = UpdateView.as_page(r, request)
            return page.page(r.form(request, instance=obj), obj, **{rows.key: formset, 'open_tab': rows.tab})
        kept = formset.kept_rows()
        rows.save(request.user, obj, kept, r.entity_type())
        messages.success(request, rows.saved % {'count': len(kept)})
        return done(request, reverse(r.url_name('edit'), args=[pk]), stay=True)
