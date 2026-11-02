"""One format for every farm tab: list, create, edit and delete pages built from a `Resource`.

A tab declares its model, form, labels and list template once; these views add what every tab
needs the same way:
- permissions: the role must hold view/add/change/delete on the model (the platform admin holds all);
- audit log: every create, change and delete is recorded in the same transaction;
- optimistic locking: a save based on an outdated `version` is refused;
- soft delete: models with `soft_delete()` are hidden, not erased;
- modal or page: opened from a `data-modal` link the same view renders inside a dialog, opened
  directly it renders as a full page (see core/templates and static/js/components.js).
"""
from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import models, transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse

from . import audit, softdelete
from .models import AuditedModel, AuditLog
from .softdelete import plan_delete

STALE_MESSAGE = ('Someone else changed this {name} while you were editing it. '
                 'The form now shows their version; make your changes again.')


def is_modal(request):
    return request.headers.get('X-Modal') == '1'


def render_page(request, template, context):
    """Renders `template` inside the console page or, for a modal request, inside the dialog."""
    context.setdefault('base_template', 'modal_base.html' if is_modal(request) else 'app_base.html')
    return render(request, template, context)


def done(request, url, stay=False):
    """After a successful save. A page follows the redirect to `url`. A dialog either loads `url`
    into itself (`stay`, e.g. a new record opens for editing) or closes and reloads its page."""
    if is_modal(request):
        header = 'X-Modal-Load' if stay else 'X-Modal-Redirect'
        return HttpResponse(status=204, headers={header: url})
    return redirect(url)


class TabbedForm(forms.ModelForm):
    """A model form whose fields are split over inner tabs: `tabs = [(key, label, [fields])]`.
    `fixed_after_creation` names the fields chosen once: they are shown but cannot be changed on an
    existing record (a department stays on its site)."""

    tabs = []
    fixed_after_creation = ()
    version = forms.IntegerField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance._state.adding:
            for name in self.fixed_after_creation:
                self.fields[name].disabled = True
                self.fields[name].required = False
        if not any(f.name == 'version' for f in self._meta.model._meta.fields):
            del self.fields['version']
        elif not self.instance._state.adding and not self.is_bound:
            self.initial['version'] = self.instance.version

    def clean(self):
        cleaned = super().clean()
        self._check_conditional_unique(cleaned)
        return cleaned

    def _check_conditional_unique(self, cleaned):
        """Conditional unique constraints, e.g. "code unique among live records". Django leaves them
        out of form validation when the condition uses a field the form does not edit (is_deleted),
        so check them here against the same condition; the field error is the constraint's message."""
        model = self._meta.model
        for constraint in model._meta.constraints:
            if not isinstance(constraint, models.UniqueConstraint) or constraint.condition is None or not constraint.fields:
                continue
            values = {}
            for name in constraint.fields:
                value = cleaned.get(name) if name in self.fields else getattr(self.instance, name, None)
                if value in (None, ''):
                    break
                values[name] = value
            else:
                error_field = next((f for f in reversed(constraint.fields) if f in self.fields), None)
                if error_field is None or error_field in self.errors:
                    continue
                clash = model._base_manager.filter(constraint.condition, **values).exclude(pk=self.instance.pk)
                if clash.exists():
                    self.add_error(error_field, constraint.violation_error_message)

    def tab_list(self):
        """The inner tabs with their bound fields and whether any field on them has an error."""
        return [
            {'key': key, 'label': label, 'fields': [self[name] for name in names],
             'has_errors': any(name in self.errors for name in names)}
            for key, label, names in self.tabs
        ]


def tab_fields(tabs):
    return [name for _, _, names in tabs for name in names]


