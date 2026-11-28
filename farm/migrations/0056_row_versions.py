"""The rows a plan from a past start reads as they were at the end of that day (owner decision 12, as decided after review
1), kept in every version (core.versions, core.operations.KeepVersions): the protocols' and the temperature profiles'
assignment rows, the protocols with their bands and cells, the profiles with their points, and the planned harvests and
transports whose fasts the plan reads. The rows already there are known from when they were made (a band or a cell from
its protocol's making: the table is saved whole); a row deleted by then is kept as it was before and after its delete."""
from django.db import migrations

from core.operations import KeepVersions

PROTOCOL_MADE = '(SELECT p.created_at FROM feeding_protocols p WHERE p.id = {row}.protocol_id)'
BAND_MADE = ('(SELECT p.created_at FROM feeding_protocols p JOIN feeding_protocol_bands b ON b.protocol_id = p.id '
             'WHERE b.id = {row}.band_id)')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0021_row_versions'),
        ('farm', '0055_weighing_names_its_source'),
    ]

    operations = [
        KeepVersions('feeding_protocols', '{row}.created_at', soft_deleted=True),
        KeepVersions('feeding_protocol_bands', PROTOCOL_MADE),
        KeepVersions('feeding_protocol_rates', BAND_MADE),
        KeepVersions('protocol_assignments', '{row}.created_at', soft_deleted=True),
        KeepVersions('temperature_profiles', '{row}.created_at', soft_deleted=True),
        KeepVersions('temperature_profile_points', '{row}.created_at'),
        KeepVersions('temperature_profile_assignments', '{row}.created_at', soft_deleted=True),
        KeepVersions('handling_plan_items', '{row}.created_at', soft_deleted=True),
    ]
