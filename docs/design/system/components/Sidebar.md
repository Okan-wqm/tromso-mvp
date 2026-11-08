# Sidebar

The rail: the app's main menu on `surface-rail` with the logo disc, the SU/DERRA wordmark, a panel switch and grouped links.

- **Use** on every signed-in page: 240px (`rail-w`) from a 1280px viewport, 72px icon rail (`rail-w-compact`) from 1024 to 1279px on fine pointers, a 56px bottom bar below.
- **The consumer provides** the panel (Company or Production), the groups and links the person's role opens, the current page (`aria-current="page"`), badge counts, and the company and site for the foot.
- **Order** is daily work first: Overview, Operations, Feeding, Harvest, Health, Reports, Communication, Team; Setup collapsed last and remembered.
- **Active item**: a light fill, bold label and a 4px `brand` bar. Never red.
- **Badges** are 20px pills in a translucent white on the rail; `data-status="critical"` makes one `crit`, only for a critical count.
- Group labels are 13/600 in `text-on-rail` at 62% opacity, sentence case, never caps.
- Icons 20px at stroke 1.75 from `templates/icons/`; in the compact rail the label goes to `aria-label`.
- Classes: `ui-rail`, `ui-rail-head`, `ui-logo`, `ui-wordmark`, `ui-panel-switch`, `ui-rail-nav`, `ui-rail-group`, `ui-rail-link`, `ui-rail-badge`, `ui-rail-foot`.
