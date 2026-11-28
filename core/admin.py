from django.apps import apps
from django.contrib import admin, messages
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _, ngettext

from . import softdelete
from .models import AuditedModel


class ReadOnlyAdmin(admin.ModelAdmin):
    """Shows records and changes nothing: farm records are changed on their own screens, where every
    change is written to the activity log, and reference data (equipment types) by migrations."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class AuditedModelAdmin(ReadOnlyAdmin):
    """Admin for farm records: deleted ones are shown too, and a platform admin can restore them.
    It is read-only on purpose: an edit here would not be in the activity log."""

    list_filter = ['is_deleted']
    actions = ['restore']

    def get_queryset(self, request):
        return self.model.all_objects.all()

    def has_restore_permission(self, request):
        return request.user.has_perm(f'{self.opts.app_label}.change_{self.opts.model_name}')

    @admin.action(description=_('Restore the selected deleted records'), permissions=['restore'])
    def restore(self, request, queryset):
        restored = 0
        for record in queryset.filter(is_deleted=True):
            try:
                with transaction.atomic():
                    softdelete.restore(record, request.user)
            except ValidationError as error:
                self.message_user(request, _('%(record)s was not restored: %(reasons)s') % {
                    'record': record, 'reasons': ' '.join(error.messages)}, messages.ERROR)
            else:
                restored += 1
        if restored:
            self.message_user(request, ngettext('%(count)d record restored.', '%(count)d records restored.',
                                                restored) % {'count': restored}, messages.SUCCESS)


def register_audited(app_label):
    """Registers every farm record of an app (an AuditedModel) with the admin. A model its service alone writes
    (`service_written`) is listed read-only with no Restore action: brought back here it would skip the service's
    rules, so a voided record of it is entered again on its page (core.softdelete.restore refuses one all the same)."""
    for model in apps.get_app_config(app_label).get_models():
        if issubclass(model, AuditedModel):
            fields = {field.name for field in model._meta.concrete_fields}
            name = getattr(model, 'name_field', 'name')    # a species is named by its common name
            admin.site.register(model, type(f'{model.__name__}Admin', (AuditedModelAdmin,), {
                **({'actions': []} if model.service_written else {}),
                'list_display': [
                    field for field in (name, 'code', 'type', 'status', 'is_deleted') if field in fields
                ] or ['__str__', 'is_deleted'],
                'search_fields': [field for field in (name, 'code') if field in fields],
            }))


# Users and roles are managed on their own screens (Administration), where every change is written to
# the activity log; Django's stock admin for them would change them without a trace.
admin.site.unregister([User, Group])

# The platform owner's settings: a row a restore left deleted comes back here.
register_audited('core')
