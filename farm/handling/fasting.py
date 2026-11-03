"""Fasting before handling: which rule applies, how long the fish have been without feed, and the fasts the
planned harvests and transports ask for.

The rule (HandlingRule, Setup › Reference data › Handling rules): for a kind of handling, the species' row,
else the row for every species, else none ("not checked", never a default). A grading moves the fish too, so it
takes the longer of its own rule and the transport rule (owner decision).

Hours fasted, never overstated (owner rule): from the fish's last feeding (farm.feeding.read.last_fed_at; a
record without a time counts from the end of its day) to the start of the handling's day on the site's clock,
since an operation has a date and no time. A feeding on the day itself gives 0 hours.

A planned harvest or transport (HandlingPlanItem, planned or overdue) asks the unit to fast from the start of
its day less the rule's hours: every day from the one the fast starts on to the planned day is a fasting day
in full, for the whole unit (two batches in a unit cannot be fed apart). The meal board asks `fasting_on`."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db.models import Q
from django.utils import formats
from django.utils.translation import gettext as _

from farm.models import HandlingPlanItem, HandlingRule
from farm.models.handling import MAX_FASTING_HOURS, HandlingKind
from farm.models.site import zone_of
from farm.stock.dates import start_of

# How far back the last feeding is looked for: longer than the longest rule (720 h), so a fish not fed in
# that time has fasted long enough for any rule.
LOOKBACK_DAYS = 31

# The rules each kind of handling is checked against; the longest applies.
RULES_OF = {
    HandlingKind.HARVEST: (HandlingKind.HARVEST,),
    HandlingKind.TRANSPORT: (HandlingKind.TRANSPORT,),
    HandlingKind.GRADING: (HandlingKind.GRADING, HandlingKind.TRANSPORT),
    HandlingKind.TREATMENT: (HandlingKind.TREATMENT,),
}


def rule_for(kind, species):
    """The rule of one kind for a species: the species' own row, else the row for every species, else None."""
    every = Q(species__isnull=True)
    rules = {rule.species_id: rule for rule in HandlingRule.objects.filter(
        Q(kind=kind) & (every | Q(species=species) if species is not None else every))}
    return rules.get(species.pk if species is not None else None) or rules.get(None)


def rule_of(kind, species):
    """The rule a handling of `kind` is checked against for a species: the longest of RULES_OF[kind] (the first
    on a tie); None when no rule applies."""
    found = [rule for rule in (rule_for(each, species) for each in RULES_OF[kind]) if rule is not None]
    return max(found, key=lambda rule: rule.min_fasting_hours, default=None)


def shown_moment(moment, unit):
    """A moment on the unit's site clock as the language writes it: 2 Nov 2026, 18:00."""
    return formats.date_format(moment.astimezone(zone_of(unit.production_department.site)), 'DATETIME_FORMAT')


# ---- the fasts plans ask for --------------------------------------------------------------------------
@dataclass(frozen=True)
class Fast:
    """The fast a planned harvest or transport asks of its unit."""
    item: HandlingPlanItem
    starts_at: datetime
    hours: int

    @property
    def on(self):
        return self.item.date

    @property
    def first_day(self):
        return self.starts_at.date()

    def covers(self, day):
        return self.first_day <= day <= self.on

    def why(self):
        """Fasting before the harvest of 15 Nov 2026: from 12 Nov 2026, 00:00 (72 h)."""
        params = {'date': formats.date_format(self.on, 'DATE_FORMAT'),
                  'start': shown_moment(self.starts_at, self.item.unit), 'hours': self.hours}
        if self.item.kind == HandlingPlanItem.Kind.HARVEST:
            return _('Fasting before the harvest of %(date)s: from %(start)s (%(hours)d h).') % params
        return _('Fasting before the transport of %(date)s: from %(start)s (%(hours)d h).') % params


def fast_of(item):
    """The fast a plan item asks for; None when it is done or cancelled, or no rule (or a 0 h one) applies."""
    if not item.is_open:
        return None
    rule = rule_of(item.kind, item.batch.species)
    if rule is None or not rule.min_fasting_hours:
        return None
    return Fast(item, start_of(item.date, item.unit) - timedelta(hours=rule.min_fasting_hours), rule.min_fasting_hours)


def fasts(units, first, last):
    """{(unit id, day): Fast} for the fasting days from `first` to `last` of these units; where the fasts of two
    plans overlap, the one that starts first wins. Loaded once for a page or a walk."""
    # A plan up to the longest rule after `last` can start its fast by then.
    reach = last + timedelta(hours=MAX_FASTING_HOURS)
    items = (HandlingPlanItem.objects.filter(unit__in=units, date__gte=first, date__lte=reach)
             .select_related('unit__production_department__site', 'batch__species', 'operation'))
    found = {}
    for item in items:
        fast = fast_of(item)
        if fast is None:
            continue
        day = max(fast.first_day, first)
        while day <= min(fast.on, last):
            key = (item.unit_id, day)
            if key not in found or fast.starts_at < found[key].starts_at:
                found[key] = fast
            day += timedelta(days=1)
    return found


def fasting_on(unit, day):
    """Why the fish of `unit` fast on `day` (the meal board shows no ration with it), or None."""
    fast = fasts([unit], day, day).get((unit.pk, day))
    return fast.why() if fast is not None else None
