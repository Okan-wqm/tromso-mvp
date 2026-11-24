"""The one handling check: before fish are harvested, is a medicine withdrawal in force, and before fish are
harvested, transported, graded or treated, have they fasted long enough?

    check(kind, unit, day, batch=None) -> [HandlingWarning]      the warnings, for the save and the pages
    assess(kind, unit, day, batch=None) -> Assessment            the warnings and what the dialog says besides

`kind` is a HandlingKind: harvest, transport (a transfer), grading, treatment (the health tab's dialog).
The fish of a unit are one group (the batch named only says which fish an operation books). Pure reads of stored facts, inside the caller's
transaction: the stock service runs it after its locks (a feeding of the unit takes turns with it).

- Withdrawal (a harvest and a live delivery: the fish leave the farm and may be eaten, slaughtered at the facility
  the harvest names or sold alive (the owner's decision 12 of 19.11.2026: a live delivery of held fish is warned,
  ticked, kept and logged exactly as a harvest is, never blocked; `WITHDRAWAL_OPERATIONS`). A medicine withdrawal is
  a meat withdrawal, so it means nothing when live fish are moved or graded on the farm, and a treatment during a
  withdrawal harms nobody): every block the registry gives (farm/handling/withdrawal.py) for the UNIT whose
  `until` is after the day, or unknown. **The withdrawal is the unit's, never the chosen batch's** (flow fault S-02;
  the owner, 14.11.2026: fish of two batches in one unit are one group): a net cannot separate the batches of a unit,
  so the withdrawal of any fish in it holds a harvest of it, whichever batch the dialog names; `in_force` takes no
  batch, so no caller can ask it of one. The warning names the batch that is held, and says so when the unit holds
  other fish beside it. With no provider the harvest dialog says "Medicine withdrawal not checked" and nothing is
  warned. A transfer or a grading is checked for the fast and the live-transfer facts alone.
  **Cleaner fish beside the production fish are kept apart** (`held_apart`, review F-05): the owner's decision is about
  two groups of production fish; cleaner fish are another species, sorted out at a harvest and never harvested
  themselves (they are culled). Whether their withdrawal holds the salmon beside them is the owner's and the vet's to
  decide; until then it is no warning on the production fish's harvest and no acknowledgement of theirs, it does not
  decide their earliest date, and a harvest of theirs is not "inside" it: the dialog says it as a note ("Cleaner
  fish in C-01 are in a medicine withdrawal (…): keep them out of the harvest."; a live delivery's dialog in its own
  words, "… (B-2026-006, the fish may leave the farm from …): keep them out of the live delivery."), and the unit's own
  line (`in_force_of`) still shows it.
- Fasting: **the fast is of the fish in the unit handled** (flow fault S-01; the owner, 14.11.2026: fish of two
  batches in one unit are one group): one fast for the unit, whichever batch the handling names, from the latest
  feeding of the fish in it along their own path (farm.feeding.read.last_fed_of: this unit since they came in, the
  unit they came from up to the day of the move, and so on back; never a sibling unit fed after a split). The hours
  since that feeding against the rule (farm/handling/fasting.py) and, for a harvest
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

from farm.feeding.read import handled, handled_of, last_fed_at, last_fed_of
from farm.models import Batch, HandlingAcknowledgement, Treatment
from farm.models.handling import AcknowledgedWarning, HandlingKind, HandlingRule, WithdrawalWarning
from farm.models.stock import MovementKind, OperationKind
from farm.stock.dates import local_today
from farm.stock.read import Presence
from farm.water.degree_days import BatchWater, degree_days_text, missing_sentence

from . import fasting, withdrawal
from .fasting import DAY, LOOKBACK_DAYS, asks_text, both_text, hours_text, shown_moment

# The handling a medicine withdrawal matters for: the fish go to food (a harvest names the slaughter facility).
# Live fish that are moved or graded on the farm are not eaten: their medicine is no concern of the handling check.
WITHDRAWAL_KIND = HandlingKind.HARVEST
# The stock operations whose fish leave the farm and may be eaten, so the withdrawal is asked of them: a harvest, and a
# live delivery (fish sold alive; the owner's decision 12 of 19.11.2026). A delivery's fast is a transport's
# (KIND_OF_OPERATION); its withdrawal is a harvest's, through the same check, box, rows and critical log line.
# The line of each such operation that takes its fish out (a harvest's other line, a count adjustment, is fish the book
# held beyond the count: lost, not gone to food). What a later write compares with a withdrawal (the owner's decision
# 13 of 19.11.2026: a live delivery is a harvest also after the fact; farm.health.withdrawal._inside).
WITHDRAWAL_LINES = {OperationKind.HARVEST: MovementKind.HARVEST, OperationKind.DELIVERY: MovementKind.DELIVERY}
WITHDRAWAL_OPERATIONS = frozenset(WITHDRAWAL_LINES)


def asks_withdrawal(kind, operation=None):
    """Whether a handling of `kind` is asked about a medicine withdrawal: of the stock operation `operation` when it is
    known (a harvest, a live delivery: `WITHDRAWAL_OPERATIONS`), else of the handling kind (a harvest)."""
    return operation in WITHDRAWAL_OPERATIONS if operation is not None else kind == WITHDRAWAL_KIND


def _date(day):
    return formats.date_format(day, 'DATE_FORMAT')


def end_text(until, approximate, kind=WITHDRAWAL_KIND):
    """A withdrawal's end in the words of the handling it is asked of: a harvest's in the one wording of every page
    (withdrawal.harvest_from: "harvest from 25.11.2026"), a live delivery's (any other handling the withdrawal is asked
    of, `WITHDRAWAL_OPERATIONS`) in its own (withdrawal.leave_from: "the fish may leave the farm from 25.11.2026";
    review of S-03 at 6776780, F-1)."""
    words = withdrawal.harvest_from if kind == WITHDRAWAL_KIND else withdrawal.leave_from
    return words(until, approximate)


def withdrawal_text(block, kind=WITHDRAWAL_KIND):
    """The withdrawal as a sentence, starting "Not suitable for harvest" (owner's words) for a harvest, and "Not
    suitable for a live delivery" for the other handling it is asked of (`WITHDRAWAL_OPERATIONS`: fish sold alive),
    each with its end in its own words (`end_text`): "… medicine withdrawal of B-2026-001: harvest from 25.11.2026.";
    "… of B-2026-001: the fish may leave the farm from 25.11.2026. Fish sold alive may be eaten."."""
    params = {'batch': block.batch.code, 'end': end_text(block.until, block.approximate, kind)}
    if kind != WITHDRAWAL_KIND:
        return _('Not suitable for a live delivery — medicine withdrawal of %(batch)s: %(end)s. Fish sold alive may '
                 'be eaten.') % params
    return _('Not suitable for harvest — medicine withdrawal of %(batch)s: %(end)s.') % params


def fed_when(fed, unit):
    """When and where fish were last fed (a LastFed), as it is true: the feeding's moment on the clock of the unit it
    was given in, when it has a time; else its day, and that no time was recorded. A feeding without a time COUNTS
    from the end of its day (farm.feeding.read.fed_moment), but that is not a moment anybody fed at, so it is never
    printed as one (flow fault M-05: "Last fed 22.10.2026 00:00" for a feeding of 21.10). The unit of the feeding is
    named (S-01: the fish may have been fed in the unit they came from), and when that unit is on another clock than
    `unit`, the one handled, the moment is said on both: nobody fed at the converted time."""
    there = fed.record.unit
    if fed.timed:
        when = shown_moment(fed.moment, there)
    else:
        when = _('%(date)s (no time recorded: counted from the end of the day)') % {'date': _date(fed.record.date)}
    when = _('%(when)s in %(unit)s') % {'when': when, 'unit': there.code}
    here = shown_moment(fed.moment, unit)
    if fed.timed and there.pk != unit.pk and here != shown_moment(fed.moment, there):
        when = _('%(when)s (%(here)s on the clock of %(unit)s)') % {'when': when, 'here': here, 'unit': unit.code}
    return when


def fed_at(fed, unit):
    """The time of a feeding given on the handling's own day, as recorded: 09:00, or that none was; and the unit it was
    given in when that is not `unit`, the one handled (the fish came out of it that day, RULES case 5: "09:00 in
    T-01"), as `fed_when` names it for a feeding of a day before."""
    at = formats.time_format(fed.record.time, 'TIME_FORMAT') if fed.timed else _('no time recorded')
    if fed.record.unit_id != unit.pk:
        at = _('%(when)s in %(unit)s') % {'when': at, 'unit': fed.record.unit.code}
    return at


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
    shared: bool = False                 # a withdrawal: the unit holds fish of other batches beside the held one
    fed: object = None                   # a fast: the feeding it counts from (farm.feeding.read.LastFed), for the words

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
            shared = ':shared' if self.shared else ''
            return f'withdrawal:{block.batch.pk}:{block.until}:{block.approximate}:{block.reason}{shared}'
        return (f'fasting:{self.rule.pk}:{self.required_hours}:{self.required_degree_days}:{self.fasted_degree_days}:'
                f'{self.last_fed_at.isoformat()}')

    def message(self):
        """The warning in the person's language (the activity log builds it in English)."""
        if self.warning == AcknowledgedWarning.WITHDRAWAL:
            text = withdrawal_text(self.block, self.kind)
            if self.shared and self.kind != WITHDRAWAL_KIND:          # a live delivery: no harvest to speak of
                text += ' ' + _('It holds every fish in %(unit)s: the fish of different batches in one unit cannot be '
                                'told apart when they are caught.') % {'unit': self.unit.code}
            elif self.shared:
                text += ' ' + _('It holds every fish in %(unit)s: the fish of different batches in one unit cannot be '
                                'told apart at a harvest.') % {'unit': self.unit.code}
            return f'{text} {self.block.reason}' if self.block.reason else text
        params = {'day': _date(self.day), 'kind': str(HandlingKind(self.kind).label).lower(),
                  'asked': asks_text(self.required_hours, self.required_degree_days)}
        if self.fed is not None and self.fed.record.date >= self.day:
            # Fed on the handling's own day: the handling has no time, so no fast is counted, and the sentence does not
            # say "0.0 h before" a day the feeding is on, nor name a moment after it (M-05).
            text = _('Fed on the day of the handling itself (%(at)s): no fast before %(day)s; the %(kind)s rule asks '
                     'for %(asked)s.') % {**params, 'at': fed_at(self.fed, self.unit)}
        else:
            text = _('Last fed %(moment)s, %(fasted)s before %(day)s: the %(kind)s rule asks for %(asked)s.') % {
                **params,
                'moment': (fed_when(self.fed, self.unit) if self.fed is not None
                           else shown_moment(self.last_fed_at, self.unit)),
                'fasted': both_text(
                    None if self.required_hours is None else hours_text(self.fasted_hours),
                    None if self.required_degree_days is None else degree_days_text(self.fasted_degree_days))}
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

    @property
    def second_person(self):
        """Why these warnings cannot be gone past by a tick, or '': a second person must approve (M-27)."""
        return second_person_text() if needs_second_person(self) else ''


def _batches_in(unit, day):
    """The production batches in the unit at the start of the day or at its end (farm.feeding.read.handled): the fish
    a harvest, a transport or a grading of the unit handles, as one group; the cleaner fish beside them are not
    slaughtered."""
    return list(Batch.all_objects.filter(pk__in=handled(unit, day)).select_related('species').order_by('code'))


def assess(kind, unit, day, batch=None, with_earliest=True, operation=None):
    """The warnings and notes of handling the fish of `batch` (or every batch) in `unit` on `day`; for a harvest and a
    live delivery, with the earliest suitable date among the notes (`with_earliest`: the save, which needs only the
    warnings, leaves it). `operation`: the stock operation the handling is, when known (a live delivery is a transport
    whose withdrawal is asked: `asks_withdrawal`)."""
    result = Assessment(kind, unit, day, batch)
    # The fish of the unit are one group (S-01, S-02): the fast and the withdrawal are the unit's, whichever batch the
    # handling names; `batch` only says which fish the operation books.
    batches = _batches_in(unit, day)
    asked = asks_withdrawal(kind, operation)
    if asked:
        _withdrawal(result)
    _fasting(result, batches)
    if asked and with_earliest:
        _earliest(result, batches)
    return result


def check(kind, unit, day, batch=None):
    """The warnings of handling the fish of `batch` (or every batch) in `unit` on `day` (assess)."""
    return assess(kind, unit, day, batch).warnings


def in_force_of(units, day=None):
    """{unit id: [block]} of every unit given: the withdrawal blocks in force for its fish on `day` (None: the unit's
    own today), those whose `until` is after the day, or unknown. None when no provider is registered: not checked."""
    found = withdrawal.blocks_of(units, day)
    if found is None:
        return None
    days = {unit.pk: day or local_today(unit) for unit in units}
    return {unit_id: [block for block in blocks if block.until is None or block.until > days[unit_id]]
            for unit_id, blocks in found.items()}


def in_force_now(units):
    """{unit id: [block]} of the units with a medicine withdrawal in force today, the units without one left out; empty
    when no provider is registered. The one read of it for the pages and the readers (the production units' row badge,
    the monitoring cards); it lived in a views module (the data-layering audit, L-10)."""
    found = in_force_of(units)
    return {unit_id: blocks for unit_id, blocks in (found or {}).items() if blocks}


def held_apart(batch, named=None):
    """Whether a withdrawal of `batch` is kept apart from a harvest of the production fish beside it: its fish are
    cleaner fish (and it is not the batch the handling itself names). THE one place that says it (review F-05; the
    module's docstring), for the check, the earliest date, the plan rows and the harvests inside a withdrawal."""
    return batch.species.is_cleaner_fish and (named is None or batch.pk != named.pk)


def _apart(blocks, named=None):
    """(the blocks that hold a harvest, those of cleaner fish beside the production fish: `held_apart`)."""
    holding, beside = [], []
    for block in blocks:
        (beside if held_apart(block.batch, named) else holding).append(block)
    return holding, beside


def _in_force(unit, day, named=None):
    """(the blocks in force that hold a harvest of `unit` on `day`, those of cleaner fish beside the production fish:
    `held_apart`); None when no provider is registered."""
    found = in_force_of([unit], day)
    return None if found is None else _apart(found[unit.pk], named)


def in_force(unit, day):
    """The withdrawal blocks in force that hold a harvest of the fish in `unit` on `day`: of EVERY production batch
    with fish in it (the registry says which; cleaner fish beside them are kept apart, `held_apart`): their `until` is
    after the day, or unknown. None when no provider is registered: not checked.
    It takes no batch on purpose (S-02): the fish of a unit are handled together, so a withdrawal is never asked of
    one of its batches alone."""
    found = holding_of([unit], day)
    return None if found is None else found[unit.pk]


def holding_of(units, day=None):
    """{unit id: `in_force` of the unit} of every unit given, in one read of the registry (`in_force_of`: one reader
    per site's day, the same number of queries for fifty units as for one); `day` None: each unit's own today. None
    when no provider is registered: not checked."""
    found = in_force_of(units, day)
    return None if found is None else {unit_id: _apart(blocks)[0] for unit_id, blocks in found.items()}


def cleaner_text(unit, block, kind=WITHDRAWAL_KIND):
    """The note of a harvest dialog about cleaner fish under a withdrawal beside the fish harvested; of a live delivery's
    dialog (any other handling the withdrawal is asked of) in a delivery's words, its end as `end_text` says it (the
    verification of the S-03 follow-up, can-follow 2: the delivery dialog spoke of a harvest)."""
    params = {'unit': unit.code, 'batch': block.batch.code, 'end': end_text(block.until, block.approximate, kind)}
    if kind != WITHDRAWAL_KIND:
        return _('Cleaner fish in %(unit)s are in a medicine withdrawal (%(batch)s, %(end)s): keep them out of the '
                 'live delivery.') % params
    return _('Cleaner fish in %(unit)s are in a medicine withdrawal (%(batch)s, %(end)s): keep them out of the '
             'harvest.') % params


def _withdrawal(result):
    """The withdrawal warnings of a handling of the unit: one per block in force for any production fish in it,
    whichever batch the handling names. A block is `shared` when the unit holds fish of another batch that day too (the
    stock's presence, as the registry's provider reads it), which the warning then says. A block of cleaner fish beside
    them is a note, not a warning (`held_apart`)."""
    unit, day = result.unit, result.day
    found = _in_force(unit, day, result.batch)
    if found is None:
        result.notes.append(_('Medicine withdrawal not checked: the health records are not in yet.'))
        return
    blocks, beside = found
    present = Presence.of_units([unit.pk]).batches_during(unit.pk, day) if blocks else set()
    for block in blocks:
        result.warnings.append(HandlingWarning(AcknowledgedWarning.WITHDRAWAL, result.kind, unit, day, block=block,
                                               shared=bool(present - {block.batch.pk})))
    # One note per cleaner-fish batch, with its latest end (review V-03: a batch held by two causes gave two notes
    # with different ends); an unknown end is the latest of all.
    latest = {}
    for block in beside:
        known = latest.get(block.batch.pk)
        if known is None or (known.until is not None and (block.until is None or block.until > known.until)):
            latest[block.batch.pk] = block
    result.notes.extend(cleaner_text(unit, block, result.kind) for block in latest.values())
    if not blocks and not beside:
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
    fed = last_fed_at(unit, day, since=day - timedelta(days=LOOKBACK_DAYS))
    if fed is None:
        result.notes.append(_('No feeding of these fish is recorded in the %(days)d days before %(day)s: the fast '
                              'is not checked.') % {'days': LOOKBACK_DAYS, 'day': _date(day)})
        return
    batch_ids = [each.pk for each in batches]
    water = None
    if requirement is not None and requirement.degree_days is not None:
        water = BatchWater(batch_ids, local_today(unit), fed.record.date + DAY)
    done = fasting.fasted(unit, day, fed, requirement, water, batch_ids)
    if requirement is not None and not done.ok:
        # ONE line (flow fault M-05): the warning says when the fish were fed, how long before the day and what the
        # rule asks; the notes do not say the same feeding a second time. What is stored is unchanged: the moment the
        # feeding counts from (`last_fed_at`) and the hours.
        result.warnings.append(HandlingWarning(
            AcknowledgedWarning.FASTING, result.kind, unit, day, last_fed_at=fed.moment, fasted_hours=done.hours,
            rule=requirement.rule, fasted_degree_days=done.degree_days, accrual=done.accrual, fed=fed))
        return
    if fed.record.date >= day:
        result.notes.append(_('Fed on the day of the handling itself (%(at)s).') % {'at': fed_at(fed, unit)})
    else:
        result.notes.append(_('Last fed %(when)s: %(fasted)s before %(day)s.') % {
            'when': fed_when(fed, unit), 'fasted': done.text(requirement), 'day': _date(day)})
    if requirement is None:
        return
    result.notes.append(_('The %(kind)s rule for %(species)s asks for %(asked)s.') % {
        'kind': label, 'species': species.common_name, 'asked': requirement.text()})
    if done.accrual is not None and done.accrual.missing:
        result.notes.append(missing_sentence(done.accrual.missing, done.accrual.assumed))


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
    kind: str = WITHDRAWAL_KIND           # the handling it is of: a harvest, or a transport (a live delivery)

    def holds(self, day):
        """Whether a harvest (a live delivery) on `day` is earlier than the earliest suitable one."""
        return bool(self.decides) and (self.day is None or day < self.day)

    def text(self):
        """Earliest suitable harvest date: 17.11.2026. Medicine withdrawal decides: harvest from 17.11.2026.
        A live delivery's in its own words (review of S-03 at 6776780, F-1): Earliest suitable live delivery date:
        17.11.2026. Medicine withdrawal decides: the fish may leave the farm from 17.11.2026; and the fast of a
        transport where a harvest has its purge."""
        if not self.decides:
            return ''
        harvest = self.kind == WITHDRAWAL_KIND
        if self.day is None:
            text = (_('Earliest suitable harvest date: not known.') if harvest
                    else _('Earliest suitable live delivery date: not known.'))
        elif harvest:
            text = _('Earliest suitable harvest date: %(date)s.') % {'date': _date(self.day)}
        else:
            text = _('Earliest suitable live delivery date: %(date)s.') % {'date': _date(self.day)}
        if self.decides == WITHDRAWAL:
            text += ' ' + _('Medicine withdrawal decides: %(end)s.') % {
                'end': end_text(None if self.unknown else self.until, self.approximate, self.kind)}
        elif self.stop_by is not None:
            text += ' ' + (_('Purging decides: feeding must stop by %(date)s.') if harvest
                           else _('The fast decides: feeding must stop by %(date)s.')) % {'date': _date(self.stop_by)}
        else:
            text += ' ' + (_('Purging decides.') if harvest else _('The fast decides.'))
        if self.degrees_unknown:
            text += ' ' + _('Degree-days unknown: no temperature.')
        return text


def earliest(unit, batch, today=None, kind=WITHDRAWAL_KIND):
    """The Earliest suitable harvest date of `batch` in `unit` on the farm's `today`: the end of the medicine withdrawal
    of the fish in the unit (`in_force`: the registry's blocks of every production batch in it, S-02; unknown when a
    block's end is) and the
    first day its purge can be complete if it is not
    fed again, which is `fasted` asked of each day from today on, from the last feeding. Nothing holds the fish when
    there is no withdrawal in force, no rule, no feeding recorded in the 31 days before, or the fast is complete.
    `kind`: the handling it is asked for, a harvest (its purge), or a transport for a live delivery (the transport's
    fast, the rule a delivery's fast is checked by: KIND_OF_OPERATION), so a delivery's dialog says the earliest
    suitable date as a harvest's does (review of S-03 at 6776780, F-1)."""
    return earliest_of([(unit, batch)], today, kind)[(unit.pk, batch.pk)]


NOT_READ = object()         # `earliest_of(holding=...)` not given: it reads the withdrawals itself


def earliest_of(pairs, today=None, kind=WITHDRAWAL_KIND, holding=NOT_READ):
    """{(unit id, batch id): Earliest} of every (unit, batch) pair given: `earliest` of each, with what it reads read
    once for all of them (a page of fifty rows costs about what one row does): the withdrawals in force (`holding_of`,
    or `holding`, its answer on the same `today`, from a caller that has it already: it must hold every unit of the
    pairs, a unit missing from it is an error, never a unit without a withdrawal; None, no provider, holds nothing as
    `earliest` alone), the rule of each species, the last feedings of the units (`last_fed_of`) and the water of the
    batches (`BatchWater.of_each`: each batch's water is the one it has read alone)."""
    pairs = list({(unit.pk, batch.pk): (unit, batch) for unit, batch in pairs}.values())
    units = list({unit.pk: unit for unit, _batch in pairs}.values())
    days = {unit.pk: local_today(unit) if today is None else today for unit in units}
    if holding is NOT_READ:
        holding = holding_of(units, today)
    if holding is None:                         # no provider registered: not checked, nothing holds (`in_force`)
        holding = {unit.pk: [] for unit in units}
    requirements = {}
    for _unit, batch in pairs:
        if batch.species_id not in requirements:
            requirements[batch.species_id] = fasting.requirement_of(kind, batch.species)

    def asks(batch):
        requirement = requirements[batch.species_id]
        return requirement is not None and requirement.asks

    asking = list({unit.pk: unit for unit, batch in pairs if asks(batch)}.values())
    handled_ids = handled_of([(unit, days[unit.pk]) for unit in asking])
    # The unit's last feeding, not the batch's (S-01).
    fed = last_fed_of([(unit, days[unit.pk], handled_ids[(unit.pk, days[unit.pk])],
                        days[unit.pk] - timedelta(days=LOOKBACK_DAYS)) for unit in asking])
    # The water `earliest` reads for a purge in degree-days: the batch's, from the day after the unit's last feeding.
    watered = {(unit.pk, batch.pk): (batch.pk, days[unit.pk], fed[unit.pk].record.date + DAY)
               for unit, batch in pairs
               if asks(batch) and fed.get(unit.pk) is not None and requirements[batch.species_id].degree_days}
    waters = BatchWater.of_each(watered.values())
    return {(unit.pk, batch.pk): _earliest_from(
        unit, batch, days[unit.pk], kind, holding[unit.pk], requirements[batch.species_id],
        fed.get(unit.pk), waters[watered[(unit.pk, batch.pk)]] if (unit.pk, batch.pk) in watered else None)
        for unit, batch in pairs}


def _earliest_from(unit, batch, today, kind, blocks, requirement, fed, water):
    """`earliest` of one pair from what `earliest_of` read: the blocks in force that hold the unit's fish, the rule,
    the unit's last feeding in the LOOKBACK_DAYS before `today` (None: none, or not read because the rule asks
    nothing) and the batches' water (when the rule asks for degree-days)."""
    dated = [block for block in blocks if block.until is not None]
    unknown = len(dated) < len(blocks)
    latest = max(dated, key=lambda block: block.until, default=None)
    purge_day, degrees_unknown = None, False
    if requirement is not None and requirement.asks:
        if fed is not None:
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
                        degrees_unknown=degrees_unknown, kind=kind)
    if latest is not None and (purge_day is None or latest.until >= purge_day):
        return Earliest(batch, latest.until, WITHDRAWAL, latest.until, latest.approximate,
                        degrees_unknown=degrees_unknown, kind=kind)
    if purge_day is not None:
        start = fasting.start_of_fast(unit, purge_day, requirement, water, batch.pk)
        stop_by = start.starts_at.date() - DAY if start.starts_at is not None else None
        return Earliest(batch, purge_day, PURGING, latest.until if latest else None,
                        latest.approximate if latest else False, stop_by=stop_by, degrees_unknown=degrees_unknown,
                        kind=kind)
    if degrees_unknown:                         # the purge cannot be worked out: not known, and said
        return Earliest(batch, None, PURGING, degrees_unknown=True, kind=kind)
    return Earliest(batch, today, '', kind=kind)


def _earliest(result, batches):
    """A harvest's (a live delivery's) earliest suitable date among the notes: of its batches, the latest."""
    found = earliest_of([(result.unit, batch) for batch in batches], kind=result.kind).values()
    held = [each for each in found if each.decides]
    if not held:
        return
    result.earliest = max(held, key=lambda each: (each.day is None, each.day or date.min))
    result.notes.append(result.earliest.text())


def require_acknowledged(assessment, seen, field='handling_ack', user=None, refused=None):
    """Refuses a save with warnings the person has not gone on past exactly as they are now (`seen`: the
    fingerprint the form's box carried); they are asked, or asked again. `assessment` has `warnings` and a
    `fingerprint` (an Assessment, or the treatment's over its units, or an experiment's start). The error is
    reported on `field`, the name of the form's box. `user` is the person going
    on (for the second-person hook); `refused(errors)` makes the error raised (a ValidationError by default; the withdrawal
    guard raises its WithdrawalChanged, which carries what it found)."""
    refused = refused or ValidationError
    # The setting first (flow fault M-27): where a second person must approve, a tick cannot go on, so the person is
    # told that before they are asked to tick, not after; the dialog shows the same sentence in the place of its box
    # (`needs_second_person`).
    if needs_second_person(assessment, user):
        raise refused({field: second_person_text()})
    if assessment.warnings and seen != assessment.fingerprint:
        if not seen:
            message = _('Tick the box to go on despite these warnings.')
        else:
            message = _('The warnings changed since the form was shown: read them again, and tick the box to go on.')
        raise refused({field: message})


def second_person_text():
    return _('A second person must approve going on past a medicine withdrawal (the platform owner’s setting), and '
             'that approval cannot be given here yet.')


def needs_second_person(assessment, user=None):
    """Whether going on past these warnings waits for a second person: a withdrawal warning is among them and the
    platform owner asks for the second approval (`second_person_must_approve`, the one place the setting is read). The
    save refuses then whatever is ticked, and a dialog says so where its box would be."""
    kinds = sorted({str(getattr(warning, 'warning', '')) for warning in assessment.warnings}
                   & {str(kind) for kind in WITHDRAWAL_WARNINGS})
    return bool(kinds) and bool(second_person_must_approve(user, kinds, assessment))


# The warnings about fish that may go, or have gone, to food medicated: a withdrawal in force before a harvest or a live
# delivery, and the withdrawal guard's (farm.health.withdrawal.guarded) harvest or live delivery inside a withdrawal and
# fish freed from one.
WITHDRAWAL_WARNINGS = (AcknowledgedWarning.WITHDRAWAL, WithdrawalWarning.HARVESTED, WithdrawalWarning.DELIVERED,
                       WithdrawalWarning.RELEASED)


def second_person_must_approve(user, kinds, record):
    """THE hook of the platform owner's setting "a second person approves a withdrawal acknowledgement" (owner answer
    2026-11-06, audit F-164): `user` is the person about to go on, `kinds` the withdrawal warnings (WITHDRAWAL_WARNINGS)
    they go on past, `record` what they acknowledge (the assessment or the withdrawal change: its warnings, messages and
    fingerprint), so the approval flow can name both people and what was approved.
    It is the one place that setting is consulted (require_acknowledged, every dialog's save): the platform owner's
    setting (core.platform.second_approval_required). The second person's approval flow does not exist yet, so the
    setting FAILS CLOSED (cross review F4): ticked, going on past a withdrawal is refused, saying a second person must
    approve and that the approval cannot be given here yet; nobody goes on alone. Unticked (the default), one person's
    acknowledgement goes on, stored and logged as critical."""
    from core import platform
    return platform.second_approval_required('withdrawal')


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
                withdrawal_approximate=block.approximate, withdrawal_reason=block.reason[:500], batch=block.batch,
                withdrawal_source=withdrawal.source_key(block.source)))
        else:
            rows.append(HandlingAcknowledgement(
                **link, warning=warning.warning, last_fed_at=warning.last_fed_at,
                feeding=warning.fed.record if warning.fed is not None else None,
                fasted_hours=warning.fasted_hours, required_hours=warning.required_hours,
                fasted_degree_days=warning.fasted_degree_days, required_degree_days=warning.required_degree_days,
                rule=warning.rule))
    HandlingAcknowledgement.objects.bulk_create(rows)
    return rows
