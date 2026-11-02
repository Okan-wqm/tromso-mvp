"""The workspace switcher in the rail head, and one shared menu behaviour for it and the user menu."""


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


wr('templates/_workspace_brand.html', '''<span class="logo-plate" aria-hidden="true">S</span>
<span class="workspace-text">
  <span class="workspace-brand">Suderra</span>
  <span class="workspace-name">{{ workspace.label }}</span>
</span>
''')

edit('templates/app_base.html', [
    ('''        <a class="rail-brand" href="{% url 'home' %}">
          <span class="logo-plate" aria-hidden="true">S</span>
          <span class="rail-brand-text">Suderra</span>
        </a>
''', '''        {% if workspaces|length > 1 %}
        <div class="menu workspace-menu" data-menu>
          <button type="button" class="workspace-trigger" data-menu-toggle aria-haspopup="true" aria-expanded="false" aria-controls="workspace-panel" title="Switch panel">
            {% include "_workspace_brand.html" %}
            {% include "icons/_icon.html" with name="chevron-down" %}
          </button>
          <div class="menu-panel" id="workspace-panel" data-menu-panel hidden>
            <p class="menu-head">Panels</p>
            {% for panel in workspaces %}
            <a class="menu-item" href="{{ panel.url }}"{% if panel.key == workspace.key %} aria-current="true"{% endif %}>{{ panel.label }}</a>
            {% endfor %}
          </div>
        </div>
        {% else %}
        <a class="workspace-trigger" href="{% url 'home' %}">{% include "_workspace_brand.html" %}</a>
        {% endif %}
'''),
    ('''        <div class="user-menu">
          <button type="button" class="user-trigger" data-user-toggle aria-haspopup="true" aria-expanded="false" aria-controls="user-panel">''',
     '''        <div class="menu user-menu" data-menu>
          <button type="button" class="user-trigger" data-menu-toggle aria-haspopup="true" aria-expanded="false" aria-controls="user-panel">'''),
    ('''          <div class="user-panel" id="user-panel" hidden>
            <p class="user-panel-head">''', '''          <div class="menu-panel menu-panel-right" id="user-panel" data-menu-panel hidden>
            <p class="menu-head">'''),
    ('<a class="user-panel-link" href="{% url \'password_change\' %}">', '<a class="menu-item" href="{% url \'password_change\' %}">'),
    ('<button type="submit" class="user-panel-link">Sign out</button>', '<button type="submit" class="menu-item">Sign out</button>'),
])

# ---- TypeScript: one behaviour for every popup menu
edit('frontend/shell.ts', [
    ('''// User menu
const userToggle = required<HTMLButtonElement>(document, '[data-user-toggle]');
const userPanel = required<HTMLElement>(document, '#user-panel');

function setUserOpen(open: boolean): void {
  userPanel.hidden = !open;
  userToggle.setAttribute('aria-expanded', String(open));
}

userToggle.addEventListener('click', (event) => {
  event.stopPropagation();
  setUserOpen(userPanel.hidden);
});
document.addEventListener('click', (event) => {
  if (!userPanel.hidden && !userPanel.contains(event.target as Node)) setUserOpen(false);
});

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  if (!userPanel.hidden) {
    setUserOpen(false);
    userToggle.focus();
  }
  if (root.hasAttribute('data-nav-open-mobile')) {''', '''// Popup menus (the panel switcher, the user menu): [data-menu] holds a [data-menu-toggle] button and a
// [data-menu-panel]. One is open at a time; a click outside or Esc closes it.
interface PopupMenu {
  toggle: HTMLButtonElement;
  panel: HTMLElement;
}

const menus: PopupMenu[] = [...document.querySelectorAll<HTMLElement>('[data-menu]')].map((menu) => ({
  toggle: required<HTMLButtonElement>(menu, '[data-menu-toggle]'),
  panel: required<HTMLElement>(menu, '[data-menu-panel]'),
}));

function setMenuOpen(menu: PopupMenu, open: boolean): void {
  menu.panel.hidden = !open;
  menu.toggle.setAttribute('aria-expanded', String(open));
}

function closeMenus(except?: PopupMenu): PopupMenu | undefined {
  let closed: PopupMenu | undefined;
  for (const menu of menus) {
    if (menu !== except && !menu.panel.hidden) {
      setMenuOpen(menu, false);
      closed = menu;
    }
  }
  return closed;
}

for (const menu of menus) {
  menu.toggle.addEventListener('click', (event) => {
    event.stopPropagation();
    closeMenus(menu);
    setMenuOpen(menu, menu.panel.hidden);
  });
}
document.addEventListener('click', (event) => {
  for (const menu of menus) {
    if (!menu.panel.hidden && !menu.panel.contains(event.target as Node)) setMenuOpen(menu, false);
  }
});

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  closeMenus()?.toggle.focus();
  if (root.hasAttribute('data-nav-open-mobile')) {'''),
])

