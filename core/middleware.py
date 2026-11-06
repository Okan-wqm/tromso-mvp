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
