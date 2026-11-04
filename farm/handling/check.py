"""The one handling check: before fish are harvested, is a medicine withdrawal in force, and before fish are
harvested, transported, graded or treated, have they fasted long enough?

    check(kind, unit, day, batch=None) -> [HandlingWarning]      the warnings, for the save and the pages
    assess(kind, unit, day, batch=None) -> Assessment            the warnings and what the dialog says besides

`kind` is a HandlingKind: harvest, transport (a transfer), grading, treatment (the health tab's dialog).
Without a batch, every batch in the unit that day counts. Pure reads of stored facts, inside the caller's
transaction: the stock service runs it after its locks (a feeding of the unit takes turns with it).

- Withdrawal (a harvest only: the fish go to food, to the slaughter facility the harvest names; a medicine
  withdrawal is a meat withdrawal, so it means nothing when live fish are moved or graded, and a treatment during
  a withdrawal harms nobody): every block the registry gives (farm/handling/withdrawal.py) for the batch whose
  `until` is after the day, or unknown. With no provider the harvest dialog says "Medicine withdrawal not
  checked" and nothing is warned. A transfer or a grading is checked for the fast and the live-transfer facts
  alone.
- Fasting: the hours since the fish's last feeding against the rule (farm/handling/fasting.py) and, for a harvest
  whose rule asks for purging in degree-days, the degree-days of the full days since it; each that the rule asks for
  must be reached, the later decides. No rule, or no feeding found in the 31 days before, is said, not warned.

- Earliest suitable harvest date (`earliest`, a harvest's dialog, the drawer and the plan pages): the later of the end
  of the batch's medicine withdrawal and the first day its purge (the fast of the rule, from the last feeding) can be
  complete, and which of the two decides. Built from the two parts above, nothing stored; a planned date before it is
  a warning on the same terms as the parts', never a block.

Nothing is blocked (owner decision). The dialogs offer one box for every warning shown; it carries the
warnings' fingerprint, so a save whose warnings changed meanwhile (a feeding recorded, a treatment entered,
another date) is asked again. Going on writes one HandlingAcknowledgement per warning (`acknowledge`) and the
operation's activity-log entry is critical."""
import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import formats
from django.utils.translation import gettext as _

from farm.feeding.read import book_on, last_fed_at
from farm.models import Batch, HandlingAcknowledgement, Treatment
from farm.models.handling import AcknowledgedWarning, HandlingKind, HandlingRule
from farm.stock.dates import local_today
from farm.water.degree_days import BatchWater, degree_days_text, missing_sentence

from . import fasting, withdrawal
from .fasting import DAY, LOOKBACK_DAYS, asks_text, both_text, hours_text, shown_moment

# The one handling a medicine withdrawal matters for: the fish go to food (a harvest names the slaughter facility).
# Live fish that are moved or graded are not eaten: their medicine is no concern of the handling check.
WITHDRAWAL_KIND = HandlingKind.HARVEST


def _date(day):
    return formats.date_format(day, 'DATE_FORMAT')


def withdrawal_text(block):
    """The withdrawal as a sentence, starting "Not suitable for harvest" (owner's words): it is only ever said
    for a harvest."""
    params = {'batch': block.batch.code, 'date': _date(block.until) if block.until else ''}
    if block.until is None:
        return _('Not suitable for harvest — medicine withdrawal of %(batch)s, its end unknown.') % params
    if block.approximate:
        return _('Not suitable for harvest — medicine withdrawal of %(batch)s until about %(date)s.') % params
    return _('Not suitable for harvest — medicine withdrawal of %(batch)s until %(date)s.') % params


