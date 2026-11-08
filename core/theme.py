"""The console's colour theme (docs/design/system/README.md, Colour): five places on the Norwegian coast, Fjord (the
default, day), Polarnatt (night), Nordlys (night, for the monitoring wall), Tang (day) and Laks (warm day). The person
picks one in the user menu; a cookie keeps it and the server writes it on <html data-theme>, so the first paint already
has it. Never the system's colour scheme: a screen at the tank side looks the same whatever the device prefers."""
from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

COOKIE = 'theme'
DEFAULT = 'fjord'
# The themes' names are names (Nordlys stays Nordlys in Turkish), as the design system gives them.
THEMES = (('fjord', 'Fjord'), ('polarnatt', 'Polarnatt'), ('nordlys', 'Nordlys'), ('tang', 'Tang'), ('laks', 'Laks'))
KEYS = {key for key, _name in THEMES}
YEAR = 365 * 24 * 3600


def chosen(request):
    """The theme of the request's cookie, or Fjord for none or one that is not a theme."""
    value = request.COOKIES.get(COOKIE)
    return value if value in KEYS else DEFAULT


def context(request):
    """THEME for <html data-theme>, THEMES for the user menu's choice (context processor)."""
    return {'THEME': chosen(request), 'THEMES': THEMES}


@login_not_required
@require_POST
def set_theme(request):
    """Keeps the chosen theme in its cookie and returns to the page it was chosen on (a page of this site only)."""
    target = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()},
                                           require_https=request.is_secure()):
        target = '/'
    response = HttpResponseRedirect(target)
    value = request.POST.get('theme')
    if value in KEYS:
        response.set_cookie(COOKIE, value, max_age=YEAR, samesite='Lax', secure=request.is_secure())
    return response
