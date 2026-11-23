"""The farm's inputs of the water's judgement move their revisions (core_rev, core.rev), so a stored water status can
prove it is still valid (live-data architecture, stage 3; the plan's B2):

- The stock ledger, per batch (scope 'batch', the fold's key) and per unit (scope 'unit_stock': the fish in a unit on a
  day decide which species a value is judged for, farm.water.read.SpeciesBook): a line inserted, changed or deleted (the
  day of its operation), an operation re-dated or voided or restored (every batch and unit it has lines of, the earlier
  of its two days) and a batch given another species (its whole history, in every unit it was ever in).
- The samples, per sampling point (scope 'water_point'): a sample written, changed, moved to another point, voided or
  restored moves the old and the new point.
- The reference data and the places the judgement reads, each table as one key: the sampling points, the limits, the
  species (a limit counts only while its species is live), the freshness rules, the units, the systems, the sites, the
  production departments, the equipment and the systems it serves."""
from django.db import migrations

from core.operations import TrackRev

LINE_DAY = 'SELECT date FROM stock_operations WHERE id = {row}.operation_id'
TABLES = ('water_sampling_points', 'water_limits', 'species', 'water_freshness', 'tanks', 'systems', 'sites',
          'production_departments', 'equipment', 'equipment_systems')


# Every key that exists when the triggers come gets a row (core_rev_ensure, core/0014): the points, the units, the
# batches and the tables. A key with no row is unknown and never valid; without this, a point nothing has changed since
# would never be served from a stored row.
BACKFILL = (
    "SELECT core_rev_ensure(coalesce(array_agg(s), '{}'), coalesce(array_agg(k), '{}')) FROM ("
    "SELECT 'water_point' AS s, id::text AS k FROM water_sampling_points "
    "UNION ALL SELECT 'unit_stock', id::text FROM tanks "
    "UNION ALL SELECT 'batch', id::text FROM batches "
    "UNION ALL SELECT t, '0' FROM unnest(%s) AS t) AS q"
) % ('ARRAY[' + ', '.join(f"'{table}'" for table in TABLES) + ']::text[]')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_rev'),
        ('farm', '0049_water_origin_help'),
    ]

    operations = [
        TrackRev('stock_movements', 'batch', keys='{row}.batch_id', day=LINE_DAY),
        TrackRev('stock_operations', 'batch', keys='SELECT batch_id FROM stock_movements WHERE operation_id = {row}.id',
                 day='{row}.date', columns=('date', 'is_deleted'), events=('UPDATE',)),
        TrackRev('batches', 'batch', keys='{row}.id', day="DATE '0001-01-01'", columns=('species_id',),
                 events=('UPDATE',)),
        TrackRev('stock_movements', 'unit_stock', keys='{row}.unit_id', day=LINE_DAY),
        TrackRev('stock_operations', 'unit_stock',
                 keys='SELECT unit_id FROM stock_movements WHERE operation_id = {row}.id',
                 day='{row}.date', columns=('date', 'is_deleted'), events=('UPDATE',)),
        TrackRev('batches', 'unit_stock', keys='SELECT unit_id FROM stock_movements WHERE batch_id = {row}.id',
                 day="DATE '0001-01-01'", columns=('species_id',), events=('UPDATE',)),
        TrackRev('water_measurements', 'water_point', keys='{row}.point_id'),
        *(TrackRev(table, table) for table in TABLES),
        migrations.RunSQL(BACKFILL, migrations.RunSQL.noop),
    ]
