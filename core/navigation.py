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
from django.utils.functional import SimpleLazyObject
from django.utils.module_loading import import_string
from django.utils.text import format_lazy, slugify
from django.utils.translation import gettext_lazy as _, override

SESSION_KEY = 'workspace'

# The area hues of the design system (docs/design/system/README.md, Colour; the --area-* tokens): where a page sits, drawn
# on its rail icon and its page head, never on data or a status. An entry without one of its own is neutral.
AREAS = ('farm', 'water', 'feed', 'stock', 'neutral')


def area_of(workspace, section, group, entry):
    """The nearest area set: the entry's, its group's, its section's, its panel's; else neutral."""
    area = entry.area or group.area or section.area or workspace.area or 'neutral'
    if area not in AREAS:
        raise ImproperlyConfigured(f'{entry.url_name}: area {area!r} is not one of {AREAS}')
    return area


@dataclass(frozen=True)
class Badge:
    """A number beside a menu entry (the unread messages), and the address of a fragment that renders the
    number again (polled by frontend/poll.ts); no address for one that is not polled (a panel's total, the pending leave
    requests: they change on the next page)."""
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
    hidden: bool = False    # no line in the menu (a settings page reached from another page's links); it still
                            # has its place: the role matrix and the page heading read it, and it is current there
    show_when: str = ''     # the dotted path of a function(user) -> bool: the line is shown only when it says so (Company's
                            # HR lines are left out for a person whose HR is all in Production). The address agrees with the
                            # menu: a line left out is refused at its address too (core.middleware.MenuAccessMiddleware)
    show_note: str = ''     # who is not offered it, in words: the role matrix says it under the area
    area: str = ''          # its area hue (AREAS); '' takes its group's, section's or panel's

    def url(self):
        return reverse(self.url_name)

    def allowed_for(self, user):
        return not self.perm or user.has_perm(self.perm)

    def matches(self, path):
        url = self.url()
        return path == url if url == '/' else path.startswith(url)

    def shown_to(self, user, answers=None):
        """Whether the line is shown to the person: their permission, not hidden, and its `show_when` (asked once per
        function and request: `answers` caches them)."""
        if not self.allowed_for(user) or self.hidden:
            return False
        if not self.show_when:
            return True
        answers = {} if answers is None else answers
        if self.show_when not in answers:
            answers[self.show_when] = bool(import_string(self.show_when)(user))
        return answers[self.show_when]

    def badge_for(self, user):
        return import_string(self.badge)(user) if self.badge else None


@dataclass(frozen=True)
class Group:
    label: str
    entries: list = field(default_factory=list)
    area: str = ''


@dataclass(frozen=True)
class Section:
    """A main heading of a panel's menu, e.g. Setup or Operations; '' for entries above them. `collapsed`: folded away in
    the rail (Setup, last), open on a page it holds and as the person left it elsewhere (frontend/collapse.ts)."""
    label: str
    groups: list = field(default_factory=list)
    collapsed: bool = False
    area: str = ''


@dataclass(frozen=True)
class Workspace:
    key: str
    label: str
    sections: list = field(default_factory=list)
    always: bool = False    # offered to everyone; otherwise only to people who can use something in it
    area: str = ''

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
    def heading(self):
        """The nearest labelled heading the entry sits under, shown above a page's title: its group's label, or,
        for an entry in a group without one (Production › Reports › Regulatory reports), its section's, else its
        workspace's."""
        return self.group.label or self.section.label or self.workspace.label

    @property
    def trail(self):
        """'Company › Administration › Platform settings': the way to the page through the menu, as a message names it
        (in the language active when it is asked)."""
        return ' › '.join(str(label) for label in (self.workspace.label, self.section.label, self.group.label,
                                                  self.entry.label) if label)

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


def entry_for(path):
    """The menu line a page belongs to: the one whose address is the longest start of the page's (the rail's current
    line), or None."""
    return max((entry for entry in entries() if entry.matches(path)), key=lambda entry: len(entry.url()), default=None)


def notes(perm):
    """["Company · HR · Shift schedule: not for a person whose HR is all in Production"]: the lines read with `perm` that
    are shown only to some, for the role matrix (a role gives the right; the line still depends on the person)."""
    found = []
    for workspace in workspaces():
        for section in workspace.sections:
            for group in section.groups:
                for entry in group.entries:
                    if entry.perm == perm and entry.show_when and not entry.hidden:
                        labels = [str(label) for label in (workspace.label, section.label, entry.label) if label]
                        found.append(f'{" · ".join(labels)}: {entry.show_note}')
    return found


def refused(user, path):
    """Whether the page is refused to the person because its menu line is left out for them (`show_when`), though they
    hold its permission: the menu and the address bar agree. A line never in the menu (`hidden`) is not a refusal."""
    entry = entry_for(path)
    return (entry is not None and not entry.hidden and bool(entry.show_when) and entry.allowed_for(user)
            and not entry.shown_to(user))


