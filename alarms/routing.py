"""Who is notified of an alarm at a level (the recipient rules, alarms.models.RecipientRule): every live, active rule of that
level whose site and production department are the alarm's or every one (an alarm of the alarm system that none
reaches: every rule, `Router.reaching`), and whose least severity the alarm reaches; its
role's active members or its person, if active; with `on_shift_only`, only those on shift now (hr.read.on_shift). A person
reached by several rules is notified once, by the first.

A pass reads the rules, the roles' members and who is on shift once (`Router`), whatever the number of alarms it routes
(alarm plan, defect 7)."""
from collections import defaultdict

from django.contrib.auth import get_user_model

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

    def recipients(self, alarm, level):
        """[(user, rule)] notified of the alarm at `level`, each person once, by username."""
        found = {}
        for rule in self.reaching(alarm):
            if rule.level != level:
                continue
            people = [rule.user] if rule.user_id else self.members[rule.role_id]
            if rule.on_shift_only:
                on_shift = self.on_shift()
                people = [person for person in people if person.pk in on_shift]
            for person in people:
                if person.is_active and person.pk not in found:
                    found[person.pk] = (person, rule)
        return sorted(found.values(), key=lambda pair: pair[0].get_username())

    def next_level(self, alarm, level):
        """The first level above `level` with a rule that reaches the alarm, or None."""
        return min((rule.level for rule in self.reaching(alarm) if rule.level > level), default=None)


def recipients(alarm, level, now):
    """[(user, rule)] notified of the alarm at `level` (`Router`)."""
    return Router(now).recipients(alarm, level)


def next_level(alarm, level, now=None):
    """The first level above `level` with a rule that reaches the alarm (`Router`)."""
    return Router(now).next_level(alarm, level)
