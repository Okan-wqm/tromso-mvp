"""The rail menu as data: groups of entries, each shown only to people allowed to read it.
The project's menu lives in config/navigation.py; `rail` is the context processor."""
from dataclasses import dataclass, field

from django.conf import settings
from django.urls import reverse
from django.utils.module_loading import import_string


@dataclass(frozen=True)
class Entry:
    label: str
    url_name: str
    icon: str
    perm: str = ''          # empty: every signed-in user

    def url(self):
        return reverse(self.url_name)


@dataclass(frozen=True)
class Group:
    label: str
    entries: list = field(default_factory=list)


def rail(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    path = request.path
    groups = []
    for group in import_string(settings.RAIL_MENU):
        entries = []
        for entry in group.entries:
            if entry.perm and not user.has_perm(entry.perm):
                continue
            url = entry.url()
            current = path == url if url == '/' else path.startswith(url)
            entries.append({'label': entry.label, 'url': url, 'icon': entry.icon, 'current': current})
        if entries:
            groups.append({'label': group.label, 'entries': entries})
    return {'rail_groups': groups}
