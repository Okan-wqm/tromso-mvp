from django.core.exceptions import PermissionDenied

from . import navigation


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
