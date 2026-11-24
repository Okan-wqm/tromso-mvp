// A roster's props as hr.resources.roster.list_next_props writes them, for the roster grid's tests (unit and browser). The
// names are plainly invented. Test code only.
const cell = (key: string | null, extra: Record<string, unknown> = {}) => ({ key, chip: null, href: null, add: null, holiday: null, finding: null, blocks: false, ...extra });

export const ROSTER_PROPS = {
  label: 'Shift schedule',
  employeeHead: 'Employee',
  hoursHead: 'Planned (h)',
  days: [
    { key: '2026-11-23', head: 'Mon 23.11.2026', sub: '' },
    { key: '2026-11-24', head: 'Tue 24.11.2026', sub: '' },
    { key: '2026-11-25', head: 'Wed 25 Nov', sub: '' },
  ],
  rows: [
    { key: '1', name: 'Test Person', sub: 'Test Hall A', hours: '15', hoursFinding: null, cells: [
      cell('1:2026-11-23', { chip: { kind: 'shift' as const, text: 'TD', title: 'Test day shift 07:00–15:00', tone: 1 }, href: '/hr/schedule/7/' }),
      cell('1:2026-11-24', { add: { href: '/hr/schedule/new/?employee=1&day=2026-11-24', label: 'Plan this day' } }),
      cell('1:2026-11-25', { chip: { kind: 'off' as const, text: 'Off', title: null }, href: '/hr/schedule/8/', holiday: 'Test holiday' }),
    ] },
    { key: '2', name: 'Test Second', sub: 'Not placed', hours: '45', hoursFinding: 'More than the standard week', cells: [
      cell(null),
      cell('2:2026-11-24', { chip: { kind: 'shift' as const, text: 'TN', title: 'Test night shift 22:00–06:00', tone: 4 }, href: '/hr/schedule/9/',
        finding: 'Less than 11 h of rest before this shift.', blocks: true }),
      cell('2:2026-11-25', { chip: { kind: 'leave' as const, text: 'On leave', title: 'TD planned: to be covered' } }),
    ] },
  ],
  paint: {
    action: '/hr/schedule/plan/', csrfToken: 'test-token', next: '/hr/schedule/?week=2026-11-23', label: 'Paint',
    choices: [{ value: '5', label: 'TD', title: 'Test day shift', kind: 'shift' as const, tone: 1 }, { value: 'off', label: 'Off', title: null, kind: 'off' as const },
      { value: 'clear', label: 'Clear', title: null, kind: 'clear' as const }],
    clearSelection: 'Clear selection', apply: 'Apply to the selected days',
  },
};
