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


edit('config/views.py', [
    ('from django.shortcuts import render\n\nfrom farm.models', 'from django.shortcuts import render\nfrom django.urls import reverse\n\nfrom farm.models'),
    ('    from django.urls import reverse\n', ''),
    ("            {'label': label, 'count': System.objects.filter(status=value).count()}",
     "            {'value': value, 'label': label, 'count': System.objects.filter(status=value).count()}"),
])
edit('templates/production_home.html', [("badge-{{ item.value|default:'' }}", 'badge-{{ item.value }}')])

s = rd('static/css/components.css').rstrip('\n')
s += '''

/* Overview pages: counts that link to their list, and a breakdown */
.tiles { display: flex; flex-wrap: wrap; gap: 1rem; margin: 0 0 1.5rem; padding: 0; list-style: none; }
.tile {
  display: flex;
  flex-direction: column;
  min-width: 11rem;
  padding: 1rem 1.25rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--white);
  color: var(--speck);
  text-decoration: none;
}
.tile:hover { border-color: var(--stripe); }
.tile-count { font-size: 2rem; font-weight: 700; line-height: 1.1; font-variant-numeric: tabular-nums; }
.tile-label { color: var(--muted); font-size: .9375rem; }

.overview-block { margin: 0 0 1.5rem; }
.overview-block h2 { margin: 0 0 .5rem; font-size: 1.125rem; }
.status-list { display: flex; flex-wrap: wrap; gap: .75rem 1.5rem; margin: 0; padding: 0; list-style: none; }
.status-list li { display: flex; align-items: center; gap: .5rem; }
'''
wr('static/css/components.css', s + '\n')

# ---- tests follow the two overviews and the panel rule
t = rd('core/tests_workspaces.py')
reps = [
    ("        self.assertEqual(self.labels(production), ['Production departments', 'Systems'])",
     "        self.assertEqual(self.labels(production), ['Overview', 'Production departments', 'Systems'])"),
    ("        self.assertEqual(panels, {'company': reverse('home'), 'production': reverse('farm:productiondepartment_list')})",
     "        self.assertEqual(panels, {'company': reverse('home'), 'production': reverse('production_home')})"),
    ("                         {'company': reverse('home'), 'production': reverse('farm:system_list')})",
     "                         {'company': reverse('home'), 'production': reverse('production_home')})"),
    ("        self.assertEqual(self.labels(response), ['Production departments', 'Systems'])\n        self.page(reverse('farm:site_list'))",
     "        self.assertEqual(self.labels(response), ['Overview', 'Production departments', 'Systems'])\n        self.page(reverse('farm:site_list'))"),
    ("        self.assertEqual(self.labels(self.page(reverse('home'))), ['Overview'])    # everyone has the overview\n        response = self.page(reverse('farm:system_list'))\n        self.assertEqual(response.context['workspace']['key'], 'production')\n        self.assertEqual(self.labels(response), ['Systems'])",
     "        self.assertEqual(self.labels(self.page(reverse('home'))), ['Overview'])    # everyone has the company overview\n        response = self.page(reverse('farm:system_list'))\n        self.assertEqual(response.context['workspace']['key'], 'production')\n        self.assertEqual(self.labels(response), ['Overview', 'Systems'])"),
    ("        self.assertEqual(navigation.workspace_of(reverse('farm:site_list')), 'company')\n",
     "        self.assertEqual(navigation.workspace_of(reverse('farm:site_list')), 'company')\n        self.assertEqual(navigation.workspace_of(reverse('production_home')), 'production')\n"),
]
for a, b in reps:
    assert a in t, a[:60]
    t = t.replace(a, b)
t = t.rstrip('\n') + '''


class OverviewTests(WorkspaceTestCase):
    def test_each_panel_has_its_own_overview(self):
        self.sign_in(self.admin)
        company, production = self.page(reverse('home')), self.page(reverse('production_home'))
        self.assertEqual((company.context['workspace']['key'], production.context['workspace']['key']),
                         ('company', 'production'))
        self.assertContains(company, 'Company overview')
        self.assertContains(production, 'Production overview')

    def test_the_overviews_show_the_counts_of_what_the_person_may_see(self):
        from farm.models import ProductionDepartment, Site, System
        site = Site.objects.create(name='Bergen', code='BG')
        ProductionDepartment.objects.create(site=site, name='Hall', code='HA')
        System.objects.create(site=site, name='RAS', code='R1')
        System.objects.create(site=site, name='Pond', code='P1', status='maintenance')
        self.sign_in(self.admin)
        self.assertEqual([(t['label'], t['count']) for t in self.page(reverse('home')).context['tiles']], [('Sites', 1)])
        production = self.page(reverse('production_home'))
        self.assertEqual([(t['label'], t['count']) for t in production.context['tiles']],
                         [('Production departments', 1), ('Systems', 2)])
        by_status = {item['value']: item['count'] for item in production.context['systems_by_status']}
        self.assertEqual((by_status['operational'], by_status['maintenance'], by_status['offline']), (1, 1, 0))

    def test_tiles_and_breakdown_are_left_out_for_what_the_person_may_not_see(self):
        self.user.groups.add(role('Systems only', 'view_system'))
        self.sign_in(self.user)
        self.assertEqual(self.page(reverse('home')).context['tiles'], [])
        production = self.page(reverse('production_home'))
        self.assertEqual([t['label'] for t in production.context['tiles']], ['Systems'])
        self.user.groups.clear()
        self.assertEqual(self.page(reverse('production_home')).context['systems_by_status'], [])
'''
wr('core/tests_workspaces.py', t + '\n')
print('ok')