@dataclass(frozen=True)
class HandlingWarning:
    """One warning of the check (the contract's Warning; named so as not to hide Python's own Warning)."""
    warning: str                         # AcknowledgedWarning: withdrawal | fasting
    kind: str                            # HandlingKind
    unit: object
    day: date
    block: withdrawal.WithdrawalBlock = None
    last_fed_at: datetime = None
    fasted_hours: Decimal = None
    rule: HandlingRule = None
    fasted_degree_days: Decimal = None   # a harvest's purging: the degree-days since the last feeding
    accrual: object = None               # how they were found (farm.water.degree_days.Accrual)

    @property
    def required_hours(self):
        return self.rule.min_fasting_hours if self.rule is not None else None

    @property
    def required_degree_days(self):
        return self.rule.min_fasting_degree_days if self.rule is not None else None

    def key(self):
        """What the person saw, as text: a change in it asks them again."""
        if self.warning == AcknowledgedWarning.WITHDRAWAL:
            block = self.block
            return f'withdrawal:{block.batch.pk}:{block.until}:{block.approximate}:{block.reason}'
        return (f'fasting:{self.rule.pk}:{self.required_hours}:{self.required_degree_days}:{self.fasted_degree_days}:'
                f'{self.last_fed_at.isoformat()}')

    def message(self):
        """The warning in the person's language (the activity log builds it in English)."""
        if self.warning == AcknowledgedWarning.WITHDRAWAL:
            text = withdrawal_text(self.block)
            return f'{text} {self.block.reason}' if self.block.reason else text
        text = _('Last fed %(moment)s, %(fasted)s before %(day)s: the %(kind)s rule asks for %(asked)s.') % {
            'moment': shown_moment(self.last_fed_at, self.unit),
            'fasted': both_text(None if self.required_hours is None else hours_text(self.fasted_hours),
                                None if self.required_degree_days is None else degree_days_text(self.fasted_degree_days)),
            'day': _date(self.day), 'kind': str(HandlingKind(self.kind).label).lower(),
            'asked': asks_text(self.required_hours, self.required_degree_days)}
        if self.accrual is not None and self.accrual.missing:
            text += ' ' + missing_sentence(self.accrual.missing, self.accrual.assumed)
        return text


@dataclass
class Assessment:
    """The check's result for a dialog: the warnings, and the plain lines it says besides (when the fish were
    last fed, the rule, a withdrawal not checked, for a harvest the earliest suitable date)."""
    kind: str
    unit: object
    day: date
    batch: object = None
    warnings: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    earliest: object = None              # a harvest's Earliest (the latest of its batches)

    @property
    def fingerprint(self):
        """The warnings as the acknowledgement box carries them; '' when there are none."""
        if not self.warnings:
            return ''
        keys = '|'.join(sorted(warning.key() for warning in self.warnings))
        return hashlib.sha256(keys.encode()).hexdigest()[:20]

    def messages(self):
        return [warning.message() for warning in self.warnings]


def _batches_in(unit, day):
    """The batches in the unit at the start of the day (at its end when it was empty then)."""
    return list(Batch.all_objects.filter(pk__in=book_on(unit, day).weights).select_related('species'))


def assess(kind, unit, day, batch=None, with_earliest=True):
    """The warnings and notes of handling the fish of `batch` (or every batch) in `unit` on `day`; for a harvest, with
    the earliest suitable date among the notes (`with_earliest`: the save, which needs only the warnings, leaves it)."""
    result = Assessment(kind, unit, day, batch)
    batches = [batch] if batch is not None else _batches_in(unit, day)
    if kind == WITHDRAWAL_KIND:
        _withdrawal(result, batches)
    _fasting(result, batches)
    if kind == WITHDRAWAL_KIND and with_earliest:
        _earliest(result, batches)
    return result


def check(kind, unit, day, batch=None):
    """The warnings of handling the fish of `batch` (or every batch) in `unit` on `day` (assess)."""
    return assess(kind, unit, day, batch).warnings


def in_force(unit, day, batches=None):
    """The withdrawal blocks in force for the fish in `unit` on `day` (of `batches` only, when given): their
    `until` is after the day, or unknown. None when no provider is registered: not checked."""
    found = withdrawal.blocks(unit, day)
    if found is None:
        return None
    held = None if batches is None else {each.pk for each in batches}
    return [block for block in found if (held is None or block.batch.pk in held)
            and (block.until is None or block.until > day)]


def _withdrawal(result, batches):
    blocks = in_force(result.unit, result.day, batches)
    if blocks is None:
        result.notes.append(_('Medicine withdrawal not checked: the health records are not in yet.'))
        return
    for block in blocks:
        result.warnings.append(HandlingWarning(AcknowledgedWarning.WITHDRAWAL, result.kind, result.unit,
                                               result.day, block=block))
    if not blocks:
        result.notes.append(_('No medicine withdrawal in force.'))


