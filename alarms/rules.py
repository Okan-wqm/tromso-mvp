"""The alarm rules as one pass reads them: the user's reference data (alarms.SeverityPolicy per severity,
alarms.ParameterDeadband per water parameter; owner, alarm plan §7c), read once at the start of a pass, so a change takes
effect on the next one. Nothing here is a default: a severity's row is seeded by migration 0002 and kept by the database
(one per severity, never deleted); a parameter without a deadband row has none.

A severity whose row is missing all the same (a restore, a hand edit) never stops the evaluation (cross review F6): each
of its fields is the safest the rows and their bounds allow, and the pass raises a critical configuration alarm until
the row is back (alarms/sources.py supervise):
- raise after: the lowest bound (at once: an alarm is never held back by a rule nobody set);
- clear after: the longest of the rows there are (an alarm is never ended sooner than a person asked), else the lowest
  bound;
- escalate after: the shortest of the rows there are, else the lowest bound;
- delivery attempts: the most of the rows there are, else the highest bound;
- retry after: the shortest of the rows there are, else the lowest bound;
- longest snooze: the shortest of the rows there are, else the lowest bound;
- device clock limit: the smallest of the rows there are, else the lowest bound; its deadband none."""
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from sensors.models.alarm import Severity

from .models import (ATTEMPTS_BOUNDS, CLOCK_SKEW_BOUNDS, CLOCK_WINDOW_BOUNDS, DELAY_BOUNDS, ESCALATION_BOUNDS, ON_DELAY_BOUNDS,
                     RETRY_BOUNDS, SHELVE_BOUNDS, ParameterDeadband, SeverityPolicy)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Rules:
    policies: dict          # {severity: SeverityPolicy}
    deadbands: dict         # {parameter code: Decimal}
    unreadable: bool = field(default=False)     # the rows could not be read at all: every value is the safest

    @property
    def missing(self):
        """The severities without a rule row, in order."""
        return [severity for severity in Severity.values if severity not in self.policies]

    def _value(self, severity, name, others, fallback):
        policy = self.policies.get(severity)
        if policy is not None:
            return getattr(policy, name)
        return others((getattr(each, name) for each in self.policies.values()), default=fallback)

    def on_delay(self, severity):
        """How long a condition must hold before the alarm is raised (missing row: at once)."""
        policy = self.policies.get(severity)
        return timedelta(seconds=policy.on_delay_seconds if policy is not None else ON_DELAY_BOUNDS[severity][0])

    def off_delay(self, severity):
        """How long a condition must be over before the alarm clears."""
        return timedelta(seconds=self._value(severity, 'off_delay_seconds', max, DELAY_BOUNDS[0]))

    def escalation_after(self, severity):
        """How long a level waits for an acknowledgement before the next level is notified."""
        return timedelta(minutes=self._value(severity, 'escalation_minutes', min, ESCALATION_BOUNDS[severity][0]))

    def delivery_attempts(self, severity):
        """How many times a failing transport is tried with one notification."""
        return self._value(severity, 'delivery_attempts', max, ATTEMPTS_BOUNDS[1])

    def retry_after(self, severity):
        """How long after a failed attempt a notification is tried again."""
        return timedelta(seconds=self._value(severity, 'retry_seconds', min, RETRY_BOUNDS[0]))

    def shelve_max(self, severity):
        """The longest an alarm of the severity may be snoozed."""
        return timedelta(minutes=self._value(severity, 'shelve_max_minutes', min, SHELVE_BOUNDS[severity][0]))

    def clock_skew(self, severity):
        """How far a device's clock may be off, either way, before the level holds (missing row: the smallest of the rows
        there are, else the lowest bound)."""
        return timedelta(seconds=self._value(severity, 'clock_skew_seconds', min, CLOCK_SKEW_BOUNDS[0]))

    def clock_behind_window(self, severity):
        """How long a device must be behind on every pass before its clock level holds (missing row: the shortest of the
        rows there are, else none)."""
        return timedelta(seconds=self._value(severity, 'clock_behind_window_seconds', min, CLOCK_WINDOW_BOUNDS[0]))

    def clock_deadband(self, severity):
        """How far back inside its limit a device's clock must come before the level clears (missing row: none)."""
        policy = self.policies.get(severity)
        return timedelta(seconds=policy.clock_skew_deadband_seconds if policy is not None else DELAY_BOUNDS[0])

    def deadband(self, code):
        """The parameter's deadband, in its unit; none without a row."""
        return self.deadbands.get(code, Decimal(0))


def current():
    """The rules as the database holds them now (two queries). When they cannot be read at all, the safest rules
    (`Rules.unreadable`): the pass goes on, and says so (sources.supervise)."""
    try:
        return Rules({policy.severity: policy for policy in SeverityPolicy.objects.all()},
                     dict(ParameterDeadband.objects.values_list('parameter', 'deadband')))
    except Exception:
        logger.exception('The alarm rules could not be read; the safest values stand in for this pass.')
        return Rules({}, {}, unreadable=True)
