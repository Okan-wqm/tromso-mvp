from django.utils.translation import gettext_lazy as _

from core.navigation import Entry, Group, Section, Workspace

# The panels of the console, switched from the top left. Company holds what belongs to the company
# as a whole (every signed-in person has it); Production holds the farm's production side and is
# offered to people who can use something in it. Each has its own overview. Company also holds the
# knowledge (the library and the knowledge entries); the HR pages will join it.
#
# Production's menu has two main headings, as in the platform: Setup (the farm's structure, its
# reference lists and its suppliers, entered once and changed seldom) and Operations (the daily
# production records: stocking, feeding, water chemistry, health, harvest), from Production units on.
# A third, Communication, holds how the people running production talk to each other: Messages.
#
# Where an entry sits here is also where the role matrix and the tab's page heading place it.
WORKSPACES = [
    Workspace('company', _('Company'), always=True, sections=[
        Section('', [
            Group('', [Entry(_('Overview'), 'home', 'home')]),
            Group(_('Facility'), [Entry(_('Sites'), 'farm:site_list', 'building', 'farm.view_site')]),
            # What the company knows: the documents of its library and the knowledge taken from them, which AI
            # agents will watch the farm with. It belongs to the organisation, not only to production.
            Group(_('Knowledge'), [
                Entry(_('Library'), 'knowledge:document_list', 'book-open', 'knowledge.view_document'),
                Entry(_('Knowledge entries'), 'knowledge:knowledgeentry_list', 'lightbulb',
                      'knowledge.view_knowledgeentry'),
            ]),
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
            # The reference lists the production side picks from: species, feeds and the water limits per species
            # now; chemicals, fish-health substances and slaughter facilities as their tabs arrive.
            Group(_('Reference data'), [
                Entry(_('Species'), 'farm:species_list', 'fish', 'farm.view_species'),
                Entry(_('Feeds'), 'farm:feed_list', 'wheat', 'farm.view_feed'),
                Entry(_('Water limits'), 'farm:waterlimit_list', 'gauge', 'farm.view_waterlimit'),
            ]),
            # Who the farm buys from: goods, live fish and services. Purchase orders join it later.
            Group(_('Purchasing'), [
                Entry(_('Suppliers'), 'farm:supplier_list', 'truck', 'farm.view_supplier'),
            ]),
        ]),
        # The daily production records: the fish in each unit and what happens to them, the water they are in and
        # their feeding; health and harvest join as their tabs arrive. Feeding has four pages: today's meals per
        # unit, what was fed against the ration, the feeding tables and where each applies.
        Section(_('Operations'), [
            Group('', [
                Entry(_('Production units'), 'farm:production_units', 'layers', 'farm.view_stockoperation'),
                Entry(_('Water chemistry'), 'farm:water', 'droplet', 'farm.view_watermeasurement'),
            ]),
            Group(_('Feeding'), [
                Entry(_('Meal board'), 'farm:meal_board', 'utensils', 'farm.view_feedingrecord'),
                Entry(_('Records'), 'farm:feeding_records', 'clipboard-list', 'farm.view_feedingrecord'),
                Entry(_('Protocols'), 'farm:feedingprotocol_list', 'table', 'farm.view_feedingprotocol'),
                Entry(_('Assignments'), 'farm:protocolassignment_list', 'link', 'farm.view_protocolassignment'),
            ]),
        ]),
        # Messages between the people running production, direct and in channels; their AI assistants join the
        # same conversations later (README, Messages). Neither structure nor a production record: a heading of
        # its own. The number beside it is the person's unread messages.
        Section(_('Communication'), [
            Group('', [
                Entry(_('Messages'), 'messaging:inbox', 'message-square', 'messaging.view_conversation',
                      badge='messaging.read.unread_badge'),
            ]),
        ]),
    ]),
]
