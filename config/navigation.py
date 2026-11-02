from core.navigation import Entry, Group

MENU = [
    Group('', [Entry('Overview', 'home', 'home')]),
    Group('Facility', [Entry('Sites', 'farm:site_list', 'building', 'farm.view_site')]),
    Group('Administration', [Entry('Activity log', 'core:activity_log', 'history', 'core.view_auditlog')]),
]
