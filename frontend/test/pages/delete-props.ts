// A delete confirmation's props as core.formpayload.delete_payload writes them, blocked and not, for the delete
// confirmation's tests (unit and browser). Plainly invented names. Test code only.
const BASE = {
  action: '/hr/settings/leave-types/7/delete/', cancel: '/hr/settings/leave-types/', cancelLabel: 'Cancel', csrfToken: 'test-token',
  question: 'Delete “Test annual leave”?', heading: 'Delete leave type', submit: 'Delete leave type',
  outcome: 'It disappears from every list but is not erased: the record stays in the database, the activity log keeps its history, and it can be restored from the admin.',
};

export const BLOCKED_PROPS = {
  ...BASE, canDelete: false,
  blocked: { title: 'This leave type cannot be deleted yet.', reasons: ['2 leave requests use it.'] },
  groups: [{ kind: 'unlinked', count: 2, records: ['Test Person 01.12.2026', 'Test Second 03.12.2026'], title: 'Leave requests linked to it',
    note: 'They keep the link, but it does not count while this is deleted; restoring it brings the link back.' }],
};

export const OPEN_PROPS = {
  ...BASE, canDelete: true, blocked: null,
  groups: [{ kind: 'kept', count: 3, records: [], title: 'Holidays kept with it', note: 'They are kept as they are.' }],
};
