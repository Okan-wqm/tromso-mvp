"""The farm's dates, one rule for every daily record (a stock operation, a feeding): today is the
farm's own day, in the time zone of the unit's site, never the UTC date of a browser; a record may be
dated at most STOCK_BACKDATE_DAYS back and never in the future, and the same window says how old a
record may be voided (owner decisions Q3 and Q-F4)."""
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import formats, timezone
from django.utils.translation import gettext as _


def local_today(unit=None):
    """Today on the farm: in the time zone of the unit's site, else the company's (settings.TIME_ZONE).
    Never the UTC date of a browser (the source's dialogs were a day behind east of UTC)."""
    site = unit.production_department.site if unit is not None else None
    name = site.timezone if site is not None and site.timezone else settings.TIME_ZONE
    return timezone.localdate(timezone=ZoneInfo(name))


def earliest(unit=None):
    """The first day a record may be dated (and the oldest one that may be voided)."""
    return local_today(unit) - timedelta(days=settings.STOCK_BACKDATE_DAYS)


def shown_date(day):
    return formats.date_format(day, 'DATE_FORMAT')


def check_date(day, units):
    """Refuses a date in the future or before the backdating window of any of the units."""
    for unit in units:
        if day > local_today(unit):
            raise ValidationError({'date': _('The date cannot be in the future.')})
        if day < earliest(unit):
            raise ValidationError({'date': _('Operations can be dated at most %(days)d days back.')
                                   % {'days': settings.STOCK_BACKDATE_DAYS}})