def place(perm):
    """Where the page read with this permission ('farm.view_site') sits in the menu."""
    for workspace in workspaces():
        for section in workspace.sections:
            for group in section.groups:
                for entry in group.entries:
                    if entry.perm == perm:
                        return Place(workspace, section, group, entry)
    raise ImproperlyConfigured(f'No menu entry in {settings.RAIL_MENU} is read with {perm!r}: add one.')


def trail(perm, fallback):
    """The way through the menu to the page read with this permission ('Company › Administration › Platform
    settings'), for a message that names where something is done; `fallback` (the page's name) when the menu in use
    has no such entry."""
    try:
        return place(perm).trail
    except ImproperlyConfigured:
        return str(fallback)


def page(url_name):
    """Where the page with this URL name sits in the menu: for pages read with one permission (the meal board and
    the feeding records are both read with farm.view_feedingrecord), whose `place` is the first of them."""
    for workspace in workspaces():
        for section in workspace.sections:
            for group in section.groups:
                for entry in group.entries:
                    if entry.url_name == url_name:
                        return Place(workspace, section, group, entry)
    raise ImproperlyConfigured(f'No menu entry in {settings.RAIL_MENU} opens {url_name!r}: add one.')


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
    # One entry is current: the one whose address is the longest start of the page's (Records at /operations/feeding/
    # is not current on its sibling /operations/feeding/protocols/).
    current_url = max((entry.url() for entry in entries() if entry.matches(request.path)), key=len, default=None)
    panels = []
    answers = {}
    for workspace in workspaces():
        if not workspace.offered_to(user):
            continue
        sections = []
        for section in workspace.sections:
            groups = []
            for group in section.groups:
                shown = [
                    {'label': entry.label, 'url': entry.url(), 'icon': entry.icon,
                     'current': entry.url() == current_url, 'badge': entry.badge_for(user),
                     'area': area_of(workspace, section, group, entry)}
                    for entry in group.entries if entry.shown_to(user, answers)
                ]
                if shown:
                    groups.append({'label': group.label, 'entries': shown})
            if groups:
                sections.append({'label': section.label, 'groups': groups, 'collapsed': section.collapsed,
                                 'key': section_key(workspace, section),
                                 'current': any(entry['current'] for group in groups for entry in group['entries'])})
        if sections:
            badges = [entry['badge'].count for section in sections for group in section['groups']
                      for entry in group['entries'] if entry['badge']]
            panels.append({'key': workspace.key, 'label': workspace.label, 'sections': sections,
                           'url': sections[0]['groups'][0]['entries'][0]['url'],
                           'badge': Badge(sum(badges), '') if badges else None})
    chosen = workspace_of(request.path) or request.session.get(SESSION_KEY)
    current = next((panel for panel in panels if panel['key'] == chosen), panels[0] if panels else None)
    sections = current['sections'] if current else []
    foot = getattr(settings, 'RAIL_FOOT', '')
    here = page_place(request.path)
    return {'workspaces': panels, 'workspace': current, 'rail_sections': sections, 'bottom_bar': bottom_bar(sections),
            'rail_foot': SimpleLazyObject(lambda: import_string(foot)(user)) if foot else '',
            'page_area': here[0], 'page_icon': here[1]}


def page_place(path):
    """(area, icon) of the menu line a page belongs to, for its page head's area chip; ('neutral', '') for a page that
    belongs to none."""
    entry = entry_for(path)
    if entry is None:
        return 'neutral', ''
    for workspace in workspaces():
        for section in workspace.sections:
            for group in section.groups:
                if any(each is entry for each in group.entries):
                    return area_of(workspace, section, group, entry), entry.icon
    return 'neutral', ''


def section_key(workspace, section):
    """A section's name for the browser to remember it by, the same in every language: production-setup."""
    with override('en'):
        return f'{workspace.key}-{slugify(str(section.label)) or "top"}'


# The bottom bar below 1024 px (docs/design/system/README.md, Shell): the daily pages under a short name, then More (the
# whole menu as a sheet). A panel without them (Company) shows its first pages under their own names.
BOTTOM_BAR = (('farm:meal_board', _('Meals')), ('farm:water', _('Water')), ('farm:production_units', _('Units')),
              ('inventory:storage', _('Storage')))
BOTTOM_BAR_SIZE = 4


def bottom_bar(sections):
    """The bottom bar's links out of the panel's menu as the person sees it (so only what their role opens)."""
    shown = [entry for section in sections for group in section['groups'] for entry in group['entries']]
    by_url = {entry['url']: entry for entry in shown}
    daily = [{**by_url[reverse(name)], 'label': label} for name, label in BOTTOM_BAR if reverse(name) in by_url]
    if daily:
        return daily
    return shown[:BOTTOM_BAR_SIZE]


def page_base(request):
    """The frame a page that is not a tab's own (an error page) draws in: the dialog's when the dialog asked for it
    (X-Modal), the console's for a person signed in, the sign-in page's for a visitor (context processor)."""
    from .crud import is_modal
    if is_modal(request):
        return {'page_base': 'modal_base.html'}
    user = getattr(request, 'user', None)
    return {'page_base': 'app_base.html' if user is not None and user.is_authenticated else 'auth_base.html'}