def _fasting(result, batches):
    unit, day = result.unit, result.day
    if not batches:
        return
    species = batches[0].species         # one species per unit (the stock service's rule)
    requirement = fasting.requirement_of(result.kind, species)
    label = str(HandlingKind(result.kind).label).lower()
    if requirement is None:
        result.notes.append(_('No handling rule for %(kind)s: the fast is not checked (Reference data › Handling '
                              'rules).') % {'kind': label})
    fed = last_fed_at(unit, day, batch=result.batch, since=day - timedelta(days=LOOKBACK_DAYS))
    if fed is None:
        result.notes.append(_('No feeding of these fish is recorded in the %(days)d days before %(day)s: the fast '
                              'is not checked.') % {'days': LOOKBACK_DAYS, 'day': _date(day)})
        return
    batch_ids = [each.pk for each in batches]
    water = None
    if requirement is not None and requirement.degree_days is not None:
        water = BatchWater(batch_ids, local_today(unit), fed.record.date + DAY)
    done = fasting.fasted(unit, day, fed, requirement, water, batch_ids)
    when = shown_moment(fed.moment, unit) if fed.timed else _('%(date)s, no time recorded: counted from the end of '
                                                              'the day') % {'date': _date(fed.record.date)}
    result.notes.append(_('Last fed %(when)s: %(fasted)s before %(day)s.') % {
        'when': when, 'fasted': done.text(requirement), 'day': _date(day)})
    if requirement is None:
        return
    result.notes.append(_('The %(kind)s rule for %(species)s asks for %(asked)s.') % {
        'kind': label, 'species': species.common_name, 'asked': requirement.text()})
    if done.accrual is not None and done.accrual.missing:
        result.notes.append(missing_sentence(done.accrual.missing, done.accrual.assumed))
    if not done.ok:
        result.warnings.append(HandlingWarning(
            AcknowledgedWarning.FASTING, result.kind, unit, day, last_fed_at=fed.moment, fasted_hours=done.hours,
            rule=requirement.rule, fasted_degree_days=done.degree_days, accrual=done.accrual))


# ---- the earliest suitable harvest date ---------------------------------------------------------------
WITHDRAWAL, PURGING = 'withdrawal', 'purging'


@dataclass(frozen=True)
class Earliest:
    """When fish may first be harvested: the later of the end of their medicine withdrawal and the first day their purge
    can be complete, and which of the two decides (`decides`; '' when nothing holds them). `day` is None when it cannot
    be known: the withdrawal's end is unknown. Read from the stored facts, nothing is stored."""
    batch: object
    day: date | None
    decides: str
    until: date | None = None             # the end of the withdrawal (the latest of the batch's blocks)
    approximate: bool = False             # ... projected
    unknown: bool = False                 # a block of unknown end holds the fish
    stop_by: date | None = None           # the last day they may be fed for the purge to be complete on `day`
    degrees_unknown: bool = False         # the purge's degree-days cannot be worked out: no temperature

    def holds(self, day):
        """Whether a harvest on `day` is earlier than the earliest suitable one."""
        return bool(self.decides) and (self.day is None or day < self.day)

    def text(self):
        """Earliest suitable harvest date: 17 Nov 2026. Medicine withdrawal decides: until 17 Nov 2026."""
        if not self.decides:
            return ''
        if self.day is None:
            text = _('Earliest suitable harvest date: not known.')
        else:
            text = _('Earliest suitable harvest date: %(date)s.') % {'date': _date(self.day)}
        if self.decides == WITHDRAWAL:
            if self.unknown:
                text += ' ' + _('Medicine withdrawal decides: its end is unknown.')
            elif self.approximate:
                text += ' ' + _('Medicine withdrawal decides: until about %(date)s.') % {'date': _date(self.until)}
            else:
                text += ' ' + _('Medicine withdrawal decides: until %(date)s.') % {'date': _date(self.until)}
        elif self.stop_by is not None:
            text += ' ' + _('Purging decides: feeding must stop by %(date)s.') % {'date': _date(self.stop_by)}
        else:
            text += ' ' + _('Purging decides.')
        if self.degrees_unknown:
            text += ' ' + _('Degree-days unknown: no temperature.')
        return text


