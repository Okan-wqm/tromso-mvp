"""The one write path of the feeding records (feeding-records §4.3). Recording and voiding a feeding go
through here, each in one transaction, with the stock's own rules where they are the same: the unit is
locked as the stock service locks it (so a feeding and a harvest of one unit take turns), the farm's
dates (farm/stock/dates.py), the form's token, and one void for every daily record
(farm.stock.services.voided).

A failure raises ValidationError (a dict of field to message: 'unit', 'date', 'feed', 'feeder',
'amount_kg', 'meals', 'high_rate_ack', 'reason' or NON_FIELD_ERRORS) and nothing is written."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _, gettext_lazy

from core import audit
from farm.models import Feed, FeedingRecord, Tank
from farm.stock.dates import check_date, shown_date
from farm.stock.services import AlreadyRecorded, locked, voided
from farm.templatetags.feeding import amount
from farm.templatetags.stock import number

from . import read

# The fields the activity log shows for a feeding.
LOGGED = ['unit', 'date', 'time', 'feed', 'amount_kg', 'meals', 'feeder', 'notes']


def label(record):
    """How the activity log names a feeding: what, where, when, how much and which feed, so a search
    for the unit's or the feed's code finds it. In English, like every log row, whoever records it."""
    return (f'{audit.english(gettext_lazy("Feeding"))} · {record.unit.code} · {record.date.isoformat()} · '
            f'{record.amount_kg.normalize():f} kg · {record.feed.code}')


def record_feeding(user, *, unit, day, feed, amount_kg, time=None, meals=None, feeder=None, notes='', ack=False,
                   token=None):
    """Feed given to `unit` on `day`. It needs fish in the unit at the start or the end of that day (the
    stock ledger), a feed that is active, and, above FEEDING_ACK_PERCENT of the unit's book biomass, the
    person's acknowledgement (stored on the record; owner decision Q-F5): a kilo typed for a gram is caught
    here, a hatchery's fry may well be fed more."""
    with transaction.atomic():
        unit = locked(Tank, {unit.pk})[unit.pk]
        if token is not None:
            done = FeedingRecord.all_objects.filter(entry_key=token).first()
            if done is not None:
                raise AlreadyRecorded(done)
        if unit.is_deleted:
            raise ValidationError({'unit': _('%(unit)s is deleted.') % {'unit': unit.code}})
        check_date(day, [unit])
        feed = Feed.all_objects.get(pk=feed.pk)
        if feed.is_deleted or feed.status != Feed.Status.ACTIVE:
            raise ValidationError({'feed': _('%(feed)s is %(status)s: a new feeding takes an active feed.') % {
                'feed': feed, 'status': _('deleted') if feed.is_deleted else str(feed.get_status_display()).lower()}})
        book = read.book_on(unit, day)
        if not book.has_fish:
            raise ValidationError({'date': _('%(unit)s holds no fish on %(date)s.') % {
                'unit': unit.code, 'date': shown_date(day)}})
        record = FeedingRecord(unit=unit, date=day, time=time, feed=feed, amount_kg=amount_kg, meals=meals,
                               feeder=feeder, notes=notes, entry_key=token, created_by=user, updated_by=user)
        record.full_clean()
        rate = 100 * amount_kg / book.biomass_kg
        if rate > settings.FEEDING_ACK_PERCENT:
            if not ack:
                raise ValidationError({'high_rate_ack': _(
                    '%(kilos)s kg is %(rate)s %% of the %(biomass)s kg %(unit)s holds on %(date)s in the book; more '
                    'than %(limit)s %% a day is unusual. Tick the box below to record it anyway.') % {
                    'kilos': amount(amount_kg), 'rate': number(rate, 1),
                    'biomass': number(book.biomass_kg, 1), 'unit': unit.code, 'date': shown_date(day),
                    'limit': settings.FEEDING_ACK_PERCENT}})
            record.high_rate_ack = True
        record.save()
        with audit.source_language():
            names = [*LOGGED, *(['high_rate_ack'] if record.high_rate_ack else [])]
            audit.record_create(user, record, audit.snapshot(record, names), label=label(record))
        return record


def void_feeding(user, record, reason):
    """The undo, as for a stock operation: the record stops counting, with its reason, within the
    backdating window. It moves no fish, so nothing else is checked."""
    with transaction.atomic():
        record = (FeedingRecord.all_objects.select_for_update(of=('self',))
                  .select_related('unit__production_department__site', 'feed').get(pk=record.pk))
        voided(user, record, reason, [record.unit], label(record))
        return record
