"""Reading the health records: the days they need fish on (for the stock's own check), the deaths recorded
under a health event, and the sea-lice weeks of a site with their statutory limit. Everything is worked out
from the stored rows on read; nothing here writes.

The site's week (lakselusforskriften Vedlegg 1 point 6): for each unit counted in the ISO week, its latest
live count of that week; per stage, the unit's average is its lice / its fish examined, and the site's
average is the sum of the units' averages divided by the number of units counted, every unit weighing the
same. The limit is § 8's for the site's area and that week (farm/health/lice.py)."""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.db.models import OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce

from farm.models import HealthEvent, LiceCount, StockMovement, Treatment
from farm.models.stock import MovementKind
from farm.stock.dates import local_today

from . import lice

STAGES = ('adult_females', 'mobile', 'attached')
ZERO = Decimal(0)
RECENT_DAYS = 90       # a unit's treatments the drawer and the cards list


def dated_records(unit_ids, since=None):
    """[(kind, record, unit id, day)] of the live health records that need fish in a unit on a day: a
    treatment on its first day in each of its units, a lice count on its day; `since` leaves out older ones.
    The stock service refuses an operation that would leave one without fish, as it does for a feeding."""
    found = []
    treatments = Treatment.objects.filter(units__in=unit_ids).distinct().prefetch_related('units')
    counts = LiceCount.objects.filter(unit_id__in=unit_ids)
    if since is not None:
        treatments, counts = treatments.filter(start_date__gte=since), counts.filter(date__gte=since)
    wanted = set(unit_ids)
    for treatment in treatments:
        found += [('treatment', treatment, unit.pk, treatment.start_date) for unit in treatment.units.all()
                  if unit.pk in wanted]
    found += [('lice_count', count, count.unit_id, count.date) for count in counts]
    return found


def has_fish_for(kind, day):
    """Whether a health record of `kind` ('treatment', 'lice_count') finds the fish it needs in a unit on a day of the
    feeding walk (fold.Day): a sea-lice count, production fish (the lice are counted on the salmon, not on the cleaner
    fish beside them, D-1); a treatment, any fish."""
    return (day.production if kind == 'lice_count' else day).has_fish


def with_deaths(events):
    """The events (a queryset) with `deaths`: the fish that died or were culled under each, from the lines of
    the live mortality and cull operations that name it (0 when none)."""
    lines = (StockMovement.objects.filter(operation__health_event=OuterRef('pk'), operation__is_deleted=False,
                                          kind__in=[MovementKind.MORTALITY, MovementKind.CULL])
             .order_by().values('operation__health_event').annotate(fish=Sum('count_delta')).values('fish'))
    return events.annotate(deaths=Coalesce(-Subquery(lines), 0))


# ---- sea-lice weeks ---------------------------------------------------------------------------------
def iso_week(day):
    year, week, _weekday = day.isocalendar()
    return year, week


@dataclass
class LiceWeek:
    """A site's sea lice in one ISO week: the latest count of each unit counted, the site's averages per
    stage, the limit and the sample the regulation asks for."""
    site: object
    year: int
    week: int
    counts: list = field(default_factory=list)    # the latest live count of each unit counted that week
    stocked: int = None                            # units of the site holding fish now (for "3 of 4 counted")

    @property
    def area(self):
        return self.site.lice_area if self.site is not None else ''

    def average(self, stage):
        """The site's average of a stage per fish: the mean of the units' averages (Vedlegg 1 point 6)."""
        if not self.counts:
            return None
        return sum((count.per_fish(stage) for count in self.counts), ZERO) / len(self.counts)

    @property
    def adult_females(self):
        return self.average('adult_females')

    @property
    def mobile(self):
        return self.average('mobile')

    @property
    def attached(self):
        return self.average('attached')

    @property
    def limit(self):
        return lice.limit(self.area, self.week)

    @property
    def over_limit(self):
        return bool(self.counts) and lice.over(self.adult_females, self.area, self.week)

    @property
    def area_unknown(self):
        return self.area not in lice.AREAS

    @property
    def minimum_fish(self):
        return lice.minimum_fish(self.area, self.week)

    @property
    def small_samples(self):
        """The counts that examined fewer fish than the regulation asks for that week."""
        return [count for count in self.counts if count.fish_counted < self.minimum_fish]


def lice_weeks(counts):
    """[LiceWeek] of the live counts given (a queryset), newest week first, sites by name."""
    latest = {}
    for count in counts.filter(is_deleted=False).select_related('unit__production_department__site').order_by(
            'date', 'created_at'):
        site = count.unit.production_department.site
        latest[(site.pk if site else None, iso_week(count.date), count.unit_id)] = count
    weeks = {}
    for (site_id, (year, week), _unit_id), count in latest.items():
        key = (site_id, year, week)
        if key not in weeks:
            weeks[key] = LiceWeek(count.unit.production_department.site, year, week)
        weeks[key].counts.append(count)
    for item in weeks.values():
        item.counts.sort(key=lambda count: count.unit.code)
    return sorted(weeks.values(), key=lambda item: (-item.year, -item.week, item.site.name if item.site else ''))


def latest_counts(unit_ids):
    """{unit id: its latest live lice count}: one row per unit, the newest by date, then by entry."""
    rows = (LiceCount.objects.filter(unit_id__in=unit_ids).order_by('unit_id', '-date', '-created_at')
            .distinct('unit_id'))
    return {count.unit_id: count for count in rows}


def recent_treatments(units, days=RECENT_DAYS):
    """{unit id: [Treatment]} of every unit given: its live treatments that ended no longer than `days` before the
    unit's own today (a course still running too), newest first, with the medicine. Two queries for all the units."""
    since = {unit.pk: local_today(unit) - timedelta(days=days) for unit in units}
    found = {unit_id: [] for unit_id in since}
    if not since:
        return found
    rows = (Treatment.units.through.objects
            .filter(tank_id__in=since, treatment__is_deleted=False, treatment__end_date__gte=min(since.values()))
            .select_related('treatment__medicine'))
    for row in rows:
        if row.treatment.end_date >= since[row.tank_id]:
            found[row.tank_id].append(row.treatment)
    for treatments in found.values():
        treatments.sort(key=lambda treatment: (treatment.start_date, treatment.created_at), reverse=True)
    return found


def open_events(units):
    """{unit id: [HealthEvent]} of every unit given: the open health events of its site that name it or name no unit
    (the whole site), in the events' own order. Two queries for all the units."""
    found = {unit.pk: [] for unit in units}
    by_site = defaultdict(list)
    for unit in units:
        if unit.production_department.site_id is not None:
            by_site[unit.production_department.site_id].append(unit)
    if not by_site:
        return found
    for event in HealthEvent.objects.filter(site_id__in=by_site, closed_on__isnull=True).prefetch_related('units'):
        named = {unit.pk for unit in event.units.all()}
        for unit in by_site[event.site_id]:
            if not named or unit.pk in named:
                found[unit.pk].append(event)
    return found


def stocked_by_site(units_with_fish):
    """{site id: units holding fish}, for "N of M units counted"."""
    found = defaultdict(int)
    for unit in units_with_fish:
        found[unit.production_department.site_id] += 1
    return found


def treatments_on(unit, first, last):
    """The live treatments of `unit` on any day from `first` to `last` (one with no last day still runs), first day
    first: the treatments a unit's water history marks (Tank › Water)."""
    return (Treatment.objects.filter(units=unit, start_date__lte=last)
            .filter(Q(end_date__isnull=True) | Q(end_date__gte=first)).order_by('start_date'))