def earliest(unit, batch, today=None):
    """The Earliest suitable harvest date of `batch` in `unit` on the farm's `today`: the end of its medicine withdrawal
    (the registry's blocks; unknown when a block's end is) and the first day its purge can be complete if it is not
    fed again, which is `fasted` asked of each day from today on, from the last feeding. Nothing holds the fish when
    there is no withdrawal in force, no rule, no feeding recorded in the 31 days before, or the fast is complete."""
    today = local_today(unit) if today is None else today
    blocks = in_force(unit, today, [batch]) or []
    dated = [block for block in blocks if block.until is not None]
    unknown = len(dated) < len(blocks)
    latest = max(dated, key=lambda block: block.until, default=None)
    requirement = fasting.requirement_of(HandlingKind.HARVEST, batch.species)
    purge_day, degrees_unknown, water = None, False, None
    if requirement is not None and requirement.asks:
        fed = last_fed_at(unit, today, batch=batch, since=today - timedelta(days=LOOKBACK_DAYS))
        if fed is not None:
            if requirement.degree_days:
                water = BatchWater({batch.pk}, today, fed.record.date + DAY)
            day = today
            for _n in range(fasting.MAX_FAST_DAYS + 1):
                done = fasting.fasted(unit, day, fed, requirement, water, [batch.pk])
                if done.ok:
                    purge_day = day if day > today else None
                    break
                day += DAY
            else:
                degrees_unknown = True              # never complete within the days looked at: said as unknown
    if unknown:
        return Earliest(batch, None, WITHDRAWAL, latest.until if latest else None, unknown=True,
                        degrees_unknown=degrees_unknown)
    if latest is not None and (purge_day is None or latest.until >= purge_day):
        return Earliest(batch, latest.until, WITHDRAWAL, latest.until, latest.approximate,
                        degrees_unknown=degrees_unknown)
    if purge_day is not None:
        start = fasting.start_of_fast(unit, purge_day, requirement, water, batch.pk)
        stop_by = start.starts_at.date() - DAY if start.starts_at is not None else None
        return Earliest(batch, purge_day, PURGING, latest.until if latest else None,
                        latest.approximate if latest else False, stop_by=stop_by, degrees_unknown=degrees_unknown)
    if degrees_unknown:                         # the purge cannot be worked out: not known, and said
        return Earliest(batch, None, PURGING, degrees_unknown=True)
    return Earliest(batch, today, '')


def _earliest(result, batches):
    """A harvest's earliest suitable date among the notes: of its batches, the latest."""
    found = [earliest(result.unit, batch) for batch in batches]
    held = [each for each in found if each.decides]
    if not held:
        return
    result.earliest = max(held, key=lambda each: (each.day is None, each.day or date.min))
    result.notes.append(result.earliest.text())


def require_acknowledged(assessment, seen, field='handling_ack'):
    """Refuses a save with warnings the person has not gone on past exactly as they are now (`seen`: the
    fingerprint the form's box carried); they are asked, or asked again. `assessment` has `warnings` and a
    `fingerprint` (an Assessment, or the treatment's over its units, or an experiment's start). The error is
    reported on `field`, the name of the form's box."""
    if assessment.warnings and seen != assessment.fingerprint:
        if not seen:
            message = _('Tick the box to go on despite these warnings.')
        else:
            message = _('The warnings changed since the form was shown: read them again, and tick the box to go on.')
        raise ValidationError({field: message})


def acknowledge(record, assessment):
    """Stores the warnings a person went on past, one row each, with what they were shown, on the stock
    operation or the treatment (`record`) they were given for."""
    link = {'treatment': record} if isinstance(record, Treatment) else {'operation': record}
    rows = []
    for warning in assessment.warnings:
        if warning.warning == AcknowledgedWarning.WITHDRAWAL:
            block = warning.block
            rows.append(HandlingAcknowledgement(
                **link, warning=warning.warning, withdrawal_until=block.until,
                withdrawal_approximate=block.approximate, withdrawal_reason=block.reason[:500]))
        else:
            rows.append(HandlingAcknowledgement(
                **link, warning=warning.warning, last_fed_at=warning.last_fed_at,
                fasted_hours=warning.fasted_hours, required_hours=warning.required_hours,
                fasted_degree_days=warning.fasted_degree_days, required_degree_days=warning.required_degree_days,
                rule=warning.rule))
    HandlingAcknowledgement.objects.bulk_create(rows)
    return rows
