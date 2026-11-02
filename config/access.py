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
    Area(_('Suppliers'), 'farm.Supplier'),
    Area(_('Activity log'), 'core.AuditLog', actions=('view',)),
]
