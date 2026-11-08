"""Writes the broker's password file and access list from the rows (sensors/CONTRACT.md, decision 11): the one way
credentials and topics reach Mosquitto, so the database stays the only source of truth (no dynamic-security plugin).

- passwd: the lines of `--extra` first (the ones operations keep themselves, the ingest service's own user among them,
  each checked to be a `user:$7$...` line), then `username:hash` of every live, enabled credential that has a secret;
- acl: per connection, its ingest user may read the topic of each live active device; per credential, it may write the
  topic of each live active device that publishes with it. Nothing else may read or write.

By default both go to SENSORS_BROKER_AUTH_DIR, which the broker container mounts at /mosquitto/auth; its entrypoint
reloads them within 5 s (sensors-ingest/mosquitto, spike S0f: connected clients stay, a removed or rotated credential is
cut off). Each file is written next to itself and moved into place, so the broker never reads half a file. `--check`
writes nothing and fails when a file differs from what the rows say."""
import os
import re
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from sensors.models import Connection, Credential, Device

LINE = re.compile(r'^[A-Za-z0-9_.@-]+:\$7\$[0-9]+\$[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+$')


def passwd_text(extra_lines):
    lines = list(extra_lines)
    for credential in Credential.objects.filter(is_enabled=True).exclude(password_hash='').order_by('username'):
        lines.append(f'{credential.username}:{credential.password_hash}')
    return ''.join(f'{line}\n' for line in lines)


def acl_text():
    devices = Device.objects.filter(is_active=True, connection__is_active=True, connection__is_deleted=False)
    parts = ['# Written by manage.py sensor_broker_sync from the Sensors configuration. Do not edit.\n']
    for connection in Connection.objects.filter(is_active=True).exclude(username='').order_by('name'):
        topics = sorted({device.topic for device in devices.filter(connection=connection)})
        parts.append(f'\nuser {connection.username}\n' + ''.join(f'topic read {topic}\n' for topic in topics))
    for credential in Credential.objects.filter(is_enabled=True).exclude(password_hash='').order_by('username'):
        topics = sorted({device.topic for device in devices.filter(credential=credential)})
        parts.append(f'\nuser {credential.username}\n' + ''.join(f'topic write {topic}\n' for topic in topics))
    return ''.join(parts)


def write(path, text):
    """Replaces the file in one step (a temporary file in its folder, then a rename), readable by its owner and group."""
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}.')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8', newline='\n') as file:
            file.write(text)
        os.chmod(temporary, 0o640)
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


class Command(BaseCommand):
    help = 'Writes the MQTT broker\'s passwd and acl files from the sensors configuration.'

    def add_arguments(self, parser):
        parser.add_argument('--passwd', help='The broker’s password file (default: SENSORS_BROKER_AUTH_DIR/passwd).')
        parser.add_argument('--acl', help='The broker’s access list (default: SENSORS_BROKER_AUTH_DIR/acl).')
        parser.add_argument('--extra', help='A file of passwd lines kept by operations (the ingest\'s own user).')
        parser.add_argument('--check', action='store_true', help='Write nothing; fail when a file is not current.')

    def handle(self, *args, **options):
        extra = []
        if options['extra']:
            for number, line in enumerate(Path(options['extra']).read_text(encoding='utf-8').splitlines(), 1):
                if not line.strip():
                    continue
                if not LINE.match(line.strip()):
                    raise CommandError(f'{options["extra"]} line {number} is not a "user:$7$..." passwd line.')
                extra.append(line.strip())
        folder = Path(settings.SENSORS_BROKER_AUTH_DIR)
        passwd = Path(options['passwd']) if options['passwd'] else folder / 'passwd'
        acl = Path(options['acl']) if options['acl'] else folder / 'acl'
        wanted = {passwd: passwd_text(extra), acl: acl_text()}
        if options['check']:
            stale = [str(path) for path, text in wanted.items()
                     if not path.exists() or path.read_text(encoding='utf-8') != text]
            if stale:
                raise CommandError(f'Not current: {", ".join(stale)}. Run manage.py sensor_broker_sync.')
            self.stdout.write('The broker files are current.')
            return
        for path, text in wanted.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            write(path, text)
        self.stdout.write(f'Wrote {", ".join(str(path) for path in wanted)}; the broker reads them again within 5 s.')
