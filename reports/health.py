"""What the health records read of the notices (farm/health/notices.py, D-4): which health events Mattilsynet has been told
of, and where a person starts the notice for one. The farm never imports the reports; this provider is registered in the
app's `ready()`."""
from urllib.parse import urlencode

from django.urls import reverse

from farm.health.notices import Notified

from .models import HEALTH_EVENT_KINDS, Report


class DiseaseNotices:
    def told(self, events):
        """{health event id: Notified} of the events a notice was filed for (a disease notice, or a welfare notice that
        came of the event): the first filing counts, with the receipt it was given."""
        found = {}
        filed = Report.objects.filter(kind__in=HEALTH_EVENT_KINDS, health_event__in=events,
                                      submitted_at__isnull=False).order_by('submitted_at')
        for report in filed:
            found.setdefault(report.health_event_id, Notified(report.submitted_at, report.reference))
        return found

    def start_url(self, event, user):
        """The new-notice page filled from the event, for a person who may start reports; '' for one who may not."""
        if not user.has_perm('reports.add_report'):
            return ''
        return f'{reverse("reports:report_create")}?{urlencode({"health_event": event.pk})}'
