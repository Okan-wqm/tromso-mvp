# MealBoard

Production › Feeding › Meal board: the daily heart, one row per unit with the next meal as the largest figure on the screen.

- Columns: Unit (sticky), Next meal (`readout` 28/700 and the feed), Today (meal pips: done filled, next ringed in `action`, later dashed, plus "3.70 of 14.28 kg, 10.58 left"), Fish now, Water (value face with origin and age), Record meal (sticky, outlined).
- A row with no ration is a hold row: the why sentence ("12.3 °C is outside this table (8.0–12.0 °C)…") where the next meal would be, Record meal still offered. Never zeros.
- A warning about a row sits under it as a warning chip; the row takes `edge-warn`.
- Keep the safety line visible: "Over- and underfeeding are not flagged yet."
- Phone: a card per unit, Next meal at 28px and a 56px full-width Record meal.
