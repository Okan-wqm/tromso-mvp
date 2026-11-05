"""The day and the time on the clocks of the sites. A site reads one time zone (`zone_of`); sites that share a zone
share a clock, and a record with no site is read on the company's clock. Every read that says "today", "overdue" or
"late" (the tasks, the HR area) takes its day from here and never from the server's date or the browser's."""
from dataclasses import dataclass
from datetime import datetime, time

from django.db.models import Q
from django.utils import timezone

from .models import Site
from .models.site import zone_of


@dataclass(frozen=True)
class Clock:
    """The day and the time now on one time zone, and which sites read it (None: the places without a site,
    on the company's clock)."""
    sites: tuple
    today: object
    now: time
    start: datetime     # the start of today, an aware moment
    zone: object = None

    def on(self, field='site_key'):
        """The rows whose site (`field`, the site's id or null) reads this clock."""
        return Q(**{f'{field}__isnull': True}) if self.sites is None else Q(**{f'{field}__in': self.sites})


def clocks(moment=None):
    """One Clock per time zone the sites use, and one for the places without a site."""
    moment = moment or timezone.now()
    zones = {}
    for site in Site.all_objects.only('pk', 'timezone'):
        zones.setdefault(zone_of(site), []).append(site.pk)
    found = [(tuple(ids), zone) for zone, ids in zones.items()] + [(None, zone_of(None))]
    result = []
    for sites, zone in found:
        local = timezone.localtime(moment, zone)
        start = datetime.combine(local.date(), time.min, tzinfo=zone)
        result.append(Clock(sites, local.date(), local.time().replace(tzinfo=None), start, zone))
    return result
