"""The one write path of the health records that are not edited on a form: treatments (record, change the
last day, void), sea-lice counts (record, void) and the void of a health event (a health event is recorded
and edited on its form, farm/forms/health.py). Each runs in one transaction with the stock's own rules where
they are the same: the units locked as a stock operation locks them (so a treatment and a harvest of a unit
take turns), the farm's dates (farm/stock/dates.py), the form's token, and one void for every daily record
(farm.stock.services.voided). The other way round, the stock service refuses an operation that would leave a
treatment or a count without fish on its day.

A failure raises ValidationError (a dict of field to message) and nothing is written.

The treatment rules (the source's write-time checks, fish-health/services/treatment-application.service.ts:
84-134, on our own lists): a bath, a medicated feed, an injection or a dip names its medicine, and is given the
way the medicine is (its administration), so the lice report's method follows from it; a treatment without a
medicine names none; "other" (method or reason) says what it was in the notes; a vaccination uses a vaccine
and a vaccine is a vaccination; a dose and an amount come with their units (the model's checks). All units on
one site, each holding fish on the first day; the first day follows the date rule of every daily record, the
last day may be planned up to PLANNED_DAYS ahead.

Before a treatment the fish fast (the shared handling check, farm/handling/check.py, kind treatment: a
withdrawal is no reason to warn before one): every unit is checked on the first day, except for medicated feed,
which is the feeding itself. Too short a fast is a warning; the person goes on by acknowledging the warnings they
were shown, which are stored on the treatment (HandlingAcknowledgement) and make its log entry critical (owner
decision: warn, never block)."""
import hashlib
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import transaction
from django.utils.translation import gettext as _, gettext_lazy, ngettext

from core import audit
from core.models import AuditLog
from farm.feeding import read as feeding_read
from farm.handling import check
from farm.health import lice, read as health_read, withdrawal
from farm.models import Batch, HealthEvent, LiceCount, Medicine, StockOperation, Tank, Treatment
from farm.models.handling import HandlingKind
from farm.models.health import MEDICINAL, PLANNED_DAYS, TreatmentMethod, TreatmentReason
from farm.stock.dates import check_date, earliest, local_today, shown_date, sites_of
from farm.stock.read import Presence
from farm.stock.services import AlreadyRecorded, locked, voided

# The fields the activity log shows for a new treatment and a new lice count.
TREATMENT_FIELDS = ['units', 'method', 'medicine', 'reason', 'start_date', 'end_date', 'dose_value', 'dose_unit',
                    'amount_value', 'amount_unit', 'bath_minutes', 'prescribed_by', 'prescription_ref', 'vet',
                    'health_event', 'notes']
COUNT_FIELDS = ['unit', 'date', 'fish_counted', 'adult_females', 'mobile', 'attached', 'notes']
# The methods that have a bath time.
BATHS = (TreatmentMethod.BATH, TreatmentMethod.DIP, TreatmentMethod.FRESHWATER)


def treatment_label(treatment, units=None):
    """How the activity log names a treatment: what, where, which medicine and when, in English."""
    units = units if units is not None else list(treatment.units.all())
    what = treatment.medicine.name if treatment.medicine_id else audit.english(treatment.get_method_display())
    return (f'{audit.english(gettext_lazy("Treatment"))} · {", ".join(sorted(unit.code for unit in units))} · '
            f'{what} · {treatment.start_date.isoformat()}–{treatment.end_date.isoformat()}')


def count_label(count):
    return f'{audit.english(gettext_lazy("Sea-lice count"))} · {count.unit.code} · {count.date.isoformat()}'


def event_label(event):
    return f'{audit.english(gettext_lazy("Health event"))} · {event.site} · {event}'


def _already(model, token):
    if token is not None:
        done = model.all_objects.filter(entry_key=token).first()
        if done is not None:
            raise AlreadyRecorded(done)


def _site_key(unit):
    department = unit.production_department
    return ('site', department.site_id) if department.site_id else ('department', department.pk)


