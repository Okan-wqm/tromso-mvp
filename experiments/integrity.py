"""The rules of a started experiment that the database cannot hold, checked from scratch over every experiment that has
begun (what is held by constraints and triggers is tested by raw SQL; this finds a row that got past what the database
cannot say: it counts or crosses tables). A design that lost a part (a group without replicates, a group without a level of
a factor), a tank off the site or booked outside the days of the experiment, a tank deleted while it is in one, and, in a
running experiment, a placement of a diet group without its live feeding assignment (the row the start wrote, ended
with the placement). The design's own rules are `design.HOLDS_AFTER_START`: said once, there. `manage.py
check_experiments` prints what it finds; the test suite runs it after its scenarios. Its messages are for the
developer, in English."""
from django.utils import translation

from farm.models import ProtocolAssignment

from . import design
from .models import Experiment, FactorKind, Status


def problems():
    """[str] of what is wrong, the experiment's number first; [] when everything adds up."""
    found = []
    with translation.override('en'):
        for experiment in Experiment.objects.exclude(status=Status.DRAFT).select_related('site', 'species').order_by('code'):
            found.extend(f'{experiment.code}: {text}' for text in _of(experiment))
    return found


def _of(experiment):
    stored = design.load(experiment)
    for check in design.HOLDS_AFTER_START:
        for finding in check(stored):
            if finding.level == design.ERROR:
                yield finding.text
    rows = [(group, replicate, row) for group, replicate in stored.slots() for row in stored.placements.get(replicate.pk, [])]
    for group, replicate, row in rows:
        if row.unit.is_deleted:
            yield f'{row.unit.code} of {group.name} R{replicate.number} was deleted while it is in the experiment.'
    if experiment.status == Status.RUNNING:
        yield from _diet_rows(stored, rows)


def _diet_rows(stored, rows):
    """Each placement of a group with a diet level has its one live unit-scope assignment: the diet's protocol, from the
    placement's first day to its last (`services.start` writes it, `release_unit` and `replace_unit` keep it so; the farm's
    exclusion over a unit's rows allows no second one)."""
    diet = next((factor for factor in stored.factors if factor.kind == FactorKind.DIET), None)
    if diet is None:
        return
    wanted = [(group, replicate, row, stored.level_of(group, diet).protocol) for group, replicate, row in rows
              if stored.level_of(group, diet) is not None and stored.level_of(group, diet).protocol_id]
    standing = {}
    for assignment in ProtocolAssignment.objects.filter(unit_id__in={row.unit_id for _g, _r, row, _p in wanted},
                                                        batch__isnull=True):
        standing.setdefault((assignment.unit_id, assignment.protocol_id, assignment.valid_from), []).append(assignment)
    for group, replicate, row, protocol in wanted:
        mine = standing.get((row.unit_id, protocol.pk, row.from_on), [])
        where = f'{row.unit.code} of {group.name} R{replicate.number}'
        if not mine:
            yield (f'{where} has no feeding assignment of {protocol.name} from {row.from_on} (the diet of {group.name}).')
        elif mine[0].valid_until != row.until_on:
            yield (f'{where} is placed until {row.until_on}, but its feeding assignment of {protocol.name} ends on '
                   f'{mine[0].valid_until}.')
