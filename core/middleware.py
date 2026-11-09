from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import OperationalError
from django.utils.translation import gettext

from . import navigation, platform


class WorkspaceMiddleware:
    """Remembers the panel (workspace) the person is working in, so that a page that belongs to
    none, such as changing the password, shows the menu of the panel they came from."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        key = navigation.workspace_of(request.path)
        if key and request.session.get(navigation.SESSION_KEY) != key:
            request.session[navigation.SESSION_KEY] = key
        return self.get_response(request)


class PlatformSettingsMiddleware:
    """Opens the request's memo of the platform owner's settings (core.platform): the row is read once per request, not
    once per record a page lists."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = platform.open_memo()
        try:
            return self.get_response(request)
        finally:
            platform.close_memo(token)


class MenuAccessMiddleware:
    """One rule for the menu and the address bar: a page whose menu line is left out for the person (`Entry.show_when`,
    e.g. Team overview for someone who leads nobody) is refused at its address too, with the 403 page."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated and navigation.refused(user, request.path):
            raise PermissionDenied
        return None


# The SQLSTATEs of a write the database aborted for another one at the same moment: a deadlock, a serialization failure.
CROSSED = {'40P01', '40001'}


class CrossedWritesMiddleware:
    """The backstop of the lock order (core.softdelete, LOCK ORDER): a write the database aborted for another one at the
    same moment rolled back whole, so nothing was saved; the person is told to send it again and comes back to the page
    they sent it from, instead of a server error. Any other database error stays a fault."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not isinstance(exception, OperationalError) or request.method != 'POST':
            return None
        if getattr(exception.__cause__, 'sqlstate', None) not in CROSSED:
            return None
        from .crud import done
        messages.error(request, gettext('Someone else saved at the same moment: nothing was saved. Send it again.'))
        return done(request, request.get_full_path())
