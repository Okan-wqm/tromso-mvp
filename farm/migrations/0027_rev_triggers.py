"""The stock ledger moves the revision of its batches (core_rev scope 'batch', core.rev): a line inserted, changed or
deleted (the day of its operation), an operation re-dated or voided or restored (every batch it has lines of, the
earlier of its two days) and a batch given another species (its whole history: the fold reads the species)."""
from django.db import migrations

from core.operations import TrackRev


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_rev'),
        ('farm', '0026_production_form_other'),
    ]

    operations = [
        TrackRev('stock_movements', 'batch', keys='{row}.batch_id',
                 day='SELECT date FROM stock_operations WHERE id = {row}.operation_id'),
        TrackRev('stock_operations', 'batch', keys='SELECT batch_id FROM stock_movements WHERE operation_id = {row}.id',
                 day='{row}.date', columns=('date', 'is_deleted'), events=('UPDATE',)),
        TrackRev('batches', 'batch', keys='{row}.id', day="DATE '0001-01-01'", columns=('species_id',),
                 events=('UPDATE',)),
    ]
