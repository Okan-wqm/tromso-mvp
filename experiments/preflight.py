"""Before confidentiality goes live on a farm's database (plan step 11): what the owner and the leads must know, read
from the stored rows and changing nothing. `manage.py experiments_sealing_preflight` prints it.

- how many experiments are open, sealed and private (every existing experiment became sealed: migration 0004);
- the experiments with no live lead: nobody can share them or change who reads them, and outside the platform admin
  nobody but their team reads them;
- the replicates whose tanks are exactly the live tanks of a system on the same days but hold no whole-system booking:
  a tank could join or leave that system meanwhile; the lead books the system on the Places tab;
- the approvals that have ended while their experiment runs;
- the live shares held by a person whose account is inactive, and the system bookings with no live tank tagged.

Its lines are for the owner, in English."""
from collections import defaultdict

from django.db.models import Q

from core import sealing
from core.dates import company_today
from farm.models import System, Tank

from .models import Experiment, ExperimentShare, Member, ReplicateSystem, ReplicateUnit, Status
from .sealing import live

ANNOUNCEMENT = (
    'Experiments are now confidential. Every experiment is sealed: its team and the people its lead shares a part with '
    'read it, and the platform admin for support (each such read is shown to the lead). Its lead may open it to everyone '
    'who reads experiments, or make it private, which keeps it from the platform admin too. Its tanks and everything on '
    'them (stock, feeding, water, health, tasks, alarms) do not exist for anyone else, except the people whose role '
    'holds Oversee, who see the fish as farm facts with a card naming the trial, its lead and its approval. Someone with '
    'direct access to the database or the server can still read the stored rows.'
)


def report(today=None):
    """[str]: the lines to print."""
    today = today or company_today()
    lines = []
    with sealing.system('the preflight report'):
        experiments = Experiment.objects.filter(is_template=False)
        counts = {value: experiments.filter(audience=value).count() for value in Experiment.Audience.values}
        lines.append('Audience: ' + ', '.join(f'{counts[value]} {value}' for value in Experiment.Audience.values))
        leads = set(Member.objects.filter(live(), role=Member.Role.LEAD).values_list('experiment_id', flat=True))
        for experiment in experiments.exclude(pk__in=leads).order_by('code'):
            lines.append(f'{experiment.code}: no live lead (nobody can share it or change who reads it).')
        lines.extend(_whole_systems(experiments))
        for experiment in experiments.filter(status=Status.RUNNING, approval_valid_until__lt=today).order_by('code'):
            lines.append(f'{experiment.code}: its approval {experiment.approval_ref} ended on '
                         f'{experiment.approval_valid_until.isoformat()} while it runs.')
        for share in (ExperimentShare.objects.filter(live(), revoked_at__isnull=True, user__is_active=False)
                      .select_related('experiment', 'user').order_by('experiment__code', 'id')):
            lines.append(f'{share.experiment.code}: a live share of {share.part} to the inactive account '
                         f'{share.user.get_username()}.')
        for booking in (ReplicateSystem.objects.exclude(Q(placements__is_deleted=False))
                        .select_related('replicate__group__experiment', 'system').order_by('from_on')):
            lines.append(f'{booking.replicate.group.experiment.code}: the booking of {booking.system.code} has no live '
                         f'tank tagged.')
    return lines


def _whole_systems(experiments):
    """The replicates whose live placements are exactly the live tanks of a system (with its nested systems) on one
    window, with no booking of that system."""
    found = []
    rows = (ReplicateUnit.objects.filter(replicate__group__experiment__in=experiments, booking__isnull=True)
            .select_related('replicate__group__experiment', 'unit'))
    by_window = defaultdict(set)
    for row in rows:
        by_window[(row.replicate, row.from_on, row.until_on)].add(row.unit_id)
    booked = set(ReplicateSystem.objects.values_list('replicate_id', 'system_id'))
    for system in System.objects.all():
        tanks = set(Tank.objects.filter(system__in=[system, *system.descendants()]).values_list('pk', flat=True))
        if not tanks:
            continue
        for (replicate, first, last), units in by_window.items():
            if units == tanks and (replicate.pk, system.pk) not in booked:
                found.append(f'{replicate.group.experiment.code}: {replicate.group.name} R{replicate.number} holds every '
                             f'tank of {system.code} from {first.isoformat()} to {last.isoformat()} without booking the '
                             f'system (book it on the Places tab).')
    return found
