"""What the broker's acl file is written from holds no line break (the security review of the go-live package, S1):
`manage.py sensor_broker_sync` writes a connection's user name and every device's topic into lines of that text file,
so a line break in either would have written a rule of its own (`topic write #`). A device's topic has no whitespace
or control character, a connection's user name is a broker user name (letters, digits and . _ @ -, as a credential's).
Every development and test row checked before (read-only): none breaks either rule."""

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sensors', '0013_channel_ph_scale'),
    ]

    operations = [
        migrations.AlterField(
            model_name='connection',
            name='username',
            field=models.CharField(blank=True, max_length=100, validators=[django.core.validators.RegexValidator('^[A-Za-z0-9_.@-]+$', 'Letters, digits and . _ @ - only.')], verbose_name='User name'),
        ),
        migrations.AddConstraint(
            model_name='connection',
            constraint=models.CheckConstraint(condition=models.Q(('username', ''), ('username__regex', '^[A-Za-z0-9_.@-]+$'), _connector='OR'), name='chk_sensors_connection_username', violation_error_message='Letters, digits and . _ @ - only.'),
        ),
        migrations.AddConstraint(
            model_name='device',
            constraint=models.CheckConstraint(condition=models.Q(('topic__regex', '[[:space:][:cntrl:]]'), _negated=True), name='chk_sensors_device_topic_plain', violation_error_message='A topic has no spaces, tabs or line breaks.'),
        ),
    ]
