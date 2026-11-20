"""The stored samples whose pH was measured on another scale than NBS, put on the NBS scale again by the application's
formula (the water-chemistry audit of 2026-11-19, consensus point 8; the owner's decision of the same day: formula 4).

A sample's `ph` is the NBS pH its `ph_as_measured` was converted to when it was written (services.on_nbs), by the formula
named in `ph_converted_formula`. Formula 4 changed the step between the NBS and the seawater scales (Millero 1986:
chemcore/core/src/formula4.rs), so a sample converted by formula 3 holds an NBS pH up to about 0.04 lower or higher than
the same measurement typed today, and its NH₃ would differ from the same reading's by up to about 9 % in cold sea water:
the same water, two numbers. Here each such sample is converted again from what was measured, with the sample's own
temperature and salinity and its point's water origin, exactly as the sample door converts a new one (`read.ph_on_nbs`,
`read.scale_origin`), and its `ph` and `ph_converted_formula` are rewritten. What was measured is never touched.

Samples are never edited otherwise (services, WQ-12): this is the one rewrite, of a converted value, and each is logged
in the activity log as a change of the sample, with the NBS pH and the formula before and after and why, so the old
value stays readable. A sample the conversion now refuses (its point's water said to be salt-added since, or a water the
core cannot work out) is left as it was and listed, never guessed at. Running it again changes nothing: a sample
converted by the application's formula is not read. Voided and deleted samples are converted too (a restore brings one
back), each logged.

`manage.py rederive_ph` runs it (`--dry-run` reads only); the check farm.W001 (`manage.py check --database default`)
says how many samples are left on an older formula."""
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_noop

from core import audit
from core.models import AuditLog
from farm import withdrawal_gate
from farm.models import WaterMeasurement

from . import chemistry
from .read import POINT_RELATED, Context, ph_on_nbs, scale_origin
from .services import label

# Why a sample's NBS pH was rewritten, as the activity log stores it (English at rest, shown translated).
WHY = gettext_noop('The pH measured on another scale was put on the NBS scale again by the application’s formula '
                   '(formula 4: Millero’s 1986 step between the scales); what was measured is unchanged.')
WHY_LABEL = gettext_noop('Why')
# The sample's columns the rewrite changes, logged before and after as the sample door logs them (services.LOGGED).
LOGGED = ['ph', 'ph_converted_formula']
# Why the rewrite passes the withdrawal gate: no withdrawal reads a sample's pH.
GATE_REASON = "rederive_ph: a sample's NBS pH and its formula only, never its temperature"


@dataclass(frozen=True)
class Found:
    """One stored sample on an older formula: what it holds and what the application's formula gives (`new` None:
    refused, `why` the core's reason)."""
    sample: WaterMeasurement
    old: Decimal
    old_formula: int
    new: Decimal | None
    formula: int | None
    why: str = ''

    @property
    def moved(self):
        return self.new is not None and self.new != self.old

    def line(self):
        sample = self.sample
        head = (f'{sample.pk} {sample.measured_at.isoformat()} {sample.point}: {sample.ph_scale} '
                f'{sample.ph_as_measured} at {sample.temperature_c} °C, {sample.salinity_ppt} ‰'
                f'{" (voided or deleted)" if sample.is_deleted else ""}: pH NBS {self.old} by formula '
                f'{self.old_formula}')
        if self.new is None:
            return f'{head}; NOT converted again ({self.why})'
        return f'{head} -> {self.new} by formula {self.formula}{"" if self.moved else " (the same)"}'


def stale():
    """The samples (all, voided and deleted too) whose pH was put on the NBS scale by another formula than the
    application's."""
    return (WaterMeasurement.all_objects.exclude(ph_scale='').exclude(ph_converted_formula=chemistry.FORMULA_VERSION)
            .select_related(*POINT_RELATED).order_by('measured_at', 'id'))


def plan():
    """[Found] of every stale sample, nothing written."""
    samples = list(stale())
    served = Context._served(list({sample.point_id: sample.point for sample in samples}.values())) if samples else {}
    found = []
    for sample in samples:
        converted = ph_on_nbs(sample.ph_as_measured, sample.ph_scale, sample.temperature_c, sample.salinity_ppt,
                              scale_origin(served[sample.point_id]))
        why = '' if converted.value is not None else (converted.error or converted.refused)
        found.append(Found(sample, sample.ph, sample.ph_converted_formula, converted.value, converted.formula, why))
    return found


def apply(user=None):
    """Converts every stale sample again, in one transaction, each logged; returns the [Found] (the refused ones left
    as they were). The rows are locked first, so a sample written meanwhile by the sample door (already by the
    application's formula) is not read."""
    with transaction.atomic():
        list(stale().select_for_update(of=('self',)).values_list('pk', flat=True))
        found = plan()
        for item in found:
            if item.new is None:
                continue
            sample = item.sample
            with audit.source_language():
                before = audit.snapshot(sample, LOGGED)
                sample.ph, sample.ph_converted_formula = item.new, item.formula
                changes = audit.diff(before, audit.snapshot(sample, LOGGED))
                changes[str(_(WHY_LABEL))] = [None, audit.message(WHY)]
                audit.record(user, AuditLog.Action.UPDATE, sample, changes, label=label(sample))
            # Behind the withdrawal gate (farm/withdrawal_gate.py: every write of a sample counts there): only the NBS pH
            # and its formula move, never the temperature a withdrawal's degree-days are worked out from.
            with withdrawal_gate.opened(GATE_REASON):
                WaterMeasurement.all_objects.filter(pk=sample.pk, measured_at=sample.measured_at).update(
                    ph=item.new, ph_converted_formula=item.formula, version=F('version') + 1, updated_at=timezone.now())
    return found
