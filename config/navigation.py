from django.utils.translation import gettext_lazy as _

from core.navigation import Entry, Group, Section, Workspace

# The panels of the console, switched from the top left. Company holds what belongs to the company
# as a whole (every signed-in person has it); Production holds the farm's production side and is
# offered to people who can use something in it. Each has its own overview. The HR pages will join
# Company.
#
# Production's menu has two main headings, as in the platform: Setup (the farm's structure, its
# reference lists and its suppliers, entered once and changed seldom) and Operations (the daily
# production records: stocking, feeding, water chemistry, health, harvest), from Production units on.
#
# Where an entry sits here is also where the role matrix and the tab's page heading place it.
WORKSPACES = [
    Workspace('company', _('Company'), always=True, sections=[
        Section('', [
            Group('', [Entry(_('Overview'), 'home', 'home')]),
            Group(_('Facility'), [Entry(_('Sites'), 'farm:site_list', 'building', 'farm.view_site')]),
            Group(_('Administration'), [
                Entry(_('Activity log'), 'core:activity_log', 'history', 'core.view_auditlog'),
                Entry(_('Roles'), 'core:group_list', 'shield', 'auth.view_group'),
                Entry(_('Users'), 'core:user_list', 'users', 'auth.view_user'),
                Entry(_('Database'), 'core:database', 'database', 'core.browse_database'),
            ]),
        ]),
    ]),
    Workspace('production', _('Production'), sections=[
        Section('', [Group('', [Entry(_('Overview'), 'production_home', 'home')])]),
        Section(_('Setup'), [
            Group(_('Facility structure'), [
                Entry(_('Production departments'), 'farm:productiondepartment_list', 'layout-grid',
                      'farm.view_productiondepartment'),
                Entry(_('Systems'), 'farm:system_list', 'waves', 'farm.view_system'),
                Entry(_('Equipment'), 'farm:equipment_list', 'wrench', 'farm.view_equipment'),
                Entry(_('Tanks, ponds & cages'), 'farm:tank_list', 'cylinder', 'farm.view_tank'),
            ]),
            # The reference lists the production side picks from: species and feeds now; water parameters,
            # chemicals, fish-health substances and slaughter facilities as their tabs arrive.
            Group(_('Reference data'), [
                Entry(_('Species'), 'farm:species_list', 'fish', 'farm.view_species'),
                Entry(_('Feeds'), 'farm:feed_list', 'wheat', 'farm.view_feed'),
            ]),
            # Who the farm buys from: goods, live fish and services. Purchase orders join it later.
            Group(_('Purchasing'), [
                Entry(_('Suppliers'), 'farm:supplier_list', 'truck', 'farm.view_supplier'),
            ]),
        ]),
        # The daily production records: the fish in each unit and what happens to them; feeding, water
        # chemistry, health and harvest join as their tabs arrive.
        Section(_('Operations'), [
            Group('', [
                Entry(_('Production units'), 'farm:production_units', 'layers', 'farm.view_stockoperation'),
            ]),
        ]),
    ]),
]
