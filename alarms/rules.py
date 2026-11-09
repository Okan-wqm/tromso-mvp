"""The alarm rules as one pass reads them: the user's reference data (alarms.SeverityPolicy per severity,
alarms.ParameterDeadband per water parameter; owner, alarm plan §7c), read once at the start of a pass, so a change takes
effect on the next one. Nothing here is a default: a severity's row is seeded by migration 0002 and kept by the database
(one per severity); a parameter without a deadband row has none."""
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from .models import ParameterDeadband, SeverityPolicy


@dataclass(frozen=True)
class Rules:
    policies: dict          # {severity: SeverityPolicy}
    deadbands: dict         # {parameter code: Decimal}

    def on_delay(self, severity):
        """How long a condition must hold before the alarm is raised."""
        return timedelta(seconds=self.policies[severity].on_delay_seconds)

    def off_delay(self, severity):
        """How long a condition must be over before the alarm clears."""
        return timedelta(seconds=self.policies[severity].off_delay_seconds)

    def escalation_after(self, severity):
        """How long a level waits for an acknowledgement before the next level is notified."""
        return timedelta(minutes=self.policies[severity].escalation_minutes)

    def delivery_attempts(self, severity):
        """How many times a failing transport is tried with one notification."""
        return self.policies[severity].delivery_attempts

    def deadband(self, code):
        """The parameter's deadband, in its unit; none without a row."""
        return self.deadbands.get(code, Decimal(0))


def current():
    """The rules as the database holds them now (two queries)."""
    return Rules({policy.severity: policy for policy in SeverityPolicy.objects.all()},
                 dict(ParameterDeadband.objects.values_list('parameter', 'deadband')))
