"""A broker credential's secret: made on the server, shown once, stored only as Mosquitto's password-file hash (`$7$`:
PBKDF2-HMAC-SHA512, a 12-byte salt and a 64-byte digest, standard base64; the format of mosquitto_passwd 2.x, checked
against lines it wrote in sensors-ingest/spikes/s0f_mosquitto_hash.py and the tests). Only the standard library."""
import base64
import hashlib
import hmac
import secrets

from django.utils import timezone

# mosquitto_passwd writes 101 iterations; the broker reads the count from the line, so a higher one is accepted. A
# secret made here is 32 random bytes, so the count guards nothing a guess could reach; 101 keeps the broker's sign-in
# cost as mosquitto_passwd's own.
ITERATIONS = 101
SALT_BYTES, DIGEST_BYTES = 12, 64
SECRET_BYTES = 32


def new_secret():
    """A secret for a publisher: 32 random bytes, URL-safe text (43 characters)."""
    return secrets.token_urlsafe(SECRET_BYTES)


def hash_secret(secret, salt=None, iterations=ITERATIONS):
    """The password-file hash of a secret: $7$ITERATIONS$SALT$DIGEST."""
    salt = secrets.token_bytes(SALT_BYTES) if salt is None else salt
    digest = hashlib.pbkdf2_hmac('sha512', secret.encode('utf-8'), salt, iterations, DIGEST_BYTES)
    return f'$7${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}'


def verify(secret, encoded):
    """Whether `secret` is the one `encoded` was made from (a constant-time comparison)."""
    try:
        kind, iterations, salt, _digest = encoded.split('$')[1:]
        if kind != '7':
            return False
        return hmac.compare_digest(hash_secret(secret, base64.b64decode(salt), int(iterations)), encoded)
    except (ValueError, TypeError):
        return False


def give_secret(credential):
    """Makes the credential a new secret, stores its hash and the moment, and returns the secret, which is shown once
    and never kept. The caller logs the change (without values) and moves the version."""
    secret = new_secret()
    credential.password_hash = hash_secret(secret)
    credential.rotated_at = timezone.now()
    credential.save(update_fields=['password_hash', 'rotated_at', 'updated_at'])
    return secret

# How the activity log says a secret changed: never its value or its hash.
SECRET_LABEL, REPLACED = 'Secret', '(replaced)'


def rotate(user, pk, version):
    """Replaces a credential's secret for `user` (the data-layering audit, L-1: the rule here, not in the view): who may
    (Edit on credentials), the row locked, refused (core.crud.Crossed) when it changed since the page was opened (its
    `version`), the version moved, logged without any value. Returns (credential, the new secret, shown once). The broker
    takes it when its files are written again (`manage.py sensor_broker_sync`)."""
    from django.db import transaction

    from core import access, audit
    from core.crud import Crossed
    from core.models import AuditLog

    from .models import Credential
    from .resources import CredentialResource
    access.require(user, CredentialResource.perm('change'))
    with transaction.atomic():
        credential = Credential.objects.select_for_update().get(pk=pk)
        if str(version) != str(credential.version):
            raise Crossed
        secret = give_secret(credential)
        credential.version += 1
        credential.updated_by = user
        credential.save(update_fields=['version', 'updated_by', 'updated_at'])
        with audit.source_language():
            audit.record(user, AuditLog.Action.UPDATE, credential, {SECRET_LABEL: [REPLACED, REPLACED]},
                         entity_type=CredentialResource.entity_type())
    return credential, secret
