"""In the tests (settings.CLOCK_GUARD), `|date` and `|time` refuse an aware moment that no clock filter has put on a
named clock: for an aware value they fall back to the server's zone (UTC), so a Norwegian page would show 08:19 for a
09:19 on the site. A page shows a time through `|site_clock:site` or `|company_clock` (core.templatetags.dates), which
hand on a naive wall time. The machine formats (`c`, `U`, `Y-m-d`: a `datetime` attribute, an address) stay allowed.
Installed once from core's app config; never in production, where the filters stay Django's own."""
from datetime import datetime

from django.utils import timezone

MACHINE = {'c', 'U', 'Y-m-d'}


class UnclockedTime(ValueError):
    pass


def install():
    from django.template import defaultfilters
    for name in ('date', 'time'):
        original = defaultfilters.register.filters[name]
        if getattr(original, 'clock_guarded', False):
            continue

        def guarded(value, arg=None, _original=original, _name=name):
            if isinstance(value, datetime) and timezone.is_aware(value) and arg not in MACHINE:
                raise UnclockedTime(f'|{_name}:{arg!r} of an aware moment ({value.isoformat()}) without a clock: put it '
                                    f'through |site_clock:site or |company_clock first.')
            return _original(value, arg)

        guarded.expects_localtime, guarded.is_safe, guarded.clock_guarded = True, False, True
        guarded._filter_name = name
        defaultfilters.register.filters[name] = guarded
