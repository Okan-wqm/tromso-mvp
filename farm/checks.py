"""System checks of the farm app, run when the server starts (and before `migrate`)."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.checks import Error, register


def company_zone_problem(zone):
    """Why `zone` cannot be the company's time zone, or None: it must be a known zone and one a site may be given
    (Site.TIMEZONES), because migration farm/0030 writes it into every site that had none and a site's form offers it."""
    from .models import Site
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return f'COMPANY_TIME_ZONE {zone!r} is not a known time zone.'
    if zone not in dict(Site.TIMEZONES):
        return f'COMPANY_TIME_ZONE {zone!r} is not one a site may be given ({", ".join(dict(Site.TIMEZONES))}).'
    return None


@register()
def company_time_zone(app_configs, **kwargs):
    """The company's time zone (settings.COMPANY_TIME_ZONE) is a zone the sites may have: a typo would be written into
    every zone-less site by migration farm/0030 and then every read of a site's day would fail."""
    problem = company_zone_problem(settings.COMPANY_TIME_ZONE)
    return [] if problem is None else [Error(problem, hint='Set COMPANY_TIME_ZONE in the environment to one of them.',
                                             id='farm.E001')]
