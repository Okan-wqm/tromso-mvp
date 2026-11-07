"""/healthz: whether the platform can do its work, for a monitor outside it (no sign-in; it shows counts only).
200 when the database answers and a worker beat within WORKER_STALE_SECONDS (default 120), else 503."""
from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.db import DatabaseError
from django.db.models import Max, Min
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .models import Job, JobStatus, WorkerBeat


@login_not_required
@never_cache
@require_GET
def healthz(request):
    now = timezone.now()
    body = {'database': 'ok', 'worker_beat_age_s': None, 'dead_jobs': None, 'oldest_queued_s': None}
    try:
        beat = WorkerBeat.objects.aggregate(last=Max('beat_at'))['last']
        body['dead_jobs'] = Job.objects.filter(status=JobStatus.DEAD).count()
        oldest = Job.objects.filter(status=JobStatus.QUEUED, run_after__lte=now).aggregate(first=Min('run_after'))['first']
    except DatabaseError:
        body['database'] = 'down'
        return JsonResponse(body, status=503)
    if beat is not None:
        body['worker_beat_age_s'] = round((now - beat).total_seconds())
    if oldest is not None:
        body['oldest_queued_s'] = round((now - oldest).total_seconds())
    stale = getattr(settings, 'WORKER_STALE_SECONDS', 120)
    ok = body['worker_beat_age_s'] is not None and body['worker_beat_age_s'] <= stale
    return JsonResponse(body, status=200 if ok else 503)
