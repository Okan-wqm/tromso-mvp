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


def strip(user, now=None):
    """The status strip of the new look's top bar (the design's direction B): the open alarms, the people on site and the
    company's clock, each only for a person who may see it, from the same readers as their pages. [{key, text, url,
    status}]: status 'critical' when a critical alarm is open, 'warning' for open warnings only, '' otherwise."""
    from core.dates import company_zone

    now = now or timezone.now()
    items = []
    if user.has_perm('alarms.view_alarm'):
        # The alarms' item reads the water of every live unit (alarms.read.attention), so the page never waits for it:
        # it comes as a fragment (frontend/poll.ts), and until it is there it says it is being read, never "no alarms".
        items.append({'key': 'alarms', 'url': reverse('alarms:alarm_list'), 'poll': reverse('core:ui_strip_alarms'),
                      'text': _('Reading the alarms…'), 'status': ''})
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
    """The strip's alarms item from alarms.read.attention: the open alarms, and, where none is open yet, what the water
    judges now. It says "No open alarms" only when nothing is open, critical, warning or blind."""
    if attention.alarms:
        text = ngettext('%(count)d open alarm', '%(count)d open alarms', attention.alarms) % {'count': attention.alarms}
    elif attention.critical:
        text = ngettext('%(count)d unit critical', '%(count)d units critical', attention.critical) % {'count': attention.critical}
    elif attention.unreadable:
        text = _('Live values cannot be read')
    elif attention.blind:
        text = ngettext('%(count)d unit without recent data', '%(count)d units without recent data',
                        attention.blind) % {'count': attention.blind}
    elif attention.warning:
        text = ngettext('%(count)d unit with a warning', '%(count)d units with a warning',
                        attention.warning) % {'count': attention.warning}
    else:
        text = _('No open alarms')
    return {'key': 'alarms', 'url': reverse('alarms:alarm_list'), 'text': text, 'status': attention.status}


def strip_alarms(request):
    """The strip's alarms item, again (polled by the top bar of the new look): 403 for a person who may not see alarms."""
    from django.core.exceptions import PermissionDenied
    from django.shortcuts import render
    from alarms import read as alarms_read
    if not request.user.has_perm('alarms.view_alarm'):
        raise PermissionDenied
    return render(request, 'core/_strip_item.html', {'item': alarms_item(alarms_read.attention())})


def context(request):
    """UI_NEXT for <html data-ui>, and the new look's status strip, read only when a page draws it (context processor)."""
    next_look = is_next(request)
    user = getattr(request, 'user', None)
    signed_in = user is not None and user.is_authenticated
    return {'UI_NEXT': next_look,
            'ui_strip': SimpleLazyObject(lambda: strip(user)) if next_look and signed_in else []}
