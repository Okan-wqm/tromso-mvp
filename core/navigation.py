"""The menu as data. It is split into workspaces (panels such as Company and Production), each with
groups of entries shown only to people allowed to read them. The project's menu lives in
config/navigation.py; `rail` is the context processor, and WorkspaceMiddleware (core.middleware)
remembers the panel a person works in so that pages belonging to none (change password) keep it."""
from dataclasses import dataclass, field

from django.conf import settings
from django.urls import reverse
from django.utils.module_loading import import_string

SESSION_KEY = 'workspace'


@dataclass(frozen=True)
class Entry:
    label: str               # translatable text
    url_name: str
    icon: str
    perm: str = ''          # empty: every signed-in user

    def url(self):
        return reverse(self.url_name)

    def allowed_for(self, user):
        return not self.perm or user.has_perm(self.perm)

    def matches(self, path):
        url = self.url()
        return path == url if url == '/' else path.startswith(url)


@dataclass(frozen=True)
class Group:
    label: str
    entries: list = field(default_factory=list)


@dataclass(frozen=True)
class Workspace:
    key: str
    label: str
    groups: list = field(default_factory=list)
    always: bool = False    # offered to everyone; otherwise only to people who can use something in it

    def offered_to(self, user):
        """Entries without a permission (the overview) are open to all, so they do not count."""
        return self.always or any(entry.perm and entry.allowed_for(user) for entry in self.entries())

    def entries(self):
        return [entry for group in self.groups for entry in group.entries]


def workspaces():
    return import_string(settings.RAIL_MENU)


def entries():
    """Every entry of every workspace."""
    return [entry for workspace in workspaces() for entry in workspace.entries()]


def workspace_of(path):
    """The key of the workspace that has an entry for this page, or None for a page that has none."""
    for workspace in workspaces():
        if any(entry.matches(path) for entry in workspace.entries()):
            return workspace.key
    return None


def rail(request):
    """The panels the person may use, the one they are in, and its menu."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    panels = []
    for workspace in workspaces():
        if not workspace.offered_to(user):
            continue
        groups = []
        for group in workspace.groups:
            shown = [
                {'label': entry.label, 'url': entry.url(), 'icon': entry.icon, 'current': entry.matches(request.path)}
                for entry in group.entries if entry.allowed_for(user)
            ]
            if shown:
                groups.append({'label': group.label, 'entries': shown})
        if groups:
            panels.append({'key': workspace.key, 'label': workspace.label, 'groups': groups,
                           'url': groups[0]['entries'][0]['url']})
    chosen = workspace_of(request.path) or request.session.get(SESSION_KEY)
    current = next((panel for panel in panels if panel['key'] == chosen), panels[0] if panels else None)
    return {'workspaces': panels, 'workspace': current, 'rail_groups': current['groups'] if current else []}
