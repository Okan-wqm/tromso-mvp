"""What the data map (core.datamap) cannot read from the code, for the monitoring tables. A board is an ordinary tab
(its create, edit, delete and read pages, and its restore in the admin, come from the code); its cards are a row list on
that tab (saved as a whole list, logged on the board as one change), so their paths are the list's. The only thing said here
is how a deleted unit's row behaves."""
from core.datamap import Screen

SCREENS = {
    'MonitorBoard': Screen(note='Deleting a board is a soft delete; its card rows stay and come back with it when it is restored.'),
    'MonitorBoardUnit': Screen(
        note="A deleted unit keeps its row (configuration, not history): its card is hidden while the unit is deleted and "
             "comes back when it is restored; saving the board's Units list drops the row."),
}
