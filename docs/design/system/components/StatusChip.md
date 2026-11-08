# StatusChip

A status said by shape, word and fill weight, with colour third, so it survives greyscale, colour blindness and glare.

- `data-status="ok"`: a check-circle in `ok`, no container; the word may be screen-reader only in tables.
- `data-status="warning"`: `warn-tint` fill, triangle in `warn`, word in `warn-text`.
- `data-status="critical"`: `crit` fill, octagon, `on-crit` word; the row also gets `edge-crit`.
- `data-status="hold"`: outline in `line-control`, hourglass, `text-2` and a date ("Withdrawal to 24 Nov"). Never red.
- `data-state="stale"`: outline, clock and an age ("2 d ago"); `data-state="nodata"`: dashed outline and "Not measured".
- `data-status="neutral"`: counts ("23 units") on `surface-sunken`.
- **The consumer provides** the glyph and the word; never a glyph alone. 24px high, 13/600.
