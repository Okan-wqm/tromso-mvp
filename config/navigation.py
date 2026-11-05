from django.utils.translation import gettext_lazy as _, pgettext_lazy

from core.navigation import Entry, Group, Section, Workspace

# Menu courtesies (hr.scope): which HR lines a person is shown, never what they may open.
NOT_PRODUCTION_ONLY = 'hr.scope.not_production_only'
LEADS = 'hr.scope.leads'

# The panels of the console, switched from the top left. Company holds what belongs to the company
# as a whole (every signed-in person has it); Production holds the farm's production side and is
# offered to people who can use something in it. Each has its own overview. Company also holds the
# knowledge (the library and the knowledge entries); the HR pages will join it.
#
# Production's menu has two main headings, as in the platform: Setup (the farm's structure, its
# reference lists and its suppliers, entered once and changed seldom) and Operations (the daily
# production records: stocking, feeding, water chemistry, health, harvest), from Production units on.
# A third, Reports, holds what is told to the authorities from those records; a fourth, Communication,
# how the people running production talk to each other: Messages.
#
# Where an entry sits here is also where the role matrix and the tab's page heading place it.
WORKSPACES = [
    Workspace('company', _('Company'), always=True, sections=[
        Section('', [
            Group('', [Entry(_('Overview'), 'home', 'home')]),
            Group(_('Facility'), [
                Entry(_('Sites'), 'farm:site_list', 'building', 'farm.view_site'),
                # Where stock is kept on each site: feed stores, silos, cold rooms, medicine cabinets.
                Entry(_('Storage locations'), 'inventory:storagelocation_list', 'warehouse',
                      'inventory.view_storagelocation'),
            ]),
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
        # The company's office people: who they are, where they work and their time (the production people are under
        # Production › Team: the same records, split by where a person is placed, hr.scope). A team lead reads and plans only
        # their own team. A person whose HR is all in Production is not shown the lines Production › Team repeats (`show_when`,
        # a menu courtesy, never a permission).
        Section(_('HR'), [
            Group(_('HR dashboard'), [
                Entry(_('Today & attendance'), 'hr:today', 'user-check', 'hr.view_attendancerecord',
                      show_when=NOT_PRODUCTION_ONLY),
                Entry(_('Team list'), 'hr:employee_list', 'users', 'hr.view_employee',
                      show_when=NOT_PRODUCTION_ONLY),
                Entry(_('Departments'), 'hr:officedepartment_list', 'layout-grid', 'hr.view_officedepartment'),
                Entry(_('Organization chart'), 'hr:orgchart', 'network', 'hr.view_officedepartment',
                      show_when=NOT_PRODUCTION_ONLY),
            ]),
            Group(_('Time & shifts'), [
                Entry(_('Shift schedule'), 'hr:shiftassignment_list', 'calendar', 'hr.view_shiftassignment',
                      show_when=NOT_PRODUCTION_ONLY),
                Entry(_('Team overview'), 'hr:overview', 'users', 'hr.view_shiftassignment',
                      show_when=NOT_PRODUCTION_ONLY),
                Entry(_('Attendance'), 'hr:attendancerecord_list', 'user-check', 'hr.view_attendancerecord',
                      show_when=NOT_PRODUCTION_ONLY),
                Entry(_('Leave requests'), 'hr:leaverequest_list', 'calendar-off', 'hr.view_leaverequest',
                      show_when=NOT_PRODUCTION_ONLY),
                Entry(_('Scheduling settings'), 'hr:schedulingsettings_list', 'settings', 'hr.view_schedulingsettings'),
                # Reached from Scheduling settings: no line in the menu, still in the role matrix.
                Entry(_('Shifts'), 'hr:shift_list', 'timer', 'hr.view_shift', hidden=True),
                Entry(_('Holidays'), 'hr:holiday_list', 'calendar', 'hr.view_holiday', hidden=True),
                Entry(_('Leave types'), 'hr:leavetype_list', 'calendar-off', 'hr.view_leavetype', hidden=True),
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
                # The named wall screens of Operations › Monitoring: which units, how each card is drawn.
                Entry(_('Monitoring boards'), 'monitoring:monitorboard_list', 'monitor', 'monitoring.view_monitorboard'),
                # Where in the water a sample is taken: a place on a unit, a loop or a piece of equipment.
                Entry(_('Sampling points'), 'farm:samplingpoint_list', 'droplet', 'farm.view_samplingpoint'),
            ]),
            # The reference lists the production side picks from: species, feeds, the water limits per species,
            # the medicines with their withdrawal and the fast before fish are handled (harvest, transport,
            # grading, treatment); chemicals as their tab arrives.
            Group(_('Reference data'), [
                Entry(_('Species'), 'farm:species_list', 'fish', 'farm.view_species'),
                Entry(_('Feeds'), 'farm:feed_list', 'wheat', 'farm.view_feed'),
                Entry(_('Water limits'), 'farm:waterlimit_list', 'gauge', 'farm.view_waterlimit'),
                Entry(_('Medicines'), 'farm:medicine_list', 'pill', 'farm.view_medicine'),
                Entry(_('Handling rules'), 'farm:handlingrule_list', 'timer', 'farm.view_handlingrule'),
            ]),
            # Harvest and logistics: the outside facilities harvested fish go to; wellboats join it when they get
            # records of their own.
            Group(_('Harvest and logistics'), [
                Entry(_('Slaughter facilities'), 'farm:slaughterfacility_list', 'factory',
                      'farm.view_slaughterfacility'),
            ]),
            # Who the farm buys from: goods, live fish and services. Purchase orders join it later.
            Group(_('Purchasing'), [
                Entry(_('Suppliers'), 'farm:supplier_list', 'truck', 'farm.view_supplier'),
            ]),
        ]),
        # The daily production records: the fish in each unit and what happens to them, the water they are in,
        # their feeding, their harvest and their health. Feeding has four pages: today's meals per unit, what was
        # fed against the ration, the feeding tables and where each applies. Harvest has three: what was harvested,
        # what is planned, and the target weight per batch.
        Section(_('Operations'), [
            Group('', [
                Entry(_('Production units'), 'farm:production_units', 'layers', 'farm.view_stockoperation'),
                # A live card per unit for the control room's wall, from the same records (the page needs the same right).
                Entry(_('Monitoring'), 'monitoring:monitor', 'monitor', 'farm.view_stockoperation'),
                Entry(_('Water chemistry'), 'farm:water', 'droplet', 'farm.view_watermeasurement'),
                # The store: what is on hand where, deliveries, moves, write-offs and counts; the feed fed is read
                # from the feeding records.
                Entry(_('Storage'), 'inventory:storage', 'package', 'inventory.view_inventoryoperation'),
                # The farm's jobs, each at one place for its people, and the recurring tasks that plan them.
                Entry(_('Tasks'), 'tasks:task_list', 'list-checks', 'tasks.view_task'),
                Entry(_('Recurring tasks'), 'tasks:taskseries_list', 'repeat', 'tasks.view_taskseries'),
            ]),
            Group(_('Feeding'), [
                Entry(_('Meal board'), 'farm:meal_board', 'utensils', 'farm.view_feedingrecord'),
                Entry(_('Records'), 'farm:feeding_records', 'clipboard-list', 'farm.view_feedingrecord'),
                Entry(_('Protocols'), 'farm:feedingprotocol_list', 'table', 'farm.view_feedingprotocol'),
                Entry(_('Assignments'), 'farm:protocolassignment_list', 'link', 'farm.view_protocolassignment'),
            ]),
            Group(_('Harvest'), [
                Entry(pgettext_lazy('page', 'Harvested'), 'farm:harvests', 'package-check', 'farm.view_harvestrecord'),
                Entry(_('Harvest plan'), 'farm:handlingplanitem_list', 'calendar', 'farm.view_handlingplanitem'),
                Entry(_('Production plans'), 'farm:productionplan_list', 'target', 'farm.view_productionplan'),
            ]),
            # The fish's health: what was given them, what was seen and found, and the sea lice counted.
            Group(_('Health'), [
                Entry(_('Treatments'), 'farm:treatments', 'syringe', 'farm.view_treatment'),
                Entry(_('Health events'), 'farm:healthevent_list', 'stethoscope', 'farm.view_healthevent'),
                Entry(_('Sea-lice counts'), 'farm:lice_counts', 'bug', 'farm.view_licecount'),
            ]),
        ]),
        # Research: trials of one species on one site, with their design, their tanks and the days. It reads the farm
        # and nothing reads it (README, Experiments).
        Section(_('Research'), [
            Group('', [
                Entry(_('Experiments'), 'experiments:experiment_list', 'flask', 'experiments.view_experiment'),
            ]),
        ]),
        # What the farm tells the authorities, computed from the records above and filed by people: neither structure
        # nor a daily record, so a heading of its own (docs/regulatory-reports.md, 5.6).
        Section(_('Reports'), [
            Group('', [
                Entry(_('Regulatory reports'), 'reports:report_list', 'file-text', 'reports.view_report'),
                Entry(_('Questions for the authority'), 'reports:openquestion_list', 'list-checks',
                      'reports.view_openquestion'),
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
        # The production people: the HR pages of Company › HR served again for the people placed in a production
        # department (core.crud.Mount, hr.scope's realm): the same records, rules and log, one set. Last, so the other
        # branches' sections above it stay where they are. Attendance is read with the same right as Today, so a Today
        # reader has it too. Team overview is shown to the people who lead production (a menu courtesy). The number beside
        # Leave requests is the pending requests the person may decide.
        Section(_('Team'), [
            Group(_('Time & attendance'), [
                Entry(_('Today & attendance'), 'hr:production_today', 'user-check', 'hr.view_attendancerecord'),
                Entry(_('Shift schedule'), 'hr:production_shiftassignment_list', 'calendar', 'hr.view_shiftassignment'),
                Entry(_('Leave requests'), 'hr:production_leaverequest_list', 'calendar-off', 'hr.view_leaverequest',
                      badge='hr.read.pending_leave_badge'),
                Entry(_('Attendance'), 'hr:production_attendancerecord_list', 'user-check', 'hr.view_attendancerecord'),
                Entry(_('Team overview'), 'hr:production_overview', 'users', 'hr.view_shiftassignment', show_when=LEADS),
            ]),
            Group(_('People'), [
                Entry(_('Team list'), 'hr:production_employee_list', 'users', 'hr.view_employee'),
                Entry(_('Organization chart'), 'hr:production_orgchart', 'network', 'hr.view_employee'),
            ]),
        ]),
    ]),
]
