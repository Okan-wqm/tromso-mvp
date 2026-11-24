"""The console's look (docs/design/system/README.md, "The new look"): the classic look, or the new one of the the design project
console of 2026-11-23 (the Industry design system: square hairline plates with registration marks, Barlow headings, the
status strip in the top bar). The new look is previewed, page by page, behind `?ui=next`; the classic look stays the
default until the owner switches (frontend redesign, slice S8).

`?ui=next` turns it on and a cookie keeps it, so every page the person opens next is in the new frame; `?ui=classic`
turns it off. One question answers it everywhere: `is_next(request)`, for the shell (templates/app_base.html, data-ui on
<html>) and for an island that has a next form (`{% island %}`, core/templatetags/assets.py)."""
from django.utils import timezone
from django.utils.functional import SimpleLazyObject
from django.utils.translation import gettext as _, ngettext
from django.urls import reverse

COOKIE = 'ui'
PARAM = 'ui'
NEXT = 'next'
CLASSIC = 'classic'
YEAR = 365 * 24 * 3600


def asked(request):
    """What the address asks for (`?ui=next` or `?ui=classic`), or None."""
    value = request.GET.get(PARAM)
    return value if value in (NEXT, CLASSIC) else None


def is_next(request):
    """Whether this request is drawn in the new look: the address's ?ui= first, then the cookie."""
    wanted = asked(request)
    if wanted is not None:
        return wanted == NEXT
    return request.COOKIES.get(COOKIE) == NEXT


class LookMiddleware:
    """Keeps the look an address asked for: `?ui=next` sets the cookie, `?ui=classic` removes it."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        wanted = asked(request)
        if wanted == NEXT:
            response.set_cookie(COOKIE, NEXT, max_age=YEAR, samesite='Lax', secure=request.is_secure())
        elif wanted == CLASSIC and COOKIE in request.COOKIES:
            response.delete_cookie(COOKIE, samesite='Lax')
        return response


def strip(user, now=None, attention=None):
    """The status strip of the new look's top bar (the design's direction B): what needs a look (`alarms_item`), the people
    on site and the company's clock, each only for a person who may see it, from the same readers as their pages.
    [{key, text, url, status}]. The page draws it with the alarms still being read (the reader looks at every unit's
    water, so the page never waits for it); the whole strip is then polled (`strip_view`, frontend/poll.ts), so the
    clock and the muster count never stand still beside a live alarm count."""
    from core.dates import company_zone

    now = now or timezone.now()
    items = []
    if user.has_perm('alarms.view_alarm'):
        items.append(alarms_item(attention) if attention is not None else
                     {'key': 'alarms', 'url': reverse('alarms:alarm_list'), 'text': _('Reading the alarms…'), 'status': ''})
    if user.has_perm('hr.view_attendancerecord'):
        from hr import read as hr_read
        from hr.models import SchedulingSettings
        on_site = hr_read.muster(now, SchedulingSettings.get().forgotten_after_hours)[0]
        items.append({'key': 'on_site', 'url': reverse('hr:today'), 'status': '',
                      'text': ngettext('%(count)d on site', '%(count)d on site', on_site) % {'count': on_site}})
    zone = company_zone()
    items.append({'key': 'clock', 'url': '', 'status': '',
                  'text': f'{timezone.localtime(now, zone):%d.%m.%Y, %H:%M} · {zone.key}'})
    return items


def alarms_item(attention):
    """The strip's alarms item from alarms.read.attention: every count that needs a look, worst first, none hidden behind
    another ("1 open alarm · 3 units critical · 2 units with no recent data"), in the cards' own words for their rungs;
    "No open alarms" only when nothing is open and every stocked unit is OK or a note (`Attention.quiet`)."""
    counts = (
        (attention.alarms, lambda n: ngettext('%(count)d open alarm', '%(count)d open alarms', n)),
        (attention.critical, lambda n: ngettext('%(count)d unit critical', '%(count)d units critical', n)),
        (attention.unreadable, lambda n: ngettext('%(count)d unit cannot be read', '%(count)d units cannot be read', n)),
        (attention.warning, lambda n: ngettext('%(count)d unit with a warning', '%(count)d units with a warning', n)),
        (attention.blind, lambda n: ngettext('%(count)d unit with no recent data', '%(count)d units with no recent data', n)),
        (attention.unjudged, lambda n: ngettext('%(count)d unit with no limit', '%(count)d units with no limit', n)))
    parts = [words(count) % {'count': count} for count, words in counts if count]
    text = ' · '.join(parts) if parts else _('No open alarms')
    return {'key': 'alarms', 'url': reverse('alarms:alarm_list'), 'text': text, 'status': attention.status}


def strip_view(request):
    """The strip again (polled by the new look's top bar every 30 s): its items, the alarms read now."""
    from django.shortcuts import render

    from alarms import read as alarms_read
    found = alarms_read.attention() if request.user.has_perm('alarms.view_alarm') else None
    return render(request, 'core/_strip.html', {'items': strip(request.user, attention=found)})


def context(request):
    """UI_NEXT for <html data-ui>, and the new look's status strip, read only when a page draws it (context processor)."""
    next_look = is_next(request)
    user = getattr(request, 'user', None)
    signed_in = user is not None and user.is_authenticated
    return {'UI_NEXT': next_look,
            'ui_strip': SimpleLazyObject(lambda: strip(user)) if next_look and signed_in else []}
