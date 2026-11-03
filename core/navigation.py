"""The menu as data. It is split into workspaces (panels such as Company and Production); a panel's
menu has sections under main headings (Setup, Operations), each with groups of entries shown only to
people allowed to read them. The project's menu lives in config/navigation.py; `rail` is the context
processor, and WorkspaceMiddleware (core.middleware) remembers the panel a person works in so that
pages belonging to none (change password) keep it.

The menu is the one place that says where a page sits: the role matrix (core.access) and a tab's
page heading (core.crud) take their grouping from it through `place`."""
from dataclasses import dataclass, field

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse
from django.utils.module_loading import import_string
from django.utils.text import format_lazy

SESSION_KEY = 'workspace'


@dataclass(frozen=True)
class Badge:
    """A number beside a menu entry (the unread messages), and the address of a fragment that renders the
    number again (polled by frontend/poll.ts); no address for a panel's total, which is not polled."""
    count: int
    url: str

    @property
    def text(self):
        """What the badge shows: nothing for 0, the number, or 99+."""
        return '' if self.count <= 0 else '99+' if self.count > 99 else str(self.count)


@dataclass(frozen=True)
class Entry:
    label: str               # translatable text
    url_name: str
    icon: str
    perm: str = ''          # empty: every signed-in user
    badge: str = ''         # the dotted path of a function(user) -> Badge, for a number beside the entry

    def url(self):
        return reverse(self.url_name)

    def allowed_for(self, user):
        return not self.perm or user.has_perm(self.perm)

    def matches(self, path):
        url = self.url()
        return path == url if url == '/' else path.startswith(url)

    def badge_for(self, user):
        return import_string(self.badge)(user) if self.badge else None


@dataclass(frozen=True)
class Group:
    label: str
    entries: list = field(default_factory=list)


@dataclass(frozen=True)
class Section:
    """A main heading of a panel's menu, e.g. Setup or Operations; '' for entries above them."""
    label: str
    groups: list = field(default_factory=list)


@dataclass(frozen=True)
class Workspace:
    key: str
    label: str
    sections: list = field(default_factory=list)
    always: bool = False    # offered to everyone; otherwise only to people who can use something in it

    def offered_to(self, user):
        """Entries without a permission (the overview) are open to all, so they do not count."""
        return self.always or any(entry.perm and entry.allowed_for(user) for entry in self.entries())

    def entries(self):
        return [entry for section in self.sections for group in section.groups for entry in group.entries]


@dataclass(frozen=True)
class Place:
    """Where an entry sits in the menu."""
    workspace: Workspace
    section: Section
    group: Group
    entry: Entry

    @property
    def path(self):
        """'Production · Setup · Facility structure', translated when shown."""
        labels = [label for label in (self.workspace.label, self.section.label, self.group.label) if label]
        return format_lazy(' · '.join(['{}'] * len(labels)), *labels)


def workspaces():
    return import_string(settings.RAIL_MENU)


def entries():
    """Every entry of every workspace."""
    return [entry for workspace in workspaces() for entry in workspace.entries()]


def place(perm):
    """Where the page read with this permission ('farm.view_site') sits in the menu."""
    for workspace in workspaces():
        for section in workspace.sections:
            for group in section.groups:
                for entry in group.entries:
                    if entry.perm == perm:
                        return Place(workspace, section, group, entry)
    raise ImproperlyConfigured(f'No menu entry in {settings.RAIL_MENU} is read with {perm!r}: add one.')


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
        sections = []
        for section in workspace.sections:
            groups = []
            for group in section.groups:
                shown = [
                    {'label': entry.label, 'url': entry.url(), 'icon': entry.icon,
                     'current': entry.matches(request.path), 'badge': entry.badge_for(user)}
                    for entry in group.entries if entry.allowed_for(user)
                ]
                if shown:
                    groups.append({'label': group.label, 'entries': shown})
            if groups:
                sections.append({'label': section.label, 'groups': groups})
        if sections:
            badges = [entry['badge'].count for section in sections for group in section['groups']
                      for entry in group['entries'] if entry['badge']]
            panels.append({'key': workspace.key, 'label': workspace.label, 'sections': sections,
                           'url': sections[0]['groups'][0]['entries'][0]['url'],
                           'badge': Badge(sum(badges), '') if badges else None})
    chosen = workspace_of(request.path) or request.session.get(SESSION_KEY)
    current = next((panel for panel in panels if panel['key'] == chosen), panels[0] if panels else None)
    return {'workspaces': panels, 'workspace': current, 'rail_sections': current['sections'] if current else []}
