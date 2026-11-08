# Button

Buttons commit, open or follow: filled ink for the one primary per view, outlined for everything else, a link style for "learn more".

- `data-variant="primary"`: `primary` fill, `on-primary` label. One per view.
- Default (no variant): outlined with `line-control` on `surface-sheet`; row buttons such as Record meal.
- `data-variant="link"`: `action` text, underlined.
- `data-variant="danger"`: `crit` fill, only inside a destructive confirm, never beside Edit.
- `data-size="coarse"`: 48px; a coarse primary is 56px (`primary-h-coarse`).
- **The consumer provides** the label (one name per action, "Record meal" → "Meal recorded") and an optional 16px icon before it. No arrows.
