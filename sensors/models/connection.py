from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel

from .credential import USERNAME

PORT_MIN, PORT_MAX = 1, 65535
KEEPALIVE_MIN, KEEPALIVE_MAX = 5, 600
# A file name under /run/secrets: no directory part, never a secret itself.
SECRET_FILE = r'^[A-Za-z0-9_.-]+$'


class Connection(AuditedModel):
    """An MQTT broker the ingest service listens to: where it is, how the service signs in (a user name and the name of a
    secret file, never the secret) and its client id. The topics it subscribes to follow from the active devices of the
    connection, so they are not stored here. Deleting one deletes its devices and their channels with it (one
    confirmation lists them); their readings stay."""

    name = models.CharField(_('Name'), max_length=100)
    host = models.CharField(_('Host'), max_length=255)
    port = models.PositiveIntegerField(_('Port'), default=8883,
                                       validators=[MinValueValidator(PORT_MIN), MaxValueValidator(PORT_MAX)])
    use_tls = models.BooleanField(_('Use TLS'), default=True)
    # A line of the broker's acl names it (manage.py sensor_broker_sync): no space, colon or line break (review S1).
    username = models.CharField(_('User name'), max_length=100, blank=True,
                                validators=[RegexValidator(USERNAME, _('Letters, digits and . _ @ - only.'))])
    secret_file = models.CharField(
        _('Secret file'), max_length=100, blank=True,
        validators=[RegexValidator(SECRET_FILE, _('A file name only: letters, digits, dot, hyphen and underscore.'))])
    client_id = models.CharField(_('Client id'), max_length=100)
    keepalive_s = models.PositiveIntegerField(
        _('Keep-alive (seconds)'), default=60,
        validators=[MinValueValidator(KEEPALIVE_MIN), MaxValueValidator(KEEPALIVE_MAX)])
    is_active = models.BooleanField(_('Active'), default=True)

    class Meta:
        db_table = 'sensors_connection'
        ordering = ['name']
        verbose_name = _('connection')
        verbose_name_plural = _('connections')
        constraints = [
            models.UniqueConstraint(Lower('name'), condition=Q(is_deleted=False), name='uq_sensors_connection_name_live',
                                    violation_error_message=_('Another connection already has this name.')),
            models.UniqueConstraint('client_id', condition=Q(is_deleted=False), name='uq_sensors_connection_client_live',
                                    violation_error_message=_('Another connection already uses this client id.')),
            models.CheckConstraint(condition=~Q(name=''), name='chk_sensors_connection_name',
                                   violation_error_message=_('Give the connection a name.')),
            models.CheckConstraint(condition=~Q(host=''), name='chk_sensors_connection_host',
                                   violation_error_message=_('Give the broker’s host.')),
            models.CheckConstraint(condition=~Q(client_id=''), name='chk_sensors_connection_client_id',
                                   violation_error_message=_('Give a client id.')),
            models.CheckConstraint(condition=Q(port__gte=PORT_MIN, port__lte=PORT_MAX), name='chk_sensors_connection_port',
                                   violation_error_message=_('A port from 1 to 65535.')),
            models.CheckConstraint(condition=Q(keepalive_s__gte=KEEPALIVE_MIN, keepalive_s__lte=KEEPALIVE_MAX),
                                   name='chk_sensors_connection_keepalive',
                                   violation_error_message=_('A keep-alive from 5 to 600 seconds.')),
            models.CheckConstraint(condition=Q(secret_file='') | Q(secret_file__regex=SECRET_FILE),
                                   name='chk_sensors_connection_secret_file',
                                   violation_error_message=_('A file name only: letters, digits, dot, hyphen and '
                                                             'underscore.')),
            models.CheckConstraint(condition=~Q(secret_file__in=['.', '..']), name='chk_sensors_connection_secret_dots',
                                   violation_error_message=_('A file name only: letters, digits, dot, hyphen and '
                                                             'underscore.')),
            models.CheckConstraint(condition=Q(username='') | Q(username__regex=USERNAME),
                                   name='chk_sensors_connection_username',
                                   violation_error_message=_('Letters, digits and . _ @ - only.')),
        ]

    def __str__(self):
        return self.name
