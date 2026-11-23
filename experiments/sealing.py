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
    team = frozenset(Member._base_manager.filter(live(now), user=user).values_list('experiment_id', flat=True))
    shares = ExperimentShare._base_manager.filter(live(now), Q(user=user) | Q(group__in=user.groups.all()),
                                            revoked_at__isnull=True).values_list('experiment_id', 'part')
    granted = {}
    for experiment_id, part in shares:
        for each in closure([part]):
            granted.setdefault(each, set()).add(experiment_id)
    return sealing.Viewer(user_id=user.pk, username=user.get_username(), is_super=user.is_superuser,
                          oversee=user.has_perm('experiments.oversee_experiment') and not user.is_superuser,
                          team=team, granted={part: frozenset(ids) for part, ids in granted.items()})


ALL = frozenset(sealing.PARTS)


def parts_of(experiment, current=None):
    """The parts of `experiment` the viewer of the moment reads: all of them for its team, a superuser, the system and
    an open experiment; for a grantee those of their live shares, with what they bring."""
    current = sealing.viewer() if current is None else current
    if current is None or current.is_super or experiment.audience == Experiment.Audience.OPEN \
            or experiment.pk in current.team:
        return ALL
    return frozenset(part for part in sealing.PARTS if experiment.pk in current.granted.get(part, ()))


def in_team(experiment, current=None):
    """Whether the viewer works on the experiment (its team now, a superuser, the system, or an open experiment): who may
    change it, if their role may."""
    current = sealing.viewer() if current is None else current
    return (current is None or current.is_super or experiment.audience == Experiment.Audience.OPEN
            or experiment.pk in current.team)


def cells():
    """The sealed cells (the database view)."""
    return SealedCell.objects.all()


def hidden_work(viewer, part):
    """The ids of the sealed experiments whose `part` the viewer may not read (for the shell: any part)."""
    seen = viewer.everything() if part == SHELL else viewer.sees(part)
    return Experiment._base_manager.filter(audience=Experiment.Audience.SEALED).exclude(pk__in=list(seen)).values('pk')


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
