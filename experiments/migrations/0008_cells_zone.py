"""The sealed cells carry their site's time zone (landing review 3, S4): a cell's days are its site's, so the seal reads a
moment's day on the clock of the cell it is compared with (core.sealing._cell_day), never the company's. The view is the
same but for the added column `zone` (the experiment's site's)."""
from importlib import import_module

from django.db import migrations

VIEW_V2 = import_module('experiments.migrations.0007_cells_from_start').VIEW_V2
VIEW_V3 = (VIEW_V2
           .replace('u.from_on, u.until_on, g.experiment_id\n', 'u.from_on, u.until_on, g.experiment_id, st.timezone AS zone\n')
           .replace('b.from_on, b.until_on, g.experiment_id\n', 'b.from_on, b.until_on, g.experiment_id, st.timezone\n')
           .replace("AND e.status <> 'draft'\n", "AND e.status <> 'draft'\n        JOIN sites st ON st.id = e.site_id\n"))
assert VIEW_V3.count('st.timezone') == 2 and VIEW_V3.count('JOIN sites st') == 2, VIEW_V3


class Migration(migrations.Migration):

    dependencies = [
        ('experiments', '0007_cells_from_start'),
    ]

    operations = [
        migrations.RunSQL(VIEW_V3, reverse_sql='DROP VIEW experiment_cells; ' + VIEW_V2),
    ]
