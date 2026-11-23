"""Experiment confidentiality, the provider of core.sealing: what a sealed cell is (the view `experiment_cells`), who is
granted what (the team and the shares), and the seals of the experiments' own records.

Who is granted what is defined once, by two querysets (`_members`, `_shares`) and the closure of the parts: the results
come with the data, the design and the systems; the data with the design and the systems; the water with the systems.
The seal's predicate reads them as subqueries inside the statement that reads the rows (`hidden_work`), with the person
read when the statement is compiled (core.sealing.Viewing), so narrowing costs no query of its own and a queryset built
earlier is never bound to anyone; Python's decisions on an experiment's own pages load them once per request (`load`)."""
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.db.models.functions import Now
from django.utils import timezone

from core import sealing
from core.dates import company_today

from .models import Experiment, ExperimentShare, Member, SealedCell

# What each part brings with it (read at read time, never stored).
CLOSURE = {'results': ('data', 'design', 'systems'), 'data': ('design', 'systems'), 'water': ('systems',)}
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
    """The condition on a member or a share of being live at `at`; with no moment, at the moment the query runs (the
    database's now: a queryset built earlier never keeps an old moment)."""
    at = at or Now()
    return (Q(valid_from__isnull=True) | Q(valid_from__lte=at)) & (Q(valid_until__isnull=True) | Q(valid_until__gt=at))


def _members(user_id, at=None):
    """The person's live team places."""
    return Member._base_manager.filter(live(at), user_id=user_id)


def _shares(user_id, at=None):
    """The live shares the person holds, given to them or to one of their roles."""
    return ExperimentShare._base_manager.filter(live(at), Q(user_id=user_id) | Q(group__user=user_id),
                                                revoked_at__isnull=True)


def _seen(user_id, part):
    """The condition on an experiment that the person reads its `part` (for the shell: any part): its team, or a live
    share of a part that gives it. `user_id` may be sealing.Viewing('user'), read when the statement runs."""
    members, shares = _members(user_id), _shares(user_id)
    if part != SHELL:
        shares = shares.filter(part__in=granting(part))
    return Q(pk__in=members.values('experiment_id')) | Q(pk__in=shares.values('experiment_id'))


def hidden_work(part):
    """The ids of the experiments whose `part` whoever is looking may not read (a subquery, read when the statement
    runs): those that are not open and are not theirs to read; for the platform admin only the private ones (owner
    amendment C4)."""
    admin = Q(sealing.Viewing('super'))
    rows = Experiment._base_manager.filter((admin & Q(audience=Experiment.Audience.PRIVATE))
                                           | (~admin & ~Q(audience=Experiment.Audience.OPEN)))
    return rows.exclude(_seen(sealing.Viewing('user'), part)).values('pk')


def oversees():
    """A subquery with a row when whoever is looking holds Oversee (the role matrix), as Django's own permission check
    reads it: an active person, the right given to them or to one of their roles."""
    app, codename = OVERSEE
    right = {'content_type__app_label': app, 'codename': codename}
    people = get_user_model()._base_manager.filter(pk=sealing.Viewing('user'), is_active=True)
    return people.filter(Q(**{f'user_permissions__{key}': value for key, value in right.items()})
                         | Q(**{f'groups__permissions__{key}': value for key, value in right.items()})).values('pk')


def load(user):
    """The viewer for a signed-in `user`, for Python's decisions (the experiment's pages, the read log): their live
    teams and shares, with the parts' closure; `oversee` from the role matrix; for the platform admin the
    private experiments they are not in (`barred`)."""
    now = timezone.now()
    team = frozenset(_members(user.pk, now).values_list('experiment_id', flat=True))
    granted = {}
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


def note_reads(ids, route, part=''):
    """Writes the read log for the experiments `ids` the person looking has just been shown (a page, a list, the
    activity log, the database viewer, the admin): every one that is not open and not theirs: the platform admin's
    read as support, a grantee's as a view (review F8). The lead reads them on Who looked."""
    current = sealing.viewer()
    if current is None or not ids:
        return
    from core.models import AccessEvent
    sealed = Experiment._base_manager.filter(pk__in=list(ids)).exclude(audience=Experiment.Audience.OPEN)         .exclude(pk__in=list(current.team)).values_list('pk', flat=True)
    for pk in sealed:
        kind = AccessEvent.Kind.SUPPORT if current.is_super and pk not in current.everything() else AccessEvent.Kind.VIEW
        sealing.log_access(kind, 'experiment', pk, part=part, route=route)


def keepers(unit_id, system_id):
    """The people who keep the fish of a unit or system an experiment holds today: its live lead and every active
    person holding Oversee (the alarms' fallback when no recipient rule names anyone who may see the alarm)."""
    with sealing.system('the alarms’ fallback'):
        today = company_today()
        where = (Q(unit=unit_id) if unit_id else Q(pk__in=[])) | (Q(system=system_id) if system_id else Q(pk__in=[]))
        cells = SealedCell.objects.filter(where, from_on__lte=today, until_on__gte=today)
        work = {cell.work for cell in cells}
        leads = Member._base_manager.filter(live(), experiment__in=work, role=Member.Role.LEAD).values('user')
        app, codename = OVERSEE
        right = {'content_type__app_label': app, 'codename': codename}
        overseers = get_user_model()._base_manager.filter(
            Q(**{f'user_permissions__{key}': value for key, value in right.items()})
            | Q(**{f'groups__permissions__{key}': value for key, value in right.items()})).values('pk')
        return list(get_user_model()._base_manager.filter(Q(pk__in=leads) | Q(pk__in=overseers), is_active=True)
                    .order_by('username'))


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
    note_reads = staticmethod(note_reads)
    keepers = staticmethod(keepers)


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
