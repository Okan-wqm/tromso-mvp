"""What is wrong with an experiment's design, in one list: `problems(experiment)` gives the findings the Start dialog, the
overview page and `manage.py check_experiments` show. An error blocks Start; a warning is shown and the person goes on
by acknowledging the warnings they were shown (their fingerprint, as the handling check's). The findings are derived on
read from the stored design: nothing about them is stored.

`CHECKS` is the list of checks, each a function of the loaded `Design` giving findings; the other areas of the plan
(ethics, permits, welfare) append theirs, so a permit can block Start without this module knowing it."""
import hashlib
from dataclasses import dataclass, field

from django.conf import settings
from django.utils.translation import gettext as _

from farm.feeding.read import tables as protocol_tables
from farm.models.feeding_protocol import ProtocolStatus
from farm.stock.dates import site_earliest

from .models import Experiment, ExperimentGroup, Factor, FactorKind, GroupLevel, Level, Member, Replicate, ReplicateUnit

ERROR, WARNING = 'error', 'warning'


@dataclass(frozen=True)
class Finding:
    """One thing about the design: its level, a code that names the rule, the text in the reader's language, and what
    it is about (a group, a factor) so that two findings of one rule stay two."""
    level: str
    code: str
    text: str
    about: str = ''

    def key(self):
        """What the person saw, as text that does not depend on their language."""
        return f'{self.code}:{self.about}'


@dataclass
class Assessment:
    """The findings of an experiment, as the Start dialog carries them: the warnings' fingerprint is what the
    acknowledgement box holds, so a start whose warnings changed meanwhile is asked again
    (farm.handling.check.require_acknowledged)."""
    findings: list = field(default_factory=list)

    @property
    def errors(self):
        return [finding for finding in self.findings if finding.level == ERROR]

    @property
    def warnings(self):
        return [finding for finding in self.findings if finding.level == WARNING]

    @property
    def fingerprint(self):
        """The warnings as the acknowledgement box carries them; '' when there are none."""
        if not self.warnings:
            return ''
        keys = '|'.join(sorted(finding.key() for finding in self.warnings))
        return hashlib.sha256(keys.encode()).hexdigest()[:20]


@dataclass
class Design:
    """An experiment's stored design, read once for the checks: its live factors with their levels, groups with their
    levels and replicates, and the placements of each replicate."""
    experiment: Experiment
    factors: list
    groups: list
    levels: dict                # group id -> {factor id: Level}
    replicates: dict            # group id -> [Replicate], by number
    placements: dict            # replicate id -> [ReplicateUnit], by first day
    lead: bool

    def level_of(self, group, factor):
        return self.levels.get(group.pk, {}).get(factor.pk)

    def slots(self):
        """[(group, replicate)] in the order the design shows them."""
        return [(group, replicate) for group in self.groups for replicate in self.replicates.get(group.pk, [])]


def load(experiment):
    """The stored design of an experiment (a handful of queries, however large it is)."""
    factors = list(Factor.objects.filter(experiment=experiment).order_by('position', 'name'))
    groups = list(ExperimentGroup.objects.filter(experiment=experiment).order_by('position', 'name'))
    live_levels = {level.pk: level for level in Level.objects.filter(factor__in=factors).select_related('protocol')}
    levels = {}
    for row in GroupLevel.objects.filter(experiment=experiment, group__in=groups):
        level = live_levels.get(row.level_id)
        if level is not None:
            levels.setdefault(row.group_id, {})[row.factor_id] = level
    replicates = {}
    for replicate in Replicate.objects.filter(group__in=groups).order_by('number'):
        replicates.setdefault(replicate.group_id, []).append(replicate)
    placements = {}
    for placement in (ReplicateUnit.objects.filter(replicate__group__in=groups).order_by('from_on', 'id')
                      .select_related('unit__production_department__site', 'unit__system')):
        placements.setdefault(placement.replicate_id, []).append(placement)
    lead = Member.objects.filter(experiment=experiment, role=Member.Role.LEAD).exists()
    return Design(experiment, factors, groups, levels, replicates, placements, lead)


def table(design):
    """The stored design as a table to show: its factors, and for each group its level of each factor (None: none) and
    its replicates."""
    return {'factors': design.factors,
            'rows': [{'group': group, 'levels': [design.level_of(group, factor) for factor in design.factors],
                      'replicates': design.replicates.get(group.pk, [])} for group in design.groups]}


# ---- the checks ----------------------------------------------------------------------------------
def check_experiment(design):
    """What an experiment says of itself: its hypothesis, endpoint, day 0 and lead (the allocation comes with the
    places)."""
    experiment = design.experiment
    if not experiment.hypothesis:
        yield Finding(ERROR, 'no_hypothesis', _('The hypothesis is not written.'))
    if not experiment.primary_endpoint:
        yield Finding(ERROR, 'no_endpoint', _('The primary endpoint is not chosen.'))
    if experiment.starts_on is None:
        yield Finding(ERROR, 'no_start_day', _('Day 0 is not set.'))
    elif experiment.starts_on < site_earliest(experiment.site):
        yield Finding(ERROR, 'day_0_too_old', _('Day 0 is further back than records can be dated: an experiment is '
                                                'registered at most %(days)d days after it begins.') % {
            'days': settings.STOCK_BACKDATE_DAYS})
    if not design.lead:
        yield Finding(ERROR, 'no_lead', _('The team has no lead.'))


