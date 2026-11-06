from datetime import datetime, time

from django.conf import settings
from django.contrib.auth.decorators import login_not_required, permission_required
from django.core.paginator import Paginator
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext
from django.views import i18n

from . import audit, query
from .language import is_supported, save_account_language
from .models import AuditLog


@login_not_required
def set_language(request):
    """Django's language switch (it sets the language cookie), which also saves the choice on the
    signed-in person's account. Open to everyone: the sign-in pages have it too."""
    response = i18n.set_language(request)
    chosen = response.cookies.get(settings.LANGUAGE_COOKIE_NAME)
    if chosen and is_supported(chosen.value) and request.user.is_authenticated:
        save_account_language(request.user, chosen.value)
    return response


def _day(value, end=False):
    day = query.day(value)
    if day is None:
        return None
    return timezone.make_aware(datetime.combine(day, time.max if end else time.min))


@permission_required('core.view_auditlog', raise_exception=True)
def activity_log(request):
    """Every recorded change, newest first, filterable by person, record type, action and dates."""
    readable = audit.readable(request.user)
    entries = readable
    filters = {key: request.GET.get(key, '').strip()
               for key in ('q', 'user', 'type', 'action', 'severity', 'from', 'to')}
    if filters['q']:
        entries = entries.filter(entity_label__icontains=filters['q'])
    if filters['user']:
        entries = entries.filter(user_name=filters['user'])
    if filters['type']:
        entries = entries.filter(entity_type=filters['type'])
    if filters['action']:
        entries = entries.filter(action=filters['action'])
    if filters['severity'] in AuditLog.Severity.values:
        entries = entries.filter(severity=filters['severity'])
    else:
        filters['severity'] = ''
    if start := _day(filters['from']):
        entries = entries.filter(created_at__gte=start)
    if end := _day(filters['to'], end=True):
        entries = entries.filter(created_at__lte=end)

    page = Paginator(entries, 50).get_page(request.GET.get('page'))
    query = request.GET.copy()
    query.pop('page', None)
    return render(request, 'core/activity_log.html', {
        'page': page,
        'filters': filters,
        'query': query.urlencode(),
        'users': readable.order_by('user_name').values_list('user_name', flat=True).distinct(),
        'types': [(name, gettext(name)) for name in
                  readable.order_by('entity_type').values_list('entity_type', flat=True).distinct()],
        'actions': AuditLog.Action.choices,
        'severities': AuditLog.Severity.choices,
    })
