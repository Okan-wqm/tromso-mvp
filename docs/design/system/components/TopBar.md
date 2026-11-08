# TopBar

The 56px bar above every page: where you are, the language switch and the user menu, followed by the page head.

- **The consumer provides** the breadcrumb (section › page), the current language and the user's initials and name.
- The EN / TR / NB switch is a segmented group; the pressed language takes `action-tint` and `action`.
- The page head below it: `h1` in `font-display`, one line of status chips (`ui-head-status`), the single primary action at the right (`ui-head-actions`).
- Do not put a second primary in the head or eyebrows over every block.
- Classes: `ui-topbar`, `ui-crumbs`, `ui-lang`, `ui-user`, `ui-avatar`, `ui-page`, `ui-head`.
