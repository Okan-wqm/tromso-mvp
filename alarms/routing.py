"""Who is notified of an alarm at a level (the recipient rules, alarms.models.RecipientRule): every live, active rule of that
level whose site and production department are the alarm's or every one (an alarm of the alarm system that none
reaches: every rule, `Router.reaching`), and whose least severity the alarm reaches; its
role's active members or its person, if active; with `on_shift_only`, only those on shift now (hr.read.on_shift). A person
reached by several rules is notified once, by the first.

A pass reads the rules, the roles' members and who is on shift once (`Router`), whatever the number of alarms it routes
(alarm plan, defect 7).

An alarm on a sealed experiment's cell (core.sealing) reaches only the people who may see it (its team, a grantee of
its water, a person holding Oversee, the platform admin unless the experiment is private): its text names the unit and
the value, which do not exist for anyone else. Which alarms lie on a sealed cell is read once per pass (`prepare`);
only for those is each person checked."""
from collections import defaultdict

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from core import sealing

from hr import read as hr_read

from .models import RANK, RecipientRule, Source


class Router:
    """The recipient rules as one pass reads them: three queries at most (the rules, the roles' members, who is on
    shift, the last only when a rule asks)."""

    def __init__(self, now):
        self.now = now
        self.rules = list(RecipientRule.objects.filter(is_active=True).select_related('user', 'role')
                          .order_by('created_at', 'id'))
        Membership = get_user_model().groups.through
        self.members = defaultdict(list)
        for membership in (Membership.objects.filter(group_id__in={rule.role_id for rule in self.rules if rule.role_id})
                           .select_related('user').order_by('user__username')):
            self.members[membership.group_id].append(membership.user)
        self._on_shift = None
        self.sealed = set()
        self._sees = {}

    def prepare(self, alarms):
        """Reads which of `alarms` lie on a sealed cell: those someone outside every team may not see (one query)."""
        from .models import Alarm
        ids = [alarm.pk for alarm in alarms]
        with sealing.as_viewer(AnonymousUser()):
            open_to_all = set(Alarm.objects.filter(pk__in=ids).values_list('pk', flat=True))
        self.sealed = set(ids) - open_to_all

    def sees(self, person, alarm):
        """Whether `person` may see `alarm` (asked only for an alarm on a sealed cell)."""
        from .models import Alarm
        key = (person.pk, alarm.pk)
        if key not in self._sees:
            with sealing.as_viewer(person):
                self._sees[key] = Alarm.objects.filter(pk=alarm.pk).exists()
        return self._sees[key]

    def on_shift(self):
        if self._on_shift is None:
            self._on_shift = hr_read.on_shift(self.now)
        return self._on_shift

    def reaching(self, alarm):
        """The rules whose site, department and least severity reach the alarm, at any level. An alarm of the alarm
        system itself (source 'system': the sensors cannot be read, a step failed, a unit cannot be evaluated) that no
        such rule reaches goes to every rule its severity reaches, whatever their site (cross review F8): a farm-wide one
        (no site) is the company-wide rules' first, and never nobody's."""
        severe = [rule for rule in self.rules if RANK[rule.min_severity] <= RANK[alarm.severity]]
        found = [rule for rule in severe if rule.site_id in (None, alarm.site_id)
                 and rule.production_department_id in (None, alarm.production_department_id)]
        if not found and alarm.source == Source.SYSTEM:
            return severe
        return found

    def people(self, rule):
        """The active people a rule names now (its person, or its role's members; on shift only, when it says so)."""
        people = [rule.user] if rule.user_id else self.members[rule.role_id]
        if rule.on_shift_only:
            on_shift = self.on_shift()
            people = [person for person in people if person.pk in on_shift]
        return [person for person in people if person.is_active]

    def recipients(self, alarm, level):
        """[(user, rule)] notified of the alarm at `level`, each person once, by username. An alarm on a sealed cell
        goes to the people of the rules who may see it; when no rule names anyone who may, it goes at its first level
        to whoever keeps those fish: the experiment's lead and the people holding Oversee (review F8; `rule` None)."""
        found = {}
        reaching = self.reaching(alarm)
        for rule in reaching:
            if rule.level != level:
                continue
            for person in self.people(rule):
                if person.pk not in found and (alarm.pk not in self.sealed or self.sees(person, alarm)):
                    found[person.pk] = (person, rule)
        if alarm.pk in self.sealed and not found and level == min((rule.level for rule in reaching), default=0)                 and not any(self.sees(person, alarm) for rule in reaching for person in self.people(rule)):
            for person in self.keepers(alarm):
                found.setdefault(person.pk, (person, None))
        return sorted(found.values(), key=lambda pair: pair[0].get_username())

    def keepers(self, alarm):
        """Who keeps the fish of a sealed alarm's cell: its experiment's live lead and the active Oversee holders, among
        those who may see the alarm."""
        provider = sealing.provider()
        if provider is None or alarm.point_id is None:
            return []
        point = alarm.point
        return [person for person in provider.keepers(point.unit_id, point.system_id) if self.sees(person, alarm)]

    def next_level(self, alarm, level):
        """The first level above `level` with a rule that reaches the alarm, or None."""
        return min((rule.level for rule in self.reaching(alarm) if rule.level > level), default=None)


def recipients(alarm, level, now):
    """[(user, rule)] notified of the alarm at `level` (`Router`)."""
    router = Router(now)
    router.prepare([alarm])
    return router.recipients(alarm, level)


def next_level(alarm, level, now=None):
    """The first level above `level` with a rule that reaches the alarm (`Router`)."""
    return Router(now).next_level(alarm, level)
