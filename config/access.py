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
    # Experiments: Read the list and the read pages, Create makes an experiment (and copies one), Edit changes it, designs
    # and places it, starts it and releases or replaces a tank, Delete removes a draft. A started experiment is never
    # deleted. Who may do what to which experiment (its team) comes with the permissions plan.
    Area(_('Experiments'), 'experiments.Experiment'),
    Area(_('Activity log'), 'core.AuditLog', actions=('view',)),
]