class Resource:
    """A farm tab. Subclass and set the attributes; `urls()` gives its URL patterns."""

    registry = []         # every declared tab; the tab rules in core/tests.py check each one

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        Resource.registry.append(cls)

    model = None
    form_class = None
    name = ''             # 'site'
    plural = ''           # 'sites'
    group = ''            # rail group and page eyebrow, e.g. 'Facility'
    url_prefix = ''       # 'sites'
    search_fields = []
    list_template = ''    # extends crud/list.html and fills the `items` block
    form_template = 'crud/form.html'
    icon = 'plus'         # shown in the empty list
    namespace = ''        # URL namespace; defaults to the model's app label
    actions = ('add', 'change', 'delete')   # what this tab offers besides the list

    # --- names derived from the model -------------------------------------------------------
    @classmethod
    def perm(cls, action):
        meta = cls.model._meta
        return f'{meta.app_label}.{action}_{meta.model_name}'

    @classmethod
    def url_name(cls, action):
        return f'{cls.namespace or cls.model._meta.app_label}:{cls.model._meta.model_name}_{action}'

    @classmethod
    def allows(cls, action):
        return action == 'view' or action in cls.actions

    @classmethod
    def entity_type(cls):
        """How the activity log names this kind of record."""
        return cls.name or audit.entity_type_of(cls.model)

    # --- extension points ---------------------------------------------------------------------
    @classmethod
    def queryset(cls):
        return cls.model._default_manager.all()

    @classmethod
    def form(cls, request, *args, **kwargs):
        """The tab's form; override to hand it more, e.g. who is editing."""
        return cls.form_class(*args, **kwargs)

    @classmethod
    def edit_extras(cls, request, obj):
        """Extra context for the edit page, e.g. inline lists shown on their own tab."""
        return {}

    @classmethod
    def snapshot(cls, obj):
        """What the audit log compares before and after a save: the form's fields under its labels."""
        return audit.snapshot(obj, tab_fields(cls.form_class.tabs), getattr(cls.form_class.Meta, 'labels', {}))

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
        return [route for action, route in routes.items() if action == 'list' or cls.allows(action)]


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
            'resource': r, 'name': r.name, 'plural': r.plural, 'group': r.group, 'empty_icon': r.icon,
            'list_url': reverse(r.url_name('list')),
            'create_url': reverse(r.url_name('create')) if r.allows('add') else '',
            **{f'can_{action}': r.allows(action) and user.has_perm(r.perm(action))
               for action in ('add', 'change', 'delete')},
            **extra,
        }

    def get_object(self, pk):
        return get_object_or_404(self.resource.queryset(), pk=pk)


class ListView(ResourceView):
    def get(self, request):
        query = request.GET.get('q', '').strip()
        objects = self.resource.queryset()
        if query:
            condition = Q()
            for field in self.resource.search_fields:
                condition |= Q(**{f'{field}__icontains': query})
            objects = objects.filter(condition)
        objects, filters = self.resource.filter_list(request, objects)
        return render_page(request, self.resource.list_template, self.context(objects=objects, query=query, **filters))


class FormView(ResourceView):
    def page(self, form, obj=None, **extra):
        r = self.resource
        history = []
        if obj is not None:
            history = AuditLog.objects.filter(entity_type=r.entity_type(), entity_id=str(obj.pk))[:20]
            extra = {**r.edit_extras(self.request, obj), **extra}
        return render_page(self.request, r.form_template, self.context(form=form, object=obj, history=history, **extra))


class CreateView(FormView):
    action = 'add'

    def get(self, request):
        return self.page(self.resource.form(request))

    def post(self, request):
        r = self.resource
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
            audit.record_create(request.user, obj, r.snapshot(obj), entity_type=r.entity_type())
            r.after_save(request, obj, created=True)
        messages.success(request, f'{r.name.capitalize()} “{obj}” created.')
        return done(request, reverse(r.url_name('edit'), args=[obj.pk]), stay=True)


class UpdateView(FormView):
    action = 'change'

    def get(self, request, pk):
        obj = self.get_object(pk)
        return self.page(self.resource.form(request, instance=obj), obj)

    def post(self, request, pk):
        r = self.resource
        obj = self.get_object(pk)
        form = r.form(request, request.POST, instance=obj)
        if not form.is_valid():
            return self.page(form, obj)
        with transaction.atomic():
            current = r.queryset().select_for_update(of=('self',)).get(pk=pk)   # not the joined rows
            versioned = 'version' in form.fields
            if versioned and form.cleaned_data.get('version') != current.version:
                messages.error(request, STALE_MESSAGE.format(name=r.name))
                return done(request, reverse(r.url_name('edit'), args=[pk]))
            before = r.snapshot(current)
            obj = form.save(commit=False)
            if versioned:
                obj.version = current.version + 1
            if hasattr(obj, 'updated_by'):
                obj.updated_by = request.user
            obj.save()
            form.save_m2m()
            audit.record_update(request.user, obj, before, r.snapshot(obj), entity_type=r.entity_type())
            r.after_save(request, obj, created=False)
        messages.success(request, f'{r.name.capitalize()} “{obj}” saved.')
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
                    messages.error(request, f'{r.name.capitalize()} “{obj}” cannot be deleted: {" ".join(plan.blockers)}')
                    return done(request, reverse(r.url_name('list')))
                softdelete.execute(plan, request.user)
            else:
                # Logged first: a hard delete clears the object's primary key.
                audit.record_delete(request.user, obj, entity_type=r.entity_type())
                obj.delete()
        messages.success(request, f'{r.name.capitalize()} “{obj}” deleted.')
        return done(request, reverse(r.url_name('list')))
