// A list page's props as core/listprops.py writes them, for the list page's tests (unit and browser). The names are the
// test world's fixtures. Test code only.
export const LIST_PROPS = {
  csrfToken: 'test-token',
  tabs: { label: 'Status', tabs: [
    { href: '?tab=pending', label: 'Pending', count: '2', current: true },
    { href: '?tab=all', label: 'All', count: '3', current: false },
  ] },
  toolbar: {
    label: 'Search employees',
    search: { name: 'q', value: 'Alfa', label: 'Search employees', placeholder: 'Search by name or number' },
    keep: [{ name: 'tab', value: 'pending' }],
    filters: [
      { name: 'department', label: 'Department', value: '', options: [{ value: '', label: 'All departments' }],
        groups: [{ label: 'Production departments', options: [{ value: 'p:1', label: 'Hatchery A' }] }] },
      { name: 'status', label: 'Status', value: 'current', options: [
        { value: '', label: 'Any status' }, { value: 'current', label: 'Working here' }, { value: 'left', label: 'Left' }] },
    ],
    submit: 'Filter',
    add: { href: '/hr/team/new/', label: 'Add employee' },
  },
  notices: [{ key: 'n1', tone: 'warning' as const, text: 'Two people have no department.' }],
  lines: ['Showing 2 of 3 employees.'],
  table: {
    label: 'Team',
    actionsLabel: 'Actions',
    columns: [{ key: 'employee', label: 'Employee' }, { key: 'department', label: 'Department' },
      { key: 'days', label: 'Days', numeric: true }, { key: 'status', label: 'Status' }],
    rows: [
      { key: '1', status: null, voided: false, cells: {
        employee: { text: 'Ann Alfa', href: '/hr/team/1/', strong: true, chip: null, chips: [], sub: ['E-1'] },
        department: { text: 'Hatchery A', href: null, strong: false, chip: null, chips: [], sub: [] },
        days: { text: '3', href: null, strong: false, chip: null, chips: [], sub: [] },
        status: { text: null, href: null, strong: false, chip: { kind: 'ok' as const, text: 'Working here' }, chips: [], sub: [] },
      }, actions: [
        { kind: 'link' as const, href: '/hr/team/1/view/', label: 'Show Ann Alfa', icon: 'search' as const, danger: false },
        { kind: 'post' as const, href: '/hr/leave/1/cancel/', label: 'Cancel the request', icon: 'calendar-off' as const,
          danger: true, fields: [{ name: 'next', value: '/hr/leave/' }] },
      ] },
      { key: '2', status: 'warning' as const, voided: false, cells: {
        employee: { text: 'Bob Bravo', href: '/hr/team/2/', strong: true, chip: null, chips: [], sub: ['E-2'] },
        department: { text: null, href: null, strong: false, chip: { kind: 'warning' as const, text: 'Not placed' }, chips: [], sub: [] },
        days: { text: '0.5', href: null, strong: false, chip: null, chips: [], sub: [] },
        status: { text: null, href: null, strong: false, chip: { kind: 'neutral' as const, text: 'Left 31.01.2026' }, chips: [], sub: [] },
      }, actions: [] },
    ],
  },
  empty: { title: 'No employees match “Zed”', text: 'Try another search.', link: { href: '/hr/team/', label: 'Show all employees' }, add: null },
  pager: { label: 'Pages', range: '51–100 of 120', page: 'Page 2 of 3',
    previous: { href: '?q=Alfa&page=1', label: 'Previous' }, next: { href: '?q=Alfa&page=3', label: 'Next' } },
};
