from django.utils.translation import gettext_lazy as _

from core.access import Area

# What the role form's permission matrix offers, one line per area (core.access). The matrix groups
# the areas the way the menu (config/navigation.py) places their pages.
AREAS = [
    Area(_('Sites'), 'farm.Site'),
    Area(_('Production departments'), 'farm.ProductionDepartment'),
    Area(_('Systems'), 'farm.System'),
    Area(_('Equipment'), 'farm.Equipment'),
    Area(_('Tanks, ponds & cages'), 'farm.Tank'),
    Area(_('Species'), 'farm.Species'),
    Area(_('Feeds'), 'farm.Feed'),
    Area(_('Water limits'), 'farm.WaterLimit'),
    Area(_('Medicines'), 'farm.Medicine'),
    Area(_('Suppliers'), 'farm.Supplier'),
    # The stock: Read is the Production units page, Create records an operation (a stocking, a mortality,
    # a weighing), Delete voids one. Operations are never edited: a correction is a void and a new entry.
    Area(_('Production units'), 'farm.StockOperation', actions=('view', 'add', 'delete')),
    # The feeding records: Read is the Feeding records page (and the feeding part of a unit's drawer), Create
    # records a feeding, Delete voids one. Records are never edited: a correction is a void and a new entry.
    Area(_('Feeding records'), 'farm.FeedingRecord', actions=('view', 'add', 'delete')),
    # Water samples: Read is the Water chemistry page (and a unit's water in the drawer), Create records a
    # sample or a round, Delete voids a sample. Samples are never edited: a correction is a void and a new entry.
    Area(_('Water chemistry'), 'farm.WaterMeasurement', actions=('view', 'add', 'delete')),
    # Treatments: Read the list (and a unit's health in the drawer), Create records one, Edit changes its last
    # day (logged), Delete voids one, which lifts its withdrawal. Nothing else of a treatment is edited.
    Area(_('Treatments'), 'farm.Treatment'),
    # Health events: Read, Create, Edit on the event's form (logged), Delete voids one with its reason.
    Area(_('Health events'), 'farm.HealthEvent'),
    # Sea-lice counts: Read the page with the site's weekly averages, Create records a count, Delete voids one.
    Area(_('Sea-lice counts'), 'farm.LiceCount', actions=('view', 'add', 'delete')),
    Area(_('Activity log'), 'core.AuditLog', actions=('view',)),
]
