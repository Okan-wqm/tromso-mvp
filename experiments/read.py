"""Reading an experiment: the one definition of what belongs to the trial, and what the other pages and checks ask of
the placements. Pure reads, one query each unless said; every figure of the farm is read through the farm's own reads
(farm/stock/read.py, farm/feeding/read.py) over the days these give, never copied.

- `cells(experiment)`: the single definition of what belongs to the trial: each live placement with its replicate and
  group, in the order of the design. Everything that asks "which tank, which days, which replicate" (the overview, the
  checks, the dataset to come) asks here.
- `booked(unit_ids, first, last)`: the experiments that hold these tanks on some of those days, drafts included (a
  draft reserves its tanks)."""
from dataclasses import dataclass
from datetime import date

from .models import ExperimentGroup, Replicate, ReplicateUnit


@dataclass(frozen=True)
class Cell:
    """A tank in a replicate of a group, on the days it is booked to it (both included, on the site's clock)."""
    replicate: Replicate
    group: ExperimentGroup
    unit: object
    first: date
    last: date


def cells(experiment):
    """The live placements of an experiment as cells, by group position, replicate number and first day."""
    placements = (ReplicateUnit.objects.filter(replicate__group__experiment=experiment,
                                               replicate__is_deleted=False, replicate__group__is_deleted=False)
                  .select_related('replicate__group', 'unit__production_department__site', 'unit__system')
                  .order_by('replicate__group__position', 'replicate__group__name', 'replicate__number', 'from_on',
                            'unit__code'))
    return [Cell(placement.replicate, placement.replicate.group, placement.unit, placement.from_on,
                 placement.until_on) for placement in placements]


def booked(unit_ids, first, last, exclude=None):
    """{unit id: the Experiment that holds it} for the tanks held on some day from `first` to `last` (both included)
    by an experiment other than `exclude`; one experiment a tank (the exclusion constraint allows no more)."""
    found = {}
    rows = (ReplicateUnit.objects.filter(unit_id__in=list(unit_ids), from_on__lte=last, until_on__gte=first)
            .select_related('replicate__group__experiment'))
    if exclude is not None:
        rows = rows.exclude(replicate__group__experiment=exclude)
    for placement in rows.order_by('from_on'):
        found.setdefault(placement.unit_id, placement.replicate.group.experiment)
    return found


def error_df(experiment):
    """The error degrees of freedom the design leaves: its replicates less its groups (pooled over the groups)."""
    groups = ExperimentGroup.objects.filter(experiment=experiment)
    replicates = Replicate.objects.filter(group__in=groups).count()
    return replicates - groups.count()
