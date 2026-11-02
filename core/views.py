from datetime import datetime, time

from django.core.paginator import Paginator
from django.shortcuts import render
from django.utils import timezone

from .models import AuditLog


def _day(value, end=False):
    try:
        day = datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None
    return timezone.make_aware(datetime.combine(day, time.max if end else time.min))


def activity_log(request):
    """Every recorded change, newest first, filterable by person, record type, action and dates."""
    entries = AuditLog.objects.all()
    filters = {key: request.GET.get(key, '').strip() for key in ('q', 'user', 'type', 'action', 'from', 'to')}
    if filters['q']:
        entries = entries.filter(entity_label__icontains=filters['q'])
    if filters['user']:
        entries = entries.filter(user_name=filters['user'])
    if filters['type']:
        entries = entries.filter(entity_type=filters['type'])
    if filters['action']:
        entries = entries.filter(action=filters['action'])
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
        'users': AuditLog.objects.order_by('user_name').values_list('user_name', flat=True).distinct(),
        'types': AuditLog.objects.order_by('entity_type').values_list('entity_type', flat=True).distinct(),
        'actions': AuditLog.Action.choices,
    })
