"""Experiment confidentiality, the provider of core.sealing: what a sealed cell is (the view `experiment_cells`), who is
granted what (the team and the shares), and the seals of the experiments' own records.

A viewer is loaded in one query per request: the experiments whose team the person is in now (every part), and per part
those a live share gives the person or one of their roles. The closure of the parts is read here, once: the results and
the data come with the design and the systems; the water with the systems."""
from django.db.models import Q
from django.utils import timezone

from core import sealing

from .models import Experiment, ExperimentShare, Member, SealedCell

# What each part brings with it (read at read time, never stored).
CLOSURE = {'results': ('design', 'systems'), 'data': ('design', 'systems'), 'water': ('systems',)}
# The part an experiment's own page asks for its shell (the code, the name, the lead): any live grant gives it.
SHELL = 'shell'


def closure(parts):
    """The parts and what they bring with them."""
    found = set(parts)
    for part in parts:
        found.update(CLOSURE.get(part, ()))
    return found


def live(at=None):
    """The condition on a member or a share of being live at `at` (now)."""
    at = at or timezone.now()
    return (Q(valid_from__isnull=True) | Q(valid_from__lte=at)) & (Q(valid_until__isnull=True) | Q(valid_until__gt=at))


def load(user):
    """The viewer for a signed-in `user`: their live teams and live shares (their own and their roles'), with the parts'
    closure; `oversee` from the role matrix."""
    now = timezone.now()
    members = Member._base_manager.filter(live(now), user=user).values_list('experiment_id', 'role')
    # A guest of the team is present and observes: they read the experiment's shell (its code, name, lead and team),
    # no part of it (plan 2.2).
    team = frozenset(experiment for experiment, role in members if role != Member.Role.GUEST)
    guest_of = {experiment for experiment, role in members if role == Member.Role.GUEST}
    shares = ExperimentShare._base_manager.filter(live(now), Q(user=user) | Q(group__in=user.groups.all()),
                                            revoked_at__isnull=True).values_list('experiment_id', 'part')
    granted = {SHELL: guest_of} if guest_of else {}
    for experiment_id, part in shares:
        for each in closure([part]):
            granted.setdefault(each, set()).add(experiment_id)
    granted = {part: frozenset(ids) for part, ids in granted.items()}
    barred = frozenset()
    if user.is_superuser:
        # What the platform admin may not read: the private experiments they are not in (owner amendment C4).
        reached = team.union(*granted.values())
        barred = frozenset(Experiment._base_manager.filter(audience=Experiment.Audience.PRIVATE)
                           .exclude(pk__in=list(reached)).values_list('pk', flat=True))
    return sealing.Viewer(user_id=user.pk, username=user.get_username(), is_super=user.is_superuser,
                          oversee=user.has_perm('experiments.oversee_experiment') and not user.is_superuser,
                          team=team, granted=granted, barred=barred)


ALL = frozenset(sealing.PARTS)


def parts_of(experiment, current=None):
    """The parts of `experiment` the viewer of the moment reads: all of them for whoever works on it (in_team); for a
    grantee those of their live shares, with what they bring."""
    current = sealing.viewer() if current is None else current
    if in_team(experiment, current):
        return ALL
    return frozenset(part for part in sealing.PARTS if experiment.pk in current.granted.get(part, ()))


def in_team(experiment, current=None):
    """Whether the viewer works on the experiment: its team now, the system, anyone on an open experiment, the platform
    admin on one that is not private (owner amendment C4). Who may change it, if their role may."""
    current = sealing.viewer() if current is None else current
    return (current is None or experiment.audience == Experiment.Audience.OPEN or experiment.pk in current.team
            or (current.is_super and experiment.audience != Experiment.Audience.PRIVATE))


def cells():
    """The sealed cells (the database view)."""
    return SealedCell.objects.all()


def hidden_work(viewer, part):
    """The ids of the experiments that are not open whose `part` the viewer may not read (for the shell: any part); for
    the platform admin, the private ones they are not granted."""
    seen = viewer.everything() if part == SHELL else viewer.sees(part)
    if viewer.is_super:
        return Experiment._base_manager.filter(pk__in=list(viewer.barred.difference(seen))).values('pk')
    return Experiment._base_manager.exclude(audience=Experiment.Audience.OPEN).exclude(pk__in=list(seen)).values('pk')


class Provider:
    load = staticmethod(load)
    cells = staticmethod(cells)
    hidden_work = staticmethod(hidden_work)


def register():
    """The provider, and the seals of the experiments' own records: the experiment itself is shown to anyone granted any
    part of it; its design (factors, levels, groups, replicates) with the design; its placements and bookings with the
    systems; its team and shares with the shell (the lead's page says who may read it)."""
    from . import models as m
    sealing.register_provider(Provider)
    sealing.declare(m.Experiment, part=SHELL, cls=sealing.SCIENCE, work='')
    for model, path in ((m.Factor, 'experiment'), (m.Level, 'factor__experiment'), (m.ExperimentGroup, 'experiment'),
                        (m.GroupLevel, 'experiment'), (m.Replicate, 'group__experiment')):
        sealing.declare(model, part='design', cls=sealing.SCIENCE, work=path)
    for model in (m.ReplicateUnit, m.ReplicateSystem):
        sealing.declare(model, part='systems', cls=sealing.SCIENCE, work='replicate__group__experiment')
    for model in (m.Member, m.ExperimentShare):
        sealing.declare(model, part=SHELL, cls=sealing.SCIENCE, work='experiment')
    sealing.declare(m.SealedCell, mode=sealing.EXEMPT,
                    reason='The sealed cells themselves: read by the seal alone, never by a page.')
