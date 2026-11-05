"""Template helpers of the HR pages."""
from zoneinfo import ZoneInfo

from django import template
from django.conf import settings
from django.utils import timezone

register = template.Library()


@register.filter
def on_clock(value, zone):
    """A moment as the wall clock of a site shows it: `zone` is a ZoneInfo or the name of one ('' for the company's). Times of
    the HR pages are read on the site's clock, never in the browser's or the server's zone. The result is naive on purpose:
    the template engine would bring an aware time back to the current zone before `date` formats it."""
    if value is None:
        return value
    if not zone:
        zone = settings.TIME_ZONE
    if isinstance(zone, str):
        zone = ZoneInfo(zone)
    return timezone.make_naive(value, zone)
