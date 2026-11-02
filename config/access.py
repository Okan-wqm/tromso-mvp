from core.access import Area

# What the role form's permission matrix offers, one line per area (core.access).
AREAS = [
    Area('Company · Facility', 'Sites', 'farm.Site'),
    Area('Production · Facility structure', 'Production departments', 'farm.ProductionDepartment'),
    Area('Production · Facility structure', 'Systems', 'farm.System'),
    Area('Company · Administration', 'Activity log', 'core.AuditLog', actions=('view',)),
]
