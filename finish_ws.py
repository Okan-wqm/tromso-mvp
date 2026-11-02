"""Overview pages for both panels; a panel is offered only to people who can use something in it."""


def rd(p):
    return open(p, encoding='utf-8', newline='').read().replace('\r\n', '\n')


def wr(p, s):
    open(p, 'w', encoding='utf-8', newline='').write(s)


def edit(path, pairs):
    s = rd(path)
    for a, b in pairs:
        assert a in s, (path, a[:70])
        s = s.replace(a, b)
    wr(path, s)


wr('config/navigation.py', '''from core.navigation import Entry, Group, Workspace

# The panels of the console, switched from the top left. Company holds what belongs to the company
# as a whole (every signed-in person has it); Production holds the farm's production side and is
# offered to people who can use something in it. Each has its own overview. The HR pages will join
# Company.
WORKSPACES = [
    Workspace('company', 'Company', always=True, groups=[
        Group('', [Entry('Overview', 'home', 'home')]),
        Group('Facility', [Entry('Sites', 'farm:site_list', 'building', 'farm.view_site')]),
        Group('Administration', [
            Entry('Activity log', 'core:activity_log', 'history', 'core.view_auditlog'),
            Entry('Roles', 'core:group_list', 'shield', 'auth.view_group'),
            Entry('Users', 'core:user_list', 'users', 'auth.view_user'),
            Entry('Database', 'core:database', 'database', 'core.browse_database'),
        ]),
    ]),
    Workspace('production', 'Production', groups=[
        Group('', [Entry('Overview', 'production_home', 'home')]),
        Group('Facility structure', [
            Entry('Production departments', 'farm:productiondepartment_list', 'layout-grid',
                  'farm.view_productiondepartment'),
            Entry('Systems', 'farm:system_list', 'waves', 'farm.view_system'),
        ]),
    ]),
]
''')

edit('core/navigation.py', [
    ('''    perm: str = ''          # empty: every signed-in user

    def url(self):
        return reverse(self.url_name)
''', '''    perm: str = ''          # empty: every signed-in user

    def url(self):
        return reverse(self.url_name)

    def allowed_for(self, user):
        return not self.perm or user.has_perm(self.perm)
'''),
    ('''@dataclass(frozen=True)
class Workspace:
    key: str
    label: str
    groups: list = field(default_factory=list)
''', '''@dataclass(frozen=True)
class Workspace:
    key: str
    label: str
    groups: list = field(default_factory=list)
    always: bool = False    # offered to everyone; otherwise only to people who can use something in it

    def offered_to(self, user):
        """Entries without a permission (the overview) are open to all, so they do not count."""
        return self.always or any(entry.perm and entry.allowed_for(user) for entry in self.entries())
'''),
    ('''    panels = []
    for workspace in workspaces():
        groups = []''', '''    panels = []
    for workspace in workspaces():
        if not workspace.offered_to(user):
            continue
        groups = []'''),
    ('''                for entry in group.entries if not entry.perm or user.has_perm(entry.perm)
''', '''                for entry in group.entries if entry.allowed_for(user)
'''),
])

# ---- the two overviews
edit('config/views.py', [
    ('''from django.shortcuts import render


def home(request):
    return render(request, 'home.html')
''', '''from django.shortcuts import render

from farm.models import ProductionDepartment, Site, System


def _counts(user, *tiles):
    """[(label, count, url)] for the records the person may see; tiles are (label, model, url name)."""
    from django.urls import reverse
    return [
        {'label': label, 'count': model.objects.count(), 'url': reverse(url_name)}
        for label, model, url_name in tiles
        if user.has_perm(f'{model._meta.app_label}.view_{model._meta.model_name}')
    ]


def home(request):
    """The company's overview."""
    return render(request, 'home.html', {
        'tiles': _counts(request.user, ('Sites', Site, 'farm:site_list')),
    })


def production_home(request):
    """The production overview."""
    return render(request, 'production_home.html', {
        'tiles': _counts(request.user,
                         ('Production departments', ProductionDepartment, 'farm:productiondepartment_list'),
                         ('Systems', System, 'farm:system_list')),
        'systems_by_status': [
            {'label': label, 'count': System.objects.filter(status=value).count()}
            for value, label in System.Status.choices
        ] if request.user.has_perm('farm.view_system') else [],
    })
'''),
])
edit('config/urls.py', [
    ("    path('', views.home, name='home'),\n", "    path('', views.home, name='home'),\n    path('production/', views.production_home, name='production_home'),\n"),
])
wr('templates/home.html', '''{% extends "app_base.html" %}
{% block title %}Company overview{% endblock %}
{% block eyebrow %}Company{% endblock %}
{% block heading %}Overview{% endblock %}
{% block content %}
{% include "_overview_tiles.html" %}
<section class="placeholder">
  <p>Welcome, {{ user.get_username }}. The company’s figures will appear here.</p>
</section>
{% endblock %}
''')
wr('templates/production_home.html', '''{% extends "app_base.html" %}
{% block title %}Production overview{% endblock %}
{% block eyebrow %}Production{% endblock %}
{% block heading %}Overview{% endblock %}
{% block content %}
{% include "_overview_tiles.html" %}
{% if systems_by_status %}
<section class="overview-block">
  <h2>Systems by status</h2>
  <ul class="status-list" role="list">
    {% for item in systems_by_status %}<li><span class="badge badge-{{ item.value|default:'' }}">{{ item.label }}</span> <strong>{{ item.count }}</strong></li>{% endfor %}
  </ul>
</section>
{% endif %}
<section class="placeholder">
  <p>The production figures will appear here.</p>
</section>
{% endblock %}
''')
wr('templates/_overview_tiles.html', '''{% if tiles %}
<ul class="tiles" role="list">
  {% for tile in tiles %}
  <li><a class="tile" href="{{ tile.url }}"><span class="tile-count">{{ tile.count }}</span><span class="tile-label">{{ tile.label }}</span></a></li>
  {% endfor %}
</ul>
{% endif %}
''')
print('ok')
