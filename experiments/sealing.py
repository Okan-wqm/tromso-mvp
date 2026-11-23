"""Experiment confidentiality, the provider of core.sealing: what a sealed cell is (the view `experiment_cells`), who is
granted what (the team and the shares), and the seals of the experiments' own records.

Who is granted what is defined once, by two querysets (`_members`, `_shares`) and the closure of the parts: the results
and the data come with the design and the systems; the water with the systems. The seal's predicate reads them as
subqueries inside the statement that reads the rows (`hidden_work`), so narrowing costs no query of its own; Python's
decisions on an experiment's own pages load them once per request (`load`)."""
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from core import sealing

from .models import Experiment, ExperimentShare, Member, SealedCell

# What each part brings with it (read at read time, never stored).
CLOSURE = {'results': ('design', 'systems'), 'data': ('design', 'systems'), 'water': ('systems',)}
# The part an experiment's own page asks for its shell (the code, the name, the lead): any live grant gives it.
SHELL = 'shell'
OVERSEE = ('experiments', 'oversee_experiment')


def closure(parts):
    """The parts and what they bring with them."""
    found = set(parts)
    for part in parts:
        found.update(CLOSURE.get(part, ()))
    return found


def granting(part):
    """The parts whose share gives `part` (the closure read backwards)."""
    return sorted(each for each in sealing.PARTS if part in closure([each]))


def live(at=None):
    """The condition on a member or a share of being live at `at` (now)."""
    at = at or timezone.now()
    return (Q(valid_from__isnull=True) | Q(valid_from__lte=at)) & (Q(valid_until__isnull=True) | Q(valid_until__gt=at))


def _members(user_id, at):
    """The person's live team places."""
    return Member._base_manager.filter(live(at), user_id=user_id)


def _shares(user_id, at):
    """The live shares the person holds, given to them or to one of their roles."""
    return ExperimentShare._base_manager.filter(live(at), Q(user_id=user_id) | Q(group__user=user_id),
                                                revoked_at__isnull=True)


def _seen(user_id, part):
    """The condition on an experiment that the person reads its `part` (for the shell: any part, or a guest's place):
    its team (but a guest), or a live share of a part that gives it."""
    at = timezone.now()
    members, shares = _members(user_id, at), _shares(user_id, at)
    if part != SHELL:
        members = members.exclude(role=Member.Role.GUEST)
        shares = shares.filter(part__in=granting(part))
    return Q(pk__in=members.values('experiment_id')) | Q(pk__in=shares.values('experiment_id'))


def hidden_work(who, part):
    """The ids of the experiments whose `part` `who` may not read (a subquery): those that are not open and are not
    theirs to read; for the platform admin only the private ones (owner amendment C4)."""
    rows = Experiment._base_manager.filter(audience=Experiment.Audience.PRIVATE) if who.is_super         else Experiment._base_manager.exclude(audience=Experiment.Audience.OPEN)
    if who.user_id is not None:
        rows = rows.exclude(_seen(who.user_id, part))
    return rows.values('pk')


def oversees(who):
    """A subquery with a row when `who` holds Oversee (the role matrix), as Django's own permission check reads it:
    an active person, the right given to them or to one of their roles."""
    app, codename = OVERSEE
    right = {'content_type__app_label': app, 'codename': codename}
    people = get_user_model()._base_manager.filter(pk=who.user_id, is_active=True)
    return people.filter(Q(**{f'user_permissions__{key}': value for key, value in right.items()})
                         | Q(**{f'groups__permissions__{key}': value for key, value in right.items()})).values('pk')


def load(user):
    """The viewer for a signed-in `user`, for Python's decisions (the experiment's pages, the read log): their live
    teams, guest places and shares, with the parts' closure; `oversee` from the role matrix; for the platform admin the
    private experiments they are not in (`barred`)."""
    now = timezone.now()
    members = list(_members(user.pk, now).values_list('experiment_id', 'role'))
    # A guest of the team is present and observes: they read the experiment's shell (its code, name, lead and team),
    # no part of it (plan 2.2).
    team = frozenset(experiment for experiment, role in members if role != Member.Role.GUEST)
    guest_of = {experiment for experiment, role in members if role == Member.Role.GUEST}
    granted = {SHELL: guest_of} if guest_of else {}
    for experiment_id, part in _shares(user.pk, now).values_list('experiment_id', 'part').distinct():
        for each in closure([part]):
            granted.setdefault(each, set()).add(experiment_id)
    granted = {part: frozenset(ids) for part, ids in granted.items()}
    barred = frozenset()
    if user.is_superuser:
        reached = team.union(*granted.values())
        barred = frozenset(Experiment._base_manager.filter(audience=Experiment.Audience.PRIVATE)
                           .exclude(pk__in=list(reached)).values_list('pk', flat=True))
    return sealing.Viewer(user_id=user.pk, username=user.get_username(), is_super=user.is_superuser,
                          oversee=user.has_perm('.'.join(OVERSEE)) and not user.is_superuser,
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


class Provider:
    load = staticmethod(load)
    cells = staticmethod(cells)
    hidden_work = staticmethod(hidden_work)
    oversees = staticmethod(oversees)


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
