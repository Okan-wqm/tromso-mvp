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
    # Messages: Read is the Messages page, writing in one's own conversations and starting a direct one; Create
    # also creates channels. Only the members of a conversation read it, whatever the role (messaging/services.py).
    Area(_('Messages'), 'messaging.Conversation', actions=('view', 'add')),
    Area(_('Activity log'), 'core.AuditLog', actions=('view',)),
]