def _has_fish(unit, day, kind):
    return health_read.has_fish_for(kind, feeding_read.book_on(unit, day))


def _no_fish(unit, day):
    return _('%(unit)s holds no fish on %(date)s.') % {'unit': unit.code, 'date': shown_date(day)}


def _check_last_day(start_date, end_date, units):
    if end_date < start_date:
        raise ValidationError({'end_date': _('The last day cannot be before the first.')})
    latest = min(local_today(unit) for unit in units) + timedelta(days=PLANNED_DAYS)
    if end_date > latest:
        raise ValidationError({'end_date': _('The last day can be planned at most %(days)d days ahead.') % {
            'days': PLANNED_DAYS}})


def _check_medicine(method, reason, medicine):
    medicinal = method in MEDICINAL
    if medicinal and medicine is None:
        raise ValidationError({'medicine': _('A bath, medicated feed, injection or dip names its medicine.')})
    if not medicinal and medicine is not None:
        raise ValidationError({'medicine': _('A treatment without a medicine names none: choose a bath, medicated '
                                             'feed, injection or dip as the method.')})
    if medicine is None:
        if reason == TreatmentReason.VACCINATION:
            raise ValidationError({'reason': _('A vaccination is given with a vaccine.')})
        return
    medicine = Medicine.all_objects.get(pk=medicine.pk)
    if medicine.is_deleted or medicine.status != Medicine.Status.ACTIVE:
        raise ValidationError({'medicine': _('%(medicine)s is inactive: a new treatment takes an active medicine.')
                               % {'medicine': medicine}})
    if method != medicine.administration:
        raise ValidationError({'method': _('%(medicine)s is given as %(administration)s.') % {
            'medicine': medicine, 'administration': str(medicine.get_administration_display()).lower()}})
    if medicine.is_vaccine != (reason == TreatmentReason.VACCINATION):
        raise ValidationError({'reason': _('A vaccine is given as a vaccination, and a vaccination with a vaccine.')})


def _check_event(event, units, day):
    event = HealthEvent.all_objects.get(pk=event.pk)
    site_ids = {unit.production_department.site_id for unit in units}
    if event.is_deleted or site_ids != {event.site_id}:
        raise ValidationError({'health_event': _('Choose a health event of the site of these units.')})
    if event.date > day:
        raise ValidationError({'health_event': _('The health event is dated %(date)s, after this treatment.') % {
            'date': shown_date(event.date)}})


# ---- treatments ---------------------------------------------------------------------------------------
@dataclass
class TreatmentHandling:
    """What a treatment's dialog asks before it is saved, as one: the handling check over its units
    (farm.handling.check.assess for each: the fast) and what the treatment leaves out of a report (`reported`,
    LeftOutOfLiceReport); the warnings, the notes (named by unit when there are several) and one fingerprint for the
    form's box. The fast protects fish: going on past it is stored and logged as critical; a report's warning is logged
    with the entry. What the treatment does to the withdrawals (harvests already recorded inside the one it creates) is
    the withdrawal guard's, asked through its own box (farm.health.withdrawal.guarded)."""
    assessments: list = field(default_factory=list)
    reported: list = field(default_factory=list)

    @property
    def handling_warnings(self):
        return [warning for assessment in self.assessments for warning in assessment.warnings]

    @property
    def warnings(self):
        return self.handling_warnings + self.reported

    @property
    def notes(self):
        if len(self.assessments) == 1:
            return self.assessments[0].notes
        return [f'{assessment.unit.code}: {note}' for assessment in self.assessments for note in assessment.notes]

    @property
    def fingerprint(self):
        keys = [f'{assessment.unit.pk}:{assessment.fingerprint}' for assessment in self.assessments
                if assessment.warnings] + [found.key() for found in self.reported]
        return hashlib.sha256('|'.join(keys).encode()).hexdigest()[:20] if keys else ''

    def messages(self):
        return [warning.message() for warning in self.warnings]


