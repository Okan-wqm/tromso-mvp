from django.utils.translation import gettext_lazy as _

from core.access import Area

# What the role form's permission matrix offers, one line per area (core.access).
AREAS = [
    Area(_('Company · Facility'), _('Sites'), 'farm.Site'),
    Area(_('Production · Facility structure'), _('Production departments'), 'farm.ProductionDepartment'),
    Area(_('Production · Facility structure'), _('Systems'), 'farm.System'),
    Area(_('Company · Administration'), _('Activity log'), 'core.AuditLog', actions=('view',)),
]
