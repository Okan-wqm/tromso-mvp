from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel

# A broker user name: the passwd file separates name and hash with a colon, so no colon and no space.
USERNAME = r'^[A-Za-z0-9_.@-]+$'


class Credential(AuditedModel):
    """A publisher's sign-in at the broker: a user name and the hash of its secret (Mosquitto's PBKDF2-SHA512 `$7$`
    format, sensors/credentials.py). One gateway may publish for many devices. The secret is made on the server, shown
    once and never stored; the hash is not on any form, so the activity log never holds it, and the database viewer
    masks it. The broker's passwd and acl files are written from these rows by `manage.py sensor_broker_sync`."""

    username = models.CharField(_('User name'), max_length=100)
    password_hash = models.CharField(_('Password hash'), max_length=255, editable=False)
    rotated_at = models.DateTimeField(_('Secret made at'), null=True, blank=True, editable=False)
    is_enabled = models.BooleanField(_('Enabled'), default=True)

    class Meta:
        db_table = 'sensors_credential'
        ordering = ['username']
        verbose_name = _('sensor credential')
        verbose_name_plural = _('sensor credentials')
        constraints = [
            models.UniqueConstraint(Lower('username'), condition=Q(is_deleted=False),
                                    name='uq_sensors_credential_username_live',
                                    violation_error_message=_('Another credential already has this user name.')),
            models.CheckConstraint(condition=Q(username__regex=USERNAME), name='chk_sensors_credential_username',
                                   violation_error_message=_('Letters, digits and . _ @ - only.')),
            # Mosquitto's $7$ format, or empty for a row that has never had a secret (it cannot sign in).
            models.CheckConstraint(condition=Q(password_hash='') | Q(password_hash__regex=r'^\$7\$[0-9]+\$[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+$'),
                                   name='chk_sensors_credential_hash'),
        ]

    def __str__(self):
        return self.username
