"""What the data map (core.datamap) cannot read from the code, for the sensors tables. The configuration (connections,
payload formats, devices, channels and their calibrations, credentials) is ordinary tabs and a row list. The other
tables are written by the ingest service (sensors-ingest/, sensors/CONTRACT.md) or seeded by the migrations; Django
reads them."""
from core.datamap import Screen, computed, no, system

INGEST = 'written by the ingest service (sensors/CONTRACT.md), never by a page'
MIGRATION = 'one row written by migration sensors 0001; the contract is changed by a migration, never by a page'

SCREENS = {
    'Credential': Screen(
        note='The secret is made on the server and shown once, on create and on Replace the secret; only its hash is '
             'stored (masked in the database viewer, never in the activity log).',
        columns={'password_hash': system('the hash of the secret made on create or on Replace the secret'),
                 'rotated_at': system('when the secret was made')}),
    'Contract': Screen(
        create=no(MIGRATION), edit=no(MIGRATION), delete=no(MIGRATION), read=no('read by the ingest service; shown in '
                                                                              'the database viewer'),
        columns={'*': system('the contract row: its version, the epoch a trigger moves on every configuration change, '
                             'and the time limits')}),
    'QualityFlag': Screen(
        create=no('seeded by migration sensors 0001 from sensors/quality.py'), edit=no('the bits are the contract'),
        delete=no('the bits are the contract'), read=no('read by the ingest service and the tests; shown in the '
                                                         'database viewer'),
        columns={'*': system('sensors/quality.py, the one definition')}),
    'ChannelState': Screen(
        create=no(INGEST), edit=no(INGEST), delete=no(INGEST), read=no('read by the latest values (sensors/read.py)'),
        columns={'*': computed('the ingest service\'s memory of the channel, updated with every batch it writes')}),
    'DeviceState': Screen(
        create=no(INGEST), edit=no(INGEST), delete=no(INGEST), read=no('read by the device status (sensors/read.py)'),
        columns={'*': computed('what the ingest service has seen of the device')}),
    'IngestStatus': Screen(
        create=no(INGEST), edit=no(INGEST), delete=no(INGEST), read=no('read by the Sensors overview'),
        columns={'*': computed('the ingest service\'s heartbeat per connection')}),
    'DeadLetter': Screen(
        create=no(INGEST), edit=no('the message is evidence: only its resolution is set, by a person'),
        delete=no('pruned after 90 days by manage.py sensors_housekeeping'),
        read=no('read by the Sensors overview'),
        columns={'*': computed('what the ingest service could not store, counted'),
                 'resolved_at': system('set when a person marks it resolved'),
                 'resolved_by': system('the person who marked it resolved')}),
    'Reading': Screen(
        create=no(INGEST), edit=no('a reading is never changed: stored values are calibrated at the device time'),
        delete=no('dropped with its chunk after the raw retention (730 days), never one by one'),
        read=no('read through the rollups and the reads of sensors/read.py, never through the database viewer'),
        note='A TimescaleDB hypertable; left out of the database viewer (billions of rows).',
        columns={'*': computed('the stored value of a channel at the device\'s time, with the run it closes')}),
}
