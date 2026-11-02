from core.navigation import Entry, Group, Workspace

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
