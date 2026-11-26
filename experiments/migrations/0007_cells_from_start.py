"""A draft seals nothing (the coordinator's decision of 2026-11-25 on landing review W3): the sealed cells are those of a
started experiment (running or closed), so a draft placed on a tank, past days included, hides no record of it from
anyone. Sealing starts when the experiment is started; a day 0 already past is started by an Oversee holder
(experiments.services.start), who so seals the days already passed. The view is the same but for that condition."""
from importlib import import_module

from django.db import migrations

_BOOKING = import_module('experiments.migrations.0004_confidential').BOOKING
VIEW_V1 = _BOOKING[_BOOKING.index('CREATE VIEW experiment_cells'):_BOOKING.index('WHERE NOT b.is_deleted;')
                   + len('WHERE NOT b.is_deleted;')].replace('CREATE VIEW', 'CREATE OR REPLACE VIEW', 1)
VIEW_V2 = VIEW_V1.replace("AND e.audience <> 'open'", "AND e.audience <> 'open' AND e.status <> 'draft'")
assert VIEW_V2.count("e.status <> 'draft'") == 2


class Migration(migrations.Migration):

    dependencies = [
        ('experiments', '0006_care_instructions'),
    ]

    operations = [
        migrations.RunSQL(VIEW_V2, reverse_sql=VIEW_V1),
    ]
