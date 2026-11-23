"""The sensors' inputs of the water's judgement move their revisions (core_rev, core.rev; the plan's B2): the bindings
(which channel counts at which place, from when to when) and the channels (their quantity, state, pH scale and
freshness), each table as one key. Never the tables the ingest writes (sensors_reading, sensors_channel_state,
sensors_device_state: core.rev.NEVER_TRACKED): a live value is proved by its channel's state, never by a revision."""
from django.db import migrations

from core.operations import TrackRev


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_rev'),
        ('sensors', '0013_channel_ph_scale'),
    ]

    operations = [
        TrackRev('sensors_binding', 'sensors_binding'),
        TrackRev('sensors_channel', 'sensors_channel'),
    ]
