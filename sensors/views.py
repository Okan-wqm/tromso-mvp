"""The Sensors panel's pages beyond its tabs: the overview, and a credential's secret, shown once when it is made or
replaced and never again."""
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core import audit, navigation
from core.crud import done, render_page
from core.models import AuditLog

from . import credentials
from .models import Credential
from .resources import (ChannelResource, ConnectionResource, CredentialResource, DeviceResource, PayloadFormatResource,
                        secret_page)

# How the activity log says a secret changed: never its value or its hash.
SECRET_LABEL, REPLACED = 'Secret', '(replaced)'


def _context(url_name, **extra):
    place = navigation.page(url_name)
    return {'title': place.entry.label, 'eyebrow': f'{place.workspace.label} · {place.entry.label}', **extra}


def home(request):
    """The Sensors overview: the configuration counted, for the parts the person may read (every signed-in person may
    open it; the panel is offered to those who can use something in it)."""
    tiles = [{'label': resource.title(), 'count': resource.model.objects.count(), 'url': reverse(resource.url_name('list'))}
             for resource in (ConnectionResource, DeviceResource, ChannelResource, PayloadFormatResource)
             if request.user.has_perm(resource.perm('view'))]
    return render_page(request, 'sensors/home.html', _context('sensors:home', setup_tiles=tiles))


@require_POST
@permission_required(CredentialResource.perm('change'), raise_exception=True)
def credential_rotate(request, pk):
    """Replaces a credential's secret: refused when the credential changed since the page was opened (its version), logged
    without any value, the new secret shown once. The broker takes it when its files are written again
    (`manage.py sensor_broker_sync`)."""
    with transaction.atomic():
        credential = get_object_or_404(Credential.objects.select_for_update(), pk=pk)
        if request.POST.get('version') != str(credential.version):
            messages.error(request, _('Someone else changed this %(name)s while you were editing it. The form now shows '
                                      'their version; make your changes again.') % {'name': CredentialResource.name})
            return done(request, reverse(CredentialResource.url_name('edit'), args=[pk]))
        secret = credentials.give_secret(credential)
        credential.version += 1
        credential.updated_by = request.user
        credential.save(update_fields=['version', 'updated_by', 'updated_at'])
        with audit.source_language():
            audit.record(request.user, AuditLog.Action.UPDATE, credential, {SECRET_LABEL: [REPLACED, REPLACED]},
                         entity_type=CredentialResource.entity_type())
    return secret_page(request, CredentialResource, credential, secret, rotated=True)
