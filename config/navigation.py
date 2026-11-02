from core.navigation import Entry, Group

MENU = [
    Group('', [Entry('Overview', 'home', 'home')]),
    Group('Facility', [
        Entry('Sites', 'farm:site_list', 'building', 'farm.view_site'),
        Entry('Departments', 'farm:department_list', 'layout-grid', 'farm.view_department'),
    ]),
    Group('Administration', [
        Entry('Activity log', 'core:activity_log', 'history', 'core.view_auditlog'),
        Entry('Roles', 'core:group_list', 'shield', 'auth.view_group'),
        Entry('Users', 'core:user_list', 'users', 'auth.view_user'),
    ]),
]
