"""Judging a water value against the owner's limits, on read. Pure Python, no queries: the read layer
(farm/water/read.py) brings the values, the limits and the fish.

Nothing is stored about a value's status: it follows the limits as they are now (owner decision 2), so
a limit changed today re-judges every sample at once (the source froze it at write time, WQ-21).

- A limit row (`WaterLimit`) is per species, parameter and water type; the row for the unit's water
  type wins over the row for any water. Two bands: inside the warning bounds is ok, outside them but
  inside the critical bounds is a warning, outside the critical bounds is critical; a value equal to
  a bound is in the inner band.
- A value is judged against every species it concerns, the fish in its unit on that day (several
  batches, later cleaner fish), and the worst status wins. No fish, or no row for their species: "no
  limit" (owner decision 1: an empty unit's values are shown, not judged).
- A value older than its parameter's freshness is "stale" (shown with its age), never ok.
- A unit's status is the worst status of its fresh values; stale when nothing is fresh."""
from datetime import timedelta

from django.db import models
from django.utils.translation import gettext_lazy as _

# The water type of a limit row for any water (farm.models.water.WaterLimit).
ANY_WATER = 'any'


class Status(models.TextChoices):
    """In order, worst first: the order "the worst of" reads."""
    CRITICAL = 'critical', _('Critical')
    WARNING = 'warning', _('Warning')
    OK = 'ok', _('OK')
    NO_LIMIT = 'no_limit', _('No limit')
    STALE = 'stale', _('Stale')
    NOT_MEASURED = 'not_measured', _('Not measured')


RANK = {status: rank for rank, status in enumerate(Status)}
ALERTS = (Status.CRITICAL, Status.WARNING)


def worst(statuses):
    return min(statuses, key=RANK.__getitem__, default=Status.NOT_MEASURED)


def judge(value, limit):
    """One value against one limit row (its four bounds, any of them empty)."""
    if limit.critical_low is not None and value < limit.critical_low:
        return Status.CRITICAL
    if limit.critical_high is not None and value > limit.critical_high:
        return Status.CRITICAL
    if limit.warning_low is not None and value < limit.warning_low:
        return Status.WARNING
    if limit.warning_high is not None and value > limit.warning_high:
        return Status.WARNING
    return Status.OK


class Limits:
    """The live limit rows, found by species, parameter and water type."""

    def __init__(self, rows):
        self.rows = {(row.species_id, row.parameter, row.water_type): row for row in rows}

    def applying(self, species_id, parameter, water_type):
        """The row for the water type, else the row for any water, else None."""
        return self.rows.get((species_id, parameter, water_type)) or self.rows.get((species_id, parameter, ANY_WATER))

    def assess(self, parameter, value, exposures):
        """(status, the rows that judged it) for a value and the fish it concerns: `exposures` is a list
        of (species id, water type), one per species in its unit (a loop sample: per unit of the loop)."""
        found = []
        for species_id, water_type in exposures:
            row = self.applying(species_id, parameter, water_type)
            if row is not None and row not in found:
                found.append(row)
        if not found:
            return Status.NO_LIMIT, []
        return worst(judge(value, row) for row in found), found

    def uncovered(self, parameter, exposures):
        """The species of `exposures` that no row judges `parameter` for, in their order: a unit with salmon judged and
        lumpfish beside them with no row is not judged for the lumpfish, whatever the salmon's row says."""
        return tuple(dict.fromkeys(species_id for species_id, water_type in exposures
                                   if self.applying(species_id, parameter, water_type) is None))


def is_fresh(parameter, measured_at, now, fresh_for=None):
    """The one freshness rule: a value says something about the water now for its parameter's `fresh_hours`, or, for a
    live value, for `fresh_for` seconds (a sensor channel's three heartbeats)."""
    limit = timedelta(seconds=fresh_for) if fresh_for is not None else timedelta(hours=parameter.fresh_hours)
    return now - measured_at <= limit
