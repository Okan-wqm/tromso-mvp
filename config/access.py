from core.access import Area

# What the role form's permission matrix offers, one line per area (core.access).
AREAS = [
    Area('Facility', 'Sites', 'farm.Site'),
    Area('Administration', 'Activity log', 'core.AuditLog', actions=('view',)),
]
