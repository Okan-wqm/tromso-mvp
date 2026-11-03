"""The one handling check: before fish are harvested, transported, graded or treated, is a medicine
withdrawal in force, and have they fasted long enough?

    check(kind, unit, day, batch=None) -> [HandlingWarning]      the warnings, for the save and the pages
    assess(kind, unit, day, batch=None) -> Assessment            the warnings and what the dialog says besides

`kind` is a HandlingKind: harvest, transport (a transfer), grading, treatment (the health tab's dialog).
Without a batch, every batch in the unit that day counts. Pure reads of stored facts, inside the caller's
transaction: the stock service runs it after its locks (a feeding of the unit takes turns with it).

- Withdrawal (harvest, transport, grading; a treatment during a withdrawal harms nobody): every block the
  registry gives (farm/handling/withdrawal.py) for the batch whose `until` is after the day, or unknown. With
  no provider the dialog says "Medicine withdrawal not checked" and nothing is warned.
- Fasting: the hours since the fish's last feeding against the rule (farm/handling/fasting.py). No rule, or
  no feeding found in the 31 days before, is said, not warned.

Nothing is blocked (owner decision). The dialogs offer one box for every warning shown; it carries the
warnings' fingerprint, so a save whose warnings changed meanwhile (a feeding recorded, a treatment entered,
another date) is asked again. Going on writes one HandlingAcknowledgement per warning (`acknowledge`) and the
operation's activity-log entry is critical."""
import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from django.core.exceptions import ValidationError
from django.utils import formats
from django.utils.translation import gettext as _

from farm.feeding.read import book_on, last_fed_at
from farm.models import Batch, HandlingAcknowledgement, Treatment
from farm.models.handling import AcknowledgedWarning, HandlingKind, HandlingRule
from farm.stock.dates import start_of

from . import withdrawal
from .fasting import LOOKBACK_DAYS, rule_of, shown_moment

# The handlings a withdrawal matters for: the fish go to food, or are crowded and moved while held.
WITHDRAWAL_KINDS = (HandlingKind.HARVEST, HandlingKind.TRANSPORT, HandlingKind.GRADING)
HOUR = Decimal('0.1')


def _date(day):
    return formats.date_format(day, 'DATE_FORMAT')


def withdrawal_text(block, harvest=False):
    """The withdrawal as a sentence; before a harvest it starts "Not suitable for harvest" (owner's words)."""
    params = {'batch': block.batch.code, 'date': _date(block.until) if block.until else ''}
    if harvest:
        if block.until is None:
            return _('Not suitable for harvest — medicine withdrawal of %(batch)s, its end unknown.') % params
        if block.approximate:
            return _('Not suitable for harvest — medicine withdrawal of %(batch)s until about %(date)s.') % params
        return _('Not suitable for harvest — medicine withdrawal of %(batch)s until %(date)s.') % params
    if block.until is None:
        return _('Medicine withdrawal of %(batch)s, its end unknown.') % params
    if block.approximate:
        return _('Medicine withdrawal of %(batch)s until about %(date)s.') % params
    return _('Medicine withdrawal of %(batch)s until %(date)s.') % params


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

    @property
    def required_hours(self):
        return self.rule.min_fasting_hours if self.rule is not None else None

    def key(self):
        """What the person saw, as text: a change in it asks them again."""
        if self.warning == AcknowledgedWarning.WITHDRAWAL:
            block = self.block
            return f'withdrawal:{block.batch.pk}:{block.until}:{block.approximate}:{block.reason}'
        return f'fasting:{self.rule.pk}:{self.required_hours}:{self.last_fed_at.isoformat()}'

    def message(self):
        """The warning in the person's language (the activity log builds it in English)."""
        if self.warning == AcknowledgedWarning.WITHDRAWAL:
            text = withdrawal_text(self.block, harvest=self.kind == HandlingKind.HARVEST)
            return f'{text} {self.block.reason}' if self.block.reason else text
        return _('Last fed %(moment)s, %(hours)s h before %(day)s: the %(kind)s rule asks for %(required)d h.') % {
            'moment': shown_moment(self.last_fed_at, self.unit), 'hours': formats.number_format(self.fasted_hours, 1),
            'day': _date(self.day), 'kind': str(HandlingKind(self.kind).label).lower(),
            'required': self.required_hours}


@dataclass
class Assessment:
    """The check's result for a dialog: the warnings, and the plain lines it says besides (when the fish were
    last fed, the rule, a withdrawal not checked)."""
    kind: str
    unit: object
    day: date
    batch: object = None
    warnings: list = field(default_factory=list)
    notes: list = field(default_factory=list)

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
    """The production batches in the unit at the start of the day (at its end when it was empty then): the fish a
    harvest, a transport or a grading of the unit handles; the cleaner fish beside them are not slaughtered."""
    return list(Batch.all_objects.filter(pk__in=book_on(unit, day).production.weights).select_related('species'))


def assess(kind, unit, day, batch=None):
    """The warnings and notes of handling the fish of `batch` (or every batch) in `unit` on `day`."""
    result = Assessment(kind, unit, day, batch)
    batches = [batch] if batch is not None else _batches_in(unit, day)
    if kind in WITHDRAWAL_KINDS:
        _withdrawal(result, batches)
    _fasting(result, batches)
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
    rule = rule_of(result.kind, species)
    label = str(HandlingKind(result.kind).label).lower()
    if rule is None:
        result.notes.append(_('No handling rule for %(kind)s: the fast is not checked (Reference data › Handling '
                              'rules).') % {'kind': label})
    fed = last_fed_at(unit, day, batch=result.batch, since=day - timedelta(days=LOOKBACK_DAYS))
    if fed is None:
        result.notes.append(_('No feeding of these fish is recorded in the %(days)d days before %(day)s: the fast '
                              'is not checked.') % {'days': LOOKBACK_DAYS, 'day': _date(day)})
        return
    hours = max(Decimal((start_of(day, unit) - fed.moment).total_seconds()) / 3600, Decimal(0))
    hours = hours.quantize(HOUR, rounding=ROUND_DOWN)        # never rounded up: the fast is not overstated
    when = shown_moment(fed.moment, unit) if fed.timed else _('%(date)s, no time recorded: counted from the end of '
                                                              'the day') % {'date': _date(fed.record.date)}
    result.notes.append(_('Last fed %(when)s: %(hours)s h before %(day)s.') % {
        'when': when, 'hours': formats.number_format(hours, 1), 'day': _date(day)})
    if rule is None:
        return
    result.notes.append(_('The %(kind)s rule for %(species)s asks for %(hours)d h.') % {
        'kind': label, 'species': species.common_name, 'hours': rule.min_fasting_hours})
    if hours < rule.min_fasting_hours:
        result.warnings.append(HandlingWarning(AcknowledgedWarning.FASTING, result.kind, unit, day,
                                               last_fed_at=fed.moment, fasted_hours=hours, rule=rule))


def require_acknowledged(assessment, seen):
    """Refuses a save with warnings the person has not gone on past exactly as they are now (`seen`: the
    fingerprint the form's box carried); they are asked, or asked again. `assessment` has `warnings` and a
    `fingerprint` (an Assessment, or the treatment's over its units)."""
    if assessment.warnings and seen != assessment.fingerprint:
        if not seen:
            message = _('Tick the box to go on despite these warnings.')
        else:
            message = _('The warnings changed since the form was shown: read them again, and tick the box to go on.')
        raise ValidationError({'handling_ack': message})


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
                fasted_hours=warning.fasted_hours, required_hours=warning.required_hours, rule=warning.rule))
    HandlingAcknowledgement.objects.bulk_create(rows)
    return rows
