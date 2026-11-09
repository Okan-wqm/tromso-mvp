"""What the data map (core.datamap) cannot read from the code, for the monitoring tables. A board is an ordinary tab
(its create, edit, delete and read pages, and its restore in the admin, come from the code); its cards are a row list on
that tab (saved as a whole list, logged on the board as one change), so their paths are the list's. Card templates and
their rules are tabs of Reference data. Said here: how a deleted unit's row behaves, the columns no form writes (the
old modes, the built-in mark, the layout version) and how the templates' and rules' rules work."""
from core.datamap import Screen, computed

# The modes of the boards before card templates: kept for one release so a rollback loses nothing (migration 0004
# copied them into the templates); no form writes them, the release after drops them.
OLD_MODE = computed('the mode before card templates, kept for one release for a rollback (migration 0004)')

SCREENS = {
    'MonitorBoard': Screen(
        columns={'default_mode': OLD_MODE},
        note='Deleting a board is a soft delete; its card rows stay and come back with it when it is restored.'),
    'CardTemplate': Screen(
        note='The layout is edited on the Design tab (the designer fills the JSON the validator checks); the layout version '
             'is stamped from the layout. The three built-ins come from migration 0002 and a trigger keeps them as they '
             'are: Copy makes an editable one. Deleting a template deletes its rules and detaches the boards and '
             'templates that point at it; restoring brings back the template with its rules (the boards and '
             'templates stay detached).'),
    'CardTemplateAssignment': Screen(
        note='One scope per rule (a CHECK) and one live rule per scope, the global rule included (a unique index whose '
             'empty values count as equal). The global rule is never deleted and stays global. A rule of a deleted unit, '
             'system or species is kept and counts again when it is restored.'),
    'MonitorBoardUnit': Screen(
        columns={'mode': OLD_MODE},
        note="A deleted unit keeps its row (configuration, not history): its card is hidden while the unit is deleted and "
             "comes back when it is restored; saving the board's Units list drops the row."),
}
