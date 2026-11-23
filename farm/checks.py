"""System checks of the farm app, run when the server starts (and before `migrate`)."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register


def company_zone_problem(zone):
    """Why `zone` cannot be the company's time zone, or None: it must be a known zone and one a site may be given
    (Site.TIMEZONES), because migration farm/0028 writes it into every site that had none and a site's form offers it."""
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
    every zone-less site by migration farm/0028 and then every read of a site's day would fail."""
    problem = company_zone_problem(settings.COMPANY_TIME_ZONE)
    return [] if problem is None else [Error(problem, hint='Set COMPANY_TIME_ZONE in the environment to one of them.',
                                             id='farm.E001')]


@register(Tags.database)
def ph_converted_by_an_older_formula(app_configs, **kwargs):
    """Samples whose pH was measured on another scale than NBS and put on the NBS scale by another formula than the
    application's (farm/water/rederive.py): after a formula change they hold an NBS pH the same measurement typed today
    would not give, until `manage.py rederive_ph` converts them again. Counted, nothing is changed. Run with `manage.py
    check --database default`; quiet when there are none or the table is not there yet."""
    from django.db import DatabaseError

    from .water import rederive
    try:
        count = rederive.stale().count()
    except DatabaseError:
        return []
    if not count:
        return []
    return [Warning(
        f'{count} water sample(s) hold a pH measured on another scale than NBS that was put on the NBS scale by an '
        f'older formula than the application’s.',
        hint='Back up the database, then run `manage.py rederive_ph --dry-run` and `manage.py rederive_ph`. A sample '
             'it lists as "NOT converted again" stays counted here, voided or not (its reason says why: the point’s '
             'water is said to be salt-added, or the core cannot work the water out): if the unit’s water origin is '
             'wrong, correct it and run it again.',
        id='farm.W001')]