@dataclass(frozen=True)
class LeftOutOfLiceReport:
    """A sea-lice medicine given for another reason (farm.health.lice.left_out_of_lice_report): the weekly sea-lice report
    will not list the treatment. A warning of the treatment's dialog, never a refusal (hydrogen peroxide is also an AGD
    treatment)."""
    medicine: Medicine
    reason: str

    warning = ''                             # not a handling warning: nothing is stored but the log entry

    def key(self):
        return f'lice_report:{self.medicine.pk}:{self.reason}'

    def message(self):
        return _('%(medicine)s is a sea-lice medicine, given here for “%(reason)s”: the weekly sea-lice report to '
                 'Mattilsynet lists only the treatments for sea lice, so this one will not be in it.') % {
            'medicine': self.medicine, 'reason': TreatmentReason(self.reason).label}


def handling(units, day, method, medicine=None, reason=None):
    """What a treatment of `units` from `day` with `medicine` for `reason` asks before it is saved (TreatmentHandling):
    the fast before it (nothing for medicated feed, which is the feeding itself) and whether the weekly sea-lice report
    leaves it out; no fast before a day is chosen."""
    units = sorted(units, key=lambda unit: unit.code)
    reported = []
    if reason and lice.left_out_of_lice_report(medicine, reason):
        reported.append(LeftOutOfLiceReport(medicine, reason))
    if day is None or not units or method == TreatmentMethod.IN_FEED:
        return TreatmentHandling(reported=reported)
    return TreatmentHandling([check.assess(HandlingKind.TREATMENT, unit, day) for unit in units], reported)


def _lock_fish(unit_ids, first):
    """Locks the batches with fish in the units from `first` on, then the units, in the order a stock operation locks
    them (farm.stock.services: batches, then units), so a treatment and a harvest of the same fish take turns and the
    withdrawal guard sees every harvest committed before it. Returns (the units, the batch ids): the fish the treatment
    can reach, which the guard works the withdrawals of."""
    presence = Presence.of_units(unit_ids)
    batch_ids = {batch_id for unit_id in unit_ids for batch_id in presence.batches.get(unit_id, ())
                 if presence.present_between(unit_id, batch_id, first, date.max)}
    locked(Batch, batch_ids)
    return list(locked(Tank, set(unit_ids)).values()), batch_ids


def _today(units):
    return min(local_today(unit) for unit in units)