def check_groups(design):
    """The groups: there are some, each has replicates and a level of every factor, and no two are one treatment."""
    if not design.groups:
        yield Finding(ERROR, 'no_group', _('The design has no group.'))
        return
    for group in design.groups:
        if not design.replicates.get(group.pk):
            yield Finding(ERROR, 'no_replicate', _('Group %(group)s has no replicate.') % {'group': group.name},
                          group.name)
        for factor in design.factors:
            if design.level_of(group, factor) is None:
                yield Finding(ERROR, 'missing_level', _('Group %(group)s has no level of %(factor)s.') % {
                    'group': group.name, 'factor': factor.name}, f'{group.name}/{factor.name}')
    seen = {}
    for group in design.groups:
        key = tuple(design.level_of(group, factor).pk if design.level_of(group, factor) else None
                    for factor in design.factors)
        if None in key:
            continue                                      # incomplete: said above
        if key in seen:
            yield Finding(ERROR, 'same_levels', _('Groups %(first)s and %(second)s have the same levels: they are one '
                                                   'group.') % {'first': seen[key].name, 'second': group.name},
                          f'{seen[key].name}/{group.name}')
        seen.setdefault(key, group)


def check_protocols(design):
    """The diet's protocols: active, of the experiment's species, and what can still change under the experiment."""
    experiment = design.experiment
    diet = next((factor for factor in design.factors if factor.kind == FactorKind.DIET), None)
    if diet is None:
        return
    used = {}
    for group in design.groups:
        level = design.level_of(group, diet)
        if level is not None and level.protocol is not None:
            used[level.protocol.pk] = level.protocol
    for protocol in used.values():
        if protocol.status != ProtocolStatus.ACTIVE:
            yield Finding(ERROR, 'protocol_not_active', _('The feeding protocol %(protocol)s is not active.') % {
                'protocol': protocol.name}, protocol.name)
        if protocol.species_id != experiment.species_id:
            yield Finding(ERROR, 'protocol_species', _('The feeding protocol %(protocol)s is for %(species)s, not '
                                                       'for %(trial)s.') % {
                'protocol': protocol.name, 'species': protocol.species, 'trial': experiment.species}, protocol.name)
        elif not protocol.is_assigned():
            yield Finding(WARNING, 'protocol_unassigned', _('The feeding protocol %(protocol)s is not assigned yet: its '
                                                            'table can still change until the experiment starts.') % {
                'protocol': protocol.name}, protocol.name)
    if len(used) > 1:
        found = protocol_tables(list(used))
        shapes = {pk: _shape_without_feed(found[pk]) for pk in used if pk in found}
        if len(set(shapes.values())) > 1:
            yield Finding(WARNING, 'tables_differ', _('The diets’ feeding tables differ in more than the feed (weight '
                                                      'bands, meals, expected FCR or feeding rates): the groups would '
                                                      'differ in more than the diet.'))


def _shape_without_feed(table):
    """A protocol's table as the ration reads it, the feed of each band left out."""
    return tuple((band.min_weight_g, band.max_weight_g, band.meals, band.fcr,
                  tuple((cell.temperature_c, cell.sfr_pct) for cell in band.cells)) for band in table.bands)


def check_balance(design):
    """The balance of the design: replicates enough to say anything, a control, equal groups."""
    if not design.groups:
        return
    counts = {group.pk: len(design.replicates.get(group.pk, [])) for group in design.groups}
    if len(design.groups) == 1:
        yield Finding(WARNING, 'one_group', _('The design has one group: there is nothing to compare it with.'))
    elif any(count < 2 for count in counts.values()):
        yield Finding(WARNING, 'few_replicates', _('A group has fewer than two replicates: its variation within the '
                                                   'group cannot be told from the difference between groups.'))
    if not any(group.is_control for group in design.groups):
        yield Finding(WARNING, 'no_control', _('The design has no control group.'))
    if len(set(counts.values())) > 1:
        yield Finding(WARNING, 'unequal_replicates', _('The groups have different numbers of replicates.'))


CHECKS = [check_experiment, check_groups, check_protocols, check_balance]


def problems(experiment, design=None):
    """The findings of an experiment's stored design, errors first (the order the checks give them within a level)."""
    design = design or load(experiment)
    found = [finding for check in CHECKS for finding in check(design)]
    return sorted(found, key=lambda finding: finding.level != ERROR)


def assess(experiment, design=None):
    return Assessment(problems(experiment, design))