# ---- CSS: shared menu parts, the switcher in the rail head
s = rd('static/css/app.css')
i = s.index('.user-panel {')
j = s.index('/* Content */')
s = s[:i] + '''.menu { position: relative; flex: none; }

.menu-panel {
  position: absolute;
  top: calc(100% + 10px);
  left: 0;
  z-index: 60;
  width: min(300px, calc(100vw - 32px));
  padding: .5rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--white);
  box-shadow: 0 12px 32px rgba(35, 41, 32, .18);
}
.menu-panel-right { left: auto; right: 0; }
.menu-panel[hidden] { display: none; }
.menu-panel form { margin: 0; }

.menu-head {
  display: flex;
  flex-direction: column;
  margin: 0 0 .375rem;
  padding: .5rem .75rem .75rem;
  border-bottom: 1px solid var(--line);
}
.menu-head span { color: var(--muted); font-size: .875rem; overflow-wrap: anywhere; }

.menu-item {
  display: block;
  width: 100%;
  padding: .625rem .75rem;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--speck);
  font: inherit;
  text-align: left;
  text-decoration: none;
  cursor: pointer;
}
.menu-item:hover { background: var(--hover); color: var(--speck); }
.menu-item[aria-current="true"] { background: var(--active-bg); color: var(--stripe-dark); font-weight: 600; }

''' + s[j:]
# the rail head: the switcher replaces the plain brand
a = s.index('.rail-brand {'); b = s.index('.logo-plate {')
s = s[:a] + '''.workspace-menu { flex: 1; min-width: 0; }

.workspace-trigger {
  display: flex;
  align-items: center;
  gap: .75rem;
  width: 100%;
  min-width: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--speck);
  font: inherit;
  text-align: left;
  text-decoration: none;
  cursor: pointer;
}
.workspace-trigger .icon { width: 18px; height: 18px; flex: none; margin-left: auto; color: var(--muted); }
.workspace-trigger:hover .workspace-name { color: var(--stripe-dark); }

.workspace-text { display: flex; flex-direction: column; min-width: 0; line-height: 1.15; }
.workspace-brand { color: var(--muted); font-size: .8125rem; font-weight: 500; }
.workspace-name { overflow: hidden; font-size: 1.25rem; font-weight: 700; white-space: nowrap; text-overflow: ellipsis; }

''' + s[b:]
a = s.index('.rail-brand-text {'); b = s.index('.rail-nav {')
s = s[:a] + s[b:]
s = s.replace('[data-nav="collapsed"] .rail-brand { flex: none; }\n[data-nav="collapsed"] .rail-brand-text { display: none; }\n',
              '[data-nav="collapsed"] .workspace-menu { flex: none; }\n[data-nav="collapsed"] .workspace-text,\n[data-nav="collapsed"] .workspace-trigger .icon { display: none; }\n')
s = s.replace('  [data-nav="collapsed"] .rail-brand { flex: 1; }\n  [data-nav="collapsed"] .rail-brand-text { display: block; }\n',
              '  [data-nav="collapsed"] .workspace-menu { flex: 1; }\n  [data-nav="collapsed"] .workspace-text { display: flex; }\n  [data-nav="collapsed"] .workspace-trigger .icon { display: block; }\n')
assert 'rail-brand' not in s and 'user-panel' not in s
wr('static/css/app.css', s)

# ---- groups and access areas follow the panels
edit('config/access.py', [
    ("Area('Facility', 'Sites', 'farm.Site'),", "Area('Company · Facility', 'Sites', 'farm.Site'),"),
    ("Area('Facility', 'Production departments', 'farm.ProductionDepartment'),", "Area('Production · Facility structure', 'Production departments', 'farm.ProductionDepartment'),"),
    ("Area('Facility', 'Systems', 'farm.System'),", "Area('Production · Facility structure', 'Systems', 'farm.System'),"),
    ("Area('Administration', 'Activity log', 'core.AuditLog', actions=('view',)),", "Area('Company · Administration', 'Activity log', 'core.AuditLog', actions=('view',)),"),
])
edit('farm/resources/production_department.py', [("'production departments', 'Facility'", "'production departments', 'Facility structure'")])
edit('farm/resources/system.py', [("'systems', 'Facility'", "'systems', 'Facility structure'")])
edit('core/tests.py', [("from django.utils.module_loading import import_string\n", "")])
print('ui done')