def record_treatment(user, *, units, method, reason, start_date, end_date, medicine=None, dose_value=None,
                     dose_unit='', amount_value=None, amount_unit='', bath_minutes=None, prescribed_by='',
                     prescription_ref='', vet=None, health_event=None, notes='', handling_ack=None, token=None):
    """A course given to the fish of `units` from `start_date` to `end_date` (see the module's rules);
    `handling_ack` is the fingerprint of the handling warnings the person went on past. The withdrawal it creates goes
    through the withdrawal guard (harvests already recorded inside it are asked about)."""
    if not units:
        raise ValidationError({'units': _('Choose the units that were treated.')})
    if len({unit.pk for unit in units}) != len(units):
        raise ValidationError({'units': _('Each unit can be listed once.')})
    with transaction.atomic():
        locked_units, batch_ids = _lock_fish([unit.pk for unit in units], start_date)
        _already(Treatment, token)
        for unit in locked_units:
            if unit.is_deleted:
                raise ValidationError({'units': _('%(unit)s is deleted.') % {'unit': unit.code}})
        if len({_site_key(unit) for unit in locked_units}) > 1:
            raise ValidationError({'units': _('A treatment is of the units of one site: record one for each site.')})
        check_date(start_date, locked_units)
        _check_last_day(start_date, end_date, locked_units)
        _check_medicine(method, reason, medicine)
        if method == TreatmentMethod.OTHER or reason == TreatmentReason.OTHER:
            if not notes.strip():
                raise ValidationError({'notes': _('Say what it was: the method or the reason is “other”.')})
        if bath_minutes is not None and method not in BATHS:
            raise ValidationError({'bath_minutes': _('Only a bath, a dip or a freshwater bath has a bath time.')})
        if health_event is not None:
            _check_event(health_event, locked_units, start_date)
        for unit in sorted(locked_units, key=lambda item: item.code):
            if not _has_fish(unit, start_date, 'treatment'):
                raise ValidationError({'units': _no_fish(unit, start_date)})
        checked = handling(locked_units, start_date, method, medicine, reason)
        check.require_acknowledged(checked, handling_ack, user=user)

        def write():
            treatment = Treatment(
                method=method, medicine=medicine, reason=reason, start_date=start_date, end_date=end_date,
                dose_value=dose_value, dose_unit=dose_unit, amount_value=amount_value, amount_unit=amount_unit,
                bath_minutes=bath_minutes, prescribed_by=prescribed_by.strip(), prescription_ref=prescription_ref.strip(),
                vet=vet, health_event=health_event, notes=notes.strip(), entry_key=token, created_by=user,
                updated_by=user)
            treatment.full_clean()
            treatment.save()
            treatment.units.set(locked_units)
            for assessment in checked.assessments:
                if assessment.warnings:
                    check.acknowledge(treatment, assessment)
            with audit.source_language():
                values = audit.snapshot(treatment, TREATMENT_FIELDS)
                critical = _acknowledged(values, checked)
                audit.record_create(user, treatment, values, label=treatment_label(treatment, locked_units),
                                    severity=AuditLog.Severity.CRITICAL if critical else AuditLog.Severity.NORMAL)
            return treatment

        return withdrawal.guarded(user, batch_ids, _today(locked_units), write)


def _acknowledged(values, checked):
    """Adds the warnings gone past to the log entry's values, in English; whether there were handling warnings among
    them (the entry is then critical)."""
    handling_warnings = [warning.message() for warning in checked.handling_warnings]
    if handling_warnings:
        values[str(gettext_lazy('Handling warnings acknowledged'))] = ' '.join(handling_warnings)
    if checked.reported:
        values[str(gettext_lazy('Warnings acknowledged'))] = ' '.join(warning.message() for warning in checked.reported)
    return bool(handling_warnings)


def _treatment_fish(treatment_id, first):
    """Locks the fish of a stored treatment's units (_lock_fish) before the treatment itself."""
    unit_ids = list(Treatment.units.through.objects.filter(treatment_id=treatment_id).values_list('tank_id', flat=True))
    return _lock_fish(unit_ids, first)


def change_last_day(user, treatment, end_date):
    """The course ended on another day than planned, or goes on longer: the withdrawal counts from the new
    last day. Logged with the old and new day; refused for a voided treatment, and outside the backdating
    window (neither the old nor the new last day may be older than it). Through the withdrawal guard: a longer
    withdrawal that reaches over a harvest already recorded, or a shorter one that frees fish held today, is asked
    about. The units and their batches are locked first, as a harvest locks them."""
    with transaction.atomic():
        start = Treatment.all_objects.filter(pk=treatment.pk).values_list('start_date', flat=True).first()
        _units, batch_ids = _treatment_fish(treatment.pk, start or end_date)
        treatment = Treatment.all_objects.select_for_update(of=('self',)).get(pk=treatment.pk)
        units = list(treatment.units.select_related('production_department__site'))
        if treatment.is_deleted:
            raise ValidationError({NON_FIELD_ERRORS: _('This treatment is voided.')})
        _check_last_day(treatment.start_date, end_date, units)
        first = max(earliest(unit) for unit in units)
        if min(end_date, treatment.end_date) < first:
            raise ValidationError({'end_date': _('A last day older than %(date)s cannot be changed.') % {
                'date': shown_date(first)}})
        if end_date == treatment.end_date:
            return treatment
        def write():
            current = Treatment.all_objects.get(pk=treatment.pk)       # as stored: a write tried is made again
            with audit.source_language():
                before = audit.snapshot(current, ['end_date'])
                current.end_date = end_date
                current.updated_by = user
                current.version += 1
                current.save(update_fields=['end_date', 'updated_by', 'version', 'updated_at'])
                audit.record_update(user, current, before, audit.snapshot(current, ['end_date']),
                                    label=treatment_label(current, units))
            return current

        return withdrawal.guarded(user, batch_ids, _today(units), write)


