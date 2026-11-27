"""THE assignment resolver (owner decision 16 of 2026-11-26): which row of an assignment table is in force for a batch in
a unit on a day. Shared by the feeding protocols' rows and the temperature profiles' rows (farm/models/assignment.py);
pure: the rows are loaded by the caller (farm/feeding/read.py), so the walk, the ration and the plan ahead read them
once.

The most specific row in force that day wins: the batch in this unit, else the unit's row, else the whole batch's
(owner decision Q8). A unit's row for another species is read past, and kept so the page can say why: a unit's row
outlives the fish in it. After a grading or a split each part is a batch in its own unit, so it resolves its own row
(decision 19) without anything entered again."""
from collections import defaultdict


class Resolver:
    """The rows of one assignment table (`subject`: the name of their table's foreign key, 'protocol' or 'profile'),
    `species_of`: {table id: species id}, `species`: {batch id: species id}."""

    def __init__(self, rows, subject, species_of, species):
        self.subject = f'{subject}_id'
        self.species_of = species_of
        self.species = species
        self._rows = defaultdict(list)
        self._resolved = {}
        for row in rows:
            self._rows[(row.unit_id, row.batch_id)].append(row)

    def _in_force(self, unit_id, batch_id, day):
        return next((row for row in self._rows.get((unit_id, batch_id), ()) if row.covers(day)), None)

    def resolve(self, unit_id, batch_id, day):
        """(the row in force, a unit's row of another species read past): batch in unit, then the unit, then the whole
        batch. (None, None) when no row applies."""
        cached = self._resolved.get((unit_id, batch_id, day))
        if cached is not None:
            return cached
        skipped = None
        found = self._in_force(unit_id, batch_id, day)
        if found is None:
            found = self._in_force(unit_id, None, day)
            if found is not None and self.species_of[getattr(found, self.subject)] != self.species.get(batch_id):
                skipped, found = found, None
        if found is None:
            found = self._in_force(None, batch_id, day)
        self._resolved[(unit_id, batch_id, day)] = result = (found, skipped)
        return result
