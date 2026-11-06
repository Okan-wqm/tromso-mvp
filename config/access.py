from django.utils.translation import gettext_lazy as _, pgettext_lazy

from core.access import Area

# What the role form's permission matrix offers, one line per area (core.access). The matrix groups
# the areas the way the menu (config/navigation.py) places their pages.
AREAS = [
    Area(_('Sites'), 'farm.Site'),
    Area(_('Storage locations'), 'inventory.StorageLocation'),
    Area(_('Production departments'), 'farm.ProductionDepartment'),
    Area(_('Systems'), 'farm.System'),
    Area(_('Equipment'), 'farm.Equipment'),
    Area(_('Tanks, ponds & cages'), 'farm.Tank'),
    # The named wall screens of Operations › Monitoring. Anyone who may read Monitoring may choose a board: a board is
    # configuration, so these rights are for making and changing them.
    Area(_('Monitoring boards'), 'monitoring.MonitorBoard'),
    # Where a sample is taken: the points of a unit, a loop or a piece of equipment (the samples are Water chemistry).
    Area(_('Sampling points'), 'farm.SamplingPoint'),
    Area(_('Species'), 'farm.Species'),
    Area(_('Feeds'), 'farm.Feed'),
    Area(_('Water limits'), 'farm.WaterLimit'),
    Area(_('Medicines'), 'farm.Medicine'),
    Area(_('Slaughter facilities'), 'farm.SlaughterFacility'),
    Area(_('Handling rules'), 'farm.HandlingRule'),
    # What a monitoring card holds and which unit's card gets which. Reading Monitoring needs neither: a card never asks
    # for a template right.
    Area(_('Card templates'), 'monitoring.CardTemplate'),
    Area(_('Card template rules'), 'monitoring.CardTemplateAssignment'),
    Area(_('Suppliers'), 'farm.Supplier'),
    Area(_('Library'), 'knowledge.Document'),
    # Edit also reviews an entry (marks it reviewed, or takes it back to draft).
    Area(_('Knowledge entries'), 'knowledge.KnowledgeEntry'),
    # The stock: Read is the Production units page and Monitoring, Create records an operation (a stocking, a mortality,
    # a weighing), Delete voids one. Operations are never edited: a correction is a void and a new entry.
    Area(_('Production units'), 'farm.StockOperation', actions=('view', 'add', 'delete')),
    # The feeding records: Read is the Meal board and the Records page (and the feeding part of a unit's drawer),
    # Create records a feeding or a meal, Delete voids one. Records are never edited: a correction is a void and a
    # new entry.
    Area(_('Feeding records'), 'farm.FeedingRecord', actions=('view', 'add', 'delete')),
    # The feeding tables and where they apply (Operations › Feeding › Protocols and Assignments).
    Area(_('Feeding protocols'), 'farm.FeedingProtocol'),
    Area(_('Protocol assignments'), 'farm.ProtocolAssignment'),
    # Water samples: Read is the Water chemistry page (and a unit's water in the drawer), Create records a
    # sample or a round, Delete voids a sample. Samples are never edited: a correction is a void and a new entry.
    Area(_('Water chemistry'), 'farm.WaterMeasurement', actions=('view', 'add', 'delete')),
    # The store: Read is the Storage page, Create records a delivery, an issue, a write-off, a return, a transfer
    # or a count, Delete voids one. Operations are never edited: a correction is a void and a new entry.
    Area(_('Storage'), 'inventory.InventoryOperation', actions=('view', 'add', 'delete')),
    # The harvests: Read is the Harvested page. A harvest is recorded and voided as a stock operation (Production
    # units: Create and Delete), with where the fish went, so nothing else is offered here.
    Area(pgettext_lazy('page', 'Harvested'), 'farm.HarvestRecord', actions=('view',)),
    # The planned harvests and transports, and the target weight per batch: read, plan, change, delete.
    Area(_('Harvest plan'), 'farm.HandlingPlanItem'),
    Area(_('Production plans'), 'farm.ProductionPlan'),
    # Treatments: Read the list (and a unit's health in the drawer), Create records one, Edit changes its last
    # day (logged), Delete voids one, which lifts its withdrawal. Nothing else of a treatment is edited.
    Area(_('Treatments'), 'farm.Treatment'),
    # Health events: Read, Create, Edit on the event's form (logged), Delete voids one with its reason.
    Area(_('Health events'), 'farm.HealthEvent'),
    # Sea-lice counts: Read the page with the site's weekly averages, Create records a count, Delete voids one.
    Area(_('Sea-lice counts'), 'farm.LiceCount', actions=('view', 'add', 'delete')),
    # Regulatory reports: Read is the Reports page, a report and its exports; Create starts a report, a notice or a
    # correction; Edit fills in a draft and records that it was filed (a state change under Edit, as a review is for
    # knowledge entries); Delete discards a draft. A filed report is never changed or deleted.
    Area(_('Regulatory reports'), 'reports.Report'),
    # Questions for the authority: the register of what only Mattilsynet, Fiskeridirektoratet or the county can answer, which
    # the people who run the reports keep (Read, Create, Edit with the answer, Delete).
    Area(_('Questions for the authority'), 'reports.OpenQuestion'),
    # Messages: Read is the Messages page, writing in one's own conversations and starting a direct one; Create
    # also creates channels. Only the members of a conversation read it, whatever the role (messaging/services.py).
    Area(_('Messages'), 'messaging.Conversation', actions=('view', 'add')),
    # Tasks: Read is the Tasks page, a task's drawer and adding a note; a person a task is for may also start it,
    # tick its checklist and complete it. Edit also cancels and reopens any task and edits its checklist.
    Area(_('Tasks'), 'tasks.Task'),
    # Recurring tasks: the rules that plan tasks ahead; Create, Edit and Delete change the plan.
    Area(_('Recurring tasks'), 'tasks.TaskSeries'),
    # HR: the people (Everyone reads every employee, otherwise only the team: HR's row scope, hr/scope.py) and the
    # office departments (the production departments are the farm's own, edited under Production). All production reads every
    # person placed in a production department (Production › Team), a department without a manager too, and never an office
    # person or a leave reason: the head of production's reach.
    Area(_('Employees'), 'hr.Employee', actions=('view', 'add', 'change', 'all_production', 'all')),
    Area(_('Departments'), 'hr.OfficeDepartment'),
    # The shift patterns and the holidays the roster and the leave charge read, and the scheduling limits (one row: Edit
    # only). The three have no menu line of their own but Scheduling settings: it leads to the other two.
    Area(_('Shifts'), 'hr.Shift'),
    # The roster: Read is the Shift schedule (the viewer's team), Create plans a day, Edit changes a plan, Delete clears a
    # cell; the rules (rest, hours, leave) run on every save. Crew adds, under one's own week, the name and shift code and times
    # of the people in one's own production department that day: nothing else of theirs (hr.read.crew_week).
    Area(_('Shift schedule'), 'hr.ShiftAssignment', actions=('view', 'add', 'change', 'delete', 'crew')),
    # Attendance: Read is Today & attendance (the team's board, and clocking oneself in and out) and the Attendance page, Create
    # enters presence by hand (with a reason), Edit corrects a stretch (logged), Delete voids one.
    Area(_('Attendance'), 'hr.AttendanceRecord'),
    # Leave requests: Read is the team's requests, Create files one (for oneself or a person of the team), Edit also approves,
    # rejects and cancels (as a review is for knowledge entries), nobody deletes one: a wrong request is cancelled. Leave
    # types are the owner's list.
    Area(_('Leave requests'), 'hr.LeaveRequest', actions=('view', 'add', 'change')),
    Area(_('Leave types'), 'hr.LeaveType'),
    Area(_('Holidays'), 'hr.Holiday'),
    Area(_('Scheduling settings'), 'hr.SchedulingSettings', actions=('view', 'change')),
    # Experiments: Read the list and the read pages, Create makes an experiment (and copies one), Edit changes it, designs
    # and places it, starts it and releases or replaces a tank, Delete removes a draft. A started experiment is never
    # deleted. Who may do what to which experiment (its team) comes with the permissions plan.
    Area(_('Experiments'), 'experiments.Experiment'),
    # Sensors: the configuration of where live values come from. Edit on Channels also saves a channel's calibrations.
    Area(_('Connections'), 'sensors.Connection'),
    Area(_('Payload formats'), 'sensors.PayloadFormat'),
    Area(_('Devices'), 'sensors.Device'),
    Area(_('Channels'), 'sensors.Channel'),
    # Where a channel's values belong: Create is the Move dialog (also from a monitoring card), Edit changes only the end
    # and the note, Delete hides a wrong binding with its history.
    Area(_('Channel bindings'), 'sensors.Binding'),
    # Sensor readings: Read is the Charts and Live values pages and a place's charts in a monitoring window. Nobody writes
    # them but the ingest service.
    Area(_('Sensor readings'), 'sensors.Reading', actions=('view',)),
    # Dead letters: Read is their page, Edit marks one resolved (logged). The ingest writes them; nobody deletes one.
    Area(_('Dead letters'), 'sensors.DeadLetter', actions=('view', 'change')),
    # Alarms are shown, not sent. Rules: read, create, edit, delete. Events: Read is their page, Edit acknowledges one.
    Area(_('Alarm rules'), 'sensors.AlarmRule'),
    Area(_('Alarm events'), 'sensors.AlarmEvent', actions=('view', 'change')),
    # The broker credentials, a right apart from the devices: Create and Edit show a secret once (made, or replaced).
    Area(_('Sensor credentials'), 'sensors.Credential'),
    # The platform owner's settings (one row: Read, Edit). "Platform owner" is the role that holds Edit here: the correction
    # window, whether a second person approves a withdrawal acknowledgement, and the alarms' escalation time.
    Area(_('Platform settings'), 'core.PlatformSettings', actions=('view', 'change')),
    # Opening balances: Read is their list. Registering one is the platform owner's right (Platform settings: Edit), never
    # a right of its own: it is the one record dated beyond the correction window.
    Area(_('Opening balances'), 'farm.OpeningBalance', actions=('view',)),
    Area(_('Activity log'), 'core.AuditLog', actions=('view',)),
]
