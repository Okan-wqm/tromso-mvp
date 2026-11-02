from django.apps import apps
from django.contrib import admin, messages
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.db import transaction

from . import softdelete
from .models import AuditedModel


class AuditedModelAdmin(admin.ModelAdmin):
    """Admin for farm records: deleted ones are shown too, and a platform admin can restore them.
    It is read-only on purpose: records are changed on their own screens, where every change is
    written to the activity log; an edit here would not be."""

    list_filter = ['is_deleted']
    actions = ['restore']

    def get_queryset(self, request):
        return self.model.all_objects.all()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_restore_permission(self, request):
        return request.user.has_perm(f'{self.opts.app_label}.change_{self.opts.model_name}')

    @admin.action(description='Restore the selected deleted records', permissions=['restore'])
    def restore(self, request, queryset):
        restored = 0
        for record in queryset.filter(is_deleted=True):
            try:
                with transaction.atomic():
                    softdelete.restore(record, request.user)
            except ValidationError as error:
                self.message_user(request, f'{record} was not restored: {" ".join(error.messages)}', messages.ERROR)
            else:
                restored += 1
        if restored:
            self.message_user(request, f'Restored {restored} record(s).', messages.SUCCESS)


def register_audited(app_label):
    """Registers every farm record of an app (an AuditedModel) with the admin."""
    for model in apps.get_app_config(app_label).get_models():
        if issubclass(model, AuditedModel):
            admin.site.register(model, type(f'{model.__name__}Admin', (AuditedModelAdmin,), {
                'list_display': [
                    field.name for field in model._meta.concrete_fields
                    if field.name in ('name', 'code', 'type', 'status', 'is_deleted')
                ] or ['__str__', 'is_deleted'],
                'search_fields': [name for name in ('name', 'code') if model._meta.get_field(name)],
            }))


# Users and roles are managed on their own screens (Administration), where every change is written to
# the activity log; Django's stock admin for them would change them without a trace.
admin.site.unregister([User, Group])
