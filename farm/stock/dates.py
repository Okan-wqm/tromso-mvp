"""The farm's dates, one rule for every daily record (a stock operation, a feeding, a water sample, a
movement of the store): today is the farm's own day, on the clock of the site (farm.models.site.zone_of),
never the UTC date of a browser; a record may be dated at most STOCK_BACKDATE_DAYS back and never in the
future, and the same window says how old a record may be voided (owner decisions Q3 and Q-F4). A record
of a unit is on its site's clock; a movement of the store (inventory) on the clocks of the sites of its
storage locations."""
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import formats, timezone
from django.utils.translation import gettext as _

from farm.models.site import zone_of


def site_today(site):
    """Today on the site's clock, else the company's (a unit's production department may have no site)."""
    return timezone.localdate(timezone=zone_of(site))


def site_earliest(site):
    """The first day a record on the site may be dated (and the oldest one that may be voided)."""
    return site_today(site) - timedelta(days=settings.STOCK_BACKDATE_DAYS)


def _site(unit):
    return unit.production_department.site if unit is not None else None


def sites_of(units):
    """The sites whose clocks the records of these units are dated on (None for a unit without a site)."""
    return [_site(unit) for unit in units]


def local_today(unit=None):
    """Today on the farm: on the clock of the unit's site, else the company's."""
    return site_today(_site(unit))


def earliest(unit=None):
    """The first day a record of the unit may be dated (and the oldest one that may be voided)."""
    return site_earliest(_site(unit))


def start_of(day, unit):
    """The first moment of `day` on the clock of the unit's site (a handling's day starts its fast count; the day
    after a feeding without a time is when that feeding counts)."""
    return datetime.combine(day, time.min, tzinfo=zone_of(_site(unit)))


def end_of(day, unit):
    """The last moment of `day` on the clock of the unit's site."""
    return start_of(day + timedelta(days=1), unit) - timedelta(microseconds=1)


def shown_date(day):
    return formats.date_format(day, 'DATE_FORMAT')


def check_date(day, units):
    """Refuses a date in the future or before the backdating window of any of the units."""
    check_site_date(day, sites_of(units))


def check_site_date(day, sites):
    """Refuses a date in the future or before the backdating window on the clock of any of the sites."""
    for site in sites:
        if day > site_today(site):
            raise ValidationError({'date': _('The date cannot be in the future.')})
        if day < site_earliest(site):
            raise ValidationError({'date': _('Operations can be dated at most %(days)d days back.')
                                   % {'days': settings.STOCK_BACKDATE_DAYS}})