def void_treatment(user, treatment, reason):
    """The undo: the treatment stops counting, with its reason, and its withdrawal with it: through the withdrawal guard
    (fish held today that it frees, and the medicated feedings it covered, now of unknown end, are asked about)."""
    with transaction.atomic():
        start = Treatment.all_objects.filter(pk=treatment.pk).values_list('start_date', flat=True).first()
        _units, batch_ids = _treatment_fish(treatment.pk, start)
        treatment = (Treatment.all_objects.select_for_update(of=('self',)).select_related('medicine')
                     .get(pk=treatment.pk))
        units = list(treatment.units.select_related('production_department__site'))
        def write():
            current = Treatment.all_objects.select_related('medicine').get(pk=treatment.pk)   # as stored
            voided(user, current, reason, sites_of(units), treatment_label(current, units))
            return current

        return withdrawal.guarded(user, batch_ids, _today(units), write)


# ---- sea-lice counts ----------------------------------------------------------------------------------
def record_lice_count(user, *, unit, day, fish_counted, adult_females, mobile, attached, notes='', token=None):
    """The lice found on the fish examined in `unit` on `day`, in total per stage. The unit holds fish that
    day; one live count per unit and day (a correction is a void and a new count)."""
    with transaction.atomic():
        unit = locked(Tank, {unit.pk})[unit.pk]
        _already(LiceCount, token)
        if unit.is_deleted:
            raise ValidationError({'unit': _('%(unit)s is deleted.') % {'unit': unit.code}})
        check_date(day, [unit])
        if not _has_fish(unit, day, 'lice_count'):
            raise ValidationError({'date': _no_fish(unit, day)})
        if LiceCount.objects.filter(unit=unit, date=day).exists():
            raise ValidationError({'date': _('%(unit)s already has a count on %(date)s: void it first to correct '
                                             'it.') % {'unit': unit.code, 'date': shown_date(day)}})
        count = LiceCount(unit=unit, date=day, fish_counted=fish_counted, adult_females=adult_females, mobile=mobile,
                          attached=attached, notes=notes.strip(), entry_key=token, created_by=user, updated_by=user)
        count.full_clean()
        count.save()
        with audit.source_language():
            audit.record_create(user, count, audit.snapshot(count, COUNT_FIELDS), label=count_label(count))
        return count


def void_lice_count(user, count, reason):
    with transaction.atomic():
        count = (LiceCount.all_objects.select_for_update(of=('self',))
                 .select_related('unit__production_department__site').get(pk=count.pk))
        voided(user, count, reason, sites_of([count.unit]), count_label(count))
        return count


# ---- health events ------------------------------------------------------------------------------------
def void_event(user, event, reason):
    """A health event recorded by mistake stops counting, with its reason. Refused while a live treatment or
    stock operation names it (void or re-record those first), and outside the site's backdating window."""
    with transaction.atomic():
        event = HealthEvent.all_objects.select_for_update(of=('self',)).select_related('site').get(pk=event.pk)
        operations = StockOperation.objects.filter(health_event=event).count()
        treatments = Treatment.objects.filter(health_event=event).count()
        if operations or treatments:
            raise ValidationError({NON_FIELD_ERRORS: ngettext(
                '%(count)d record names this event (mortality, cull or treatment): void it first.',
                '%(count)d records name this event (mortality, cull or treatment): void them first.',
                operations + treatments) % {'count': operations + treatments}})
        voided(user, event, reason, [event.site], event_label(event))
        return event
