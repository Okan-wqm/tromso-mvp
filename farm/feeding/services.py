"""The one write path of the feeding records (feeding-records §4.3). Recording and voiding a feeding go
through here, each in one transaction, with the stock's own rules where they are the same: the unit is
locked as the stock service locks it (so a feeding and a harvest of one unit take turns), the farm's
dates (farm/stock/dates.py), the form's token, and one void for every daily record
(farm.stock.services.voided).

A failure raises ValidationError (a dict of field to message: 'unit', 'date', 'feed', 'feeder', 'target',
'amount_kg', 'meals', 'high_rate_ack', 'reason' or NON_FIELD_ERRORS) and nothing is written."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils.translation import gettext as _, gettext_lazy

from core import access, audit
from core.models import EntryKey
from farm.health import withdrawal
from farm.models import Feed, FeedingRecord
from farm.models.feeding import FeedTarget
from farm.stock.dates import check_date, local_today, shown_date, sites_of
from farm.stock.services import AlreadyRecorded, lock_fish, voided
from farm.templatetags.feeding import amount
from farm.templatetags.stock import number

from . import read

# The fields the activity log shows for a feeding.
LOGGED = ['unit', 'date', 'time', 'feed', 'target', 'amount_kg', 'meals', 'feeder', 'notes']


def label(record):
    """How the activity log names a feeding: what, where, when, how much and which feed, so a search
    for the unit's or the feed's code finds it. In English, like every log row, whoever records it."""
    return (f'{audit.english(gettext_lazy("Feeding"))} · {record.unit.code} · {record.date.isoformat()} · '
            f'{record.amount_kg.normalize():f} kg · {record.feed.code}')


# Who may record a feeding and void one (farm/feeding/views.py asks the same); asked here too (the data-layering audit, L-6).
RECORD, VOID = 'farm.add_feedingrecord', 'farm.delete_feedingrecord'


def record_feeding(user, *, unit, day, feed, amount_kg, time=None, meals=None, feeder=None, notes='', ack=False,
                   target=FeedTarget.PRODUCTION, token=None, withdrawal_ack=None):
    """Feed given to `unit` on `day`, for its production fish or for the cleaner fish beside them (`target`, D-1).
    It needs fish of its target in the unit at the start or the end of that day (the stock ledger), a feed that is
    active, and, above FEEDING_ACK_PERCENT of their book biomass, the person's acknowledgement (stored on the record;
    owner decision Q-F5): a kilo typed for a gram is caught here, a hatchery's fry may well be fed more."""
    access.require(user, RECORD)
    with transaction.atomic():
        unit, batch_ids = _lock_fish(unit, day)
        if token is not None:
            done = EntryKey.record_of(token, FeedingRecord)
            if done is not None:
                raise AlreadyRecorded(done)
        if unit.is_deleted:
            raise ValidationError({'unit': _('%(unit)s is deleted.') % {'unit': unit.code}})
        check_date(day, [unit])
        feed = Feed.all_objects.get(pk=feed.pk)
        if feed.is_deleted or feed.status != Feed.Status.ACTIVE:
            raise ValidationError({'feed': _('%(feed)s is %(status)s: a new feeding takes an active feed.') % {
                'feed': feed, 'status': _('deleted') if feed.is_deleted else str(feed.get_status_display()).lower()}})
        book = read.book_on(unit, day).of(target)
        if not book.has_fish:
            text = (_('%(unit)s holds no cleaner fish on %(date)s.') if target == FeedTarget.CLEANER_FISH
                    else _('%(unit)s holds no fish on %(date)s.'))
            raise ValidationError({'target' if read.book_on(unit, day).has_fish else 'date': text % {
                'unit': unit.code, 'date': shown_date(day)}})
        record = FeedingRecord(unit=unit, date=day, time=time, feed=feed, target=target, amount_kg=amount_kg,
                               meals=meals, feeder=feeder, notes=notes, created_by=user, updated_by=user)
        record.full_clean()
        # Q-F5 asks about more than the limit a day: the day's feedings of the target in the unit, this one included (the
        # unit is locked, so two feedings of one day take turns; audit F-081).
        day_kg = amount_kg + (FeedingRecord.objects.filter(unit=unit, date=day, target=target)
                              .aggregate(total=Sum('amount_kg'))['total'] or 0)
        rate = 100 * day_kg / book.biomass_kg
        if rate > settings.FEEDING_ACK_PERCENT:
            if not ack:
                raise ValidationError({'high_rate_ack': _(
                    '%(kilos)s kg fed on %(date)s, this feeding included, is %(rate)s %% of the %(biomass)s kg %(unit)s '
                    'holds in the book; more than %(limit)s %% a day is unusual. Tick the box below to record it '
                    'anyway.') % {
                    'kilos': amount(day_kg), 'rate': number(rate, 1),
                    'biomass': number(book.biomass_kg, 1), 'unit': unit.code, 'date': shown_date(day),
                    'limit': settings.FEEDING_ACK_PERCENT}})
            record.high_rate_ack = True

        def write():
            saved = FeedingRecord(unit=unit, date=day, time=time, feed=feed, target=target, amount_kg=amount_kg,
                                  meals=meals, feeder=feeder, notes=notes, created_by=user, updated_by=user,
                                  high_rate_ack=record.high_rate_ack)
            saved.save()
            if token is not None:
                EntryKey.note(token, saved)
            with audit.source_language():
                names = [*LOGGED, *(['high_rate_ack'] if saved.high_rate_ack else [])]
                audit.record_create(user, saved, audit.snapshot(saved, names), label=label(saved))
            return saved

        # A medicated feeding no in-feed treatment covers holds the fish (withdrawal rule 6): through the guard.
        return withdrawal.guarded(user, batch_ids, local_today(unit), write, seen=withdrawal_ack)


def void_feeding(user, record, reason, withdrawal_ack=None):
    """The undo, as for a stock operation: the record stops counting, with its reason, within the
    backdating window. It moves no fish; a medicated feeding's void can free fish its withdrawal holds, so it goes
    through the withdrawal guard."""
    access.require(user, VOID)
    with transaction.atomic():
        found = FeedingRecord.all_objects.select_related('unit').get(pk=record.pk)
        _unit, batch_ids = _lock_fish(found.unit, found.date)

        def write():
            current = (FeedingRecord.all_objects.select_for_update(of=('self',))
                       .select_related('unit__production_department__site', 'feed').get(pk=record.pk))
            voided(user, current, reason, sites_of([current.unit]), label(current))
            return current

        return withdrawal.guarded(user, batch_ids, local_today(found.unit), write, seen=withdrawal_ack)


def _lock_fish(unit, day):
    """Locks the batches with fish in the unit on the feeding's day, then the unit, as a stock operation locks them
    (batches, then units), so a feeding and a harvest of the same fish take turns; returns (the unit, the batch ids):
    the fish a medicated feeding holds, which the withdrawal guard works the withdrawals of."""
    units, batch_ids = lock_fish([unit.pk], day)
    return units[unit.pk], batch_ids
