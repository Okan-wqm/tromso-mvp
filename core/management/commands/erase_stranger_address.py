"""`manage.py erase_stranger_address ADDRESS`: erases, on request, the address of a stranger an invitation was mis-sent
to (core/erasure.py; docs/erasure.md, step 8). Run by the platform's database administrator on the data-protection
officer's written instruction; no page does this.

Without `--apply` it changes nothing: it says exactly which `account_mails` rows and which activity-log rows and
labels would change, and where else the text of the address stands (left as it is). That is the default because the
erasure cannot be undone and sets the log's append-only trigger aside: the operator reads what will change, then
runs it again with `--apply`, the instruction and their name.

    python manage.py erase_stranger_address stranger@example.com
    python manage.py erase_stranger_address stranger@example.com --apply \\
        --instruction "DPO instruction of 2026-11-11, ref. DP-17" --carried-out-by "Kari Nordmann" """
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email

from core import erasure


class Command(BaseCommand):
    help = ('Erases the address of a stranger an invitation was mis-sent to, on the data-protection officer\'s '
            'instruction: in account_mails and in the activity log\'s rows of the account (the address replaced by a '
            'placeholder, one "Erased on request" row added on each account touched). Without --apply nothing is '
            'changed: it lists what would be. Refuses an address that is an account\'s own now. Cannot be undone.')

    def add_arguments(self, parser):
        parser.add_argument('address', help='The address to erase, as it was typed (case and outer spaces do not matter).')
        parser.add_argument('--apply', action='store_true', help='Carry it out. Without it nothing is changed.')
        parser.add_argument('--instruction', default='',
                            help='The instruction it is done on: its reference and date, never the address itself '
                                 '(written in the log\'s row).')
        parser.add_argument('--carried-out-by', default='', help='Who carries it out (written in the log\'s row).')

    def handle(self, *args, address, apply=False, instruction='', carried_out_by='', **options):
        address = address.strip()
        try:
            validate_email(address)
        except ValidationError:
            raise CommandError(f'“{address}” is not an e-mail address: give the address alone, as it was typed.') from None
        if not apply:
            self.said(erasure.plan(address), applied=False)
            return
        instruction, by = ' '.join(instruction.split()), ' '.join(carried_out_by.split())
        if not instruction or not by:
            raise CommandError('--apply needs --instruction (the data-protection officer\'s instruction: its reference '
                               'and date) and --carried-out-by (your name): both are written in the log\'s row, so '
                               'neither may hold the address itself.')
        try:
            found = erasure.erase(address, instruction, by)
        except erasure.Refused as refusal:
            raise CommandError(str(refusal)) from refusal
        self.said(found, applied=True)

    def said(self, found, applied):
        write = self.stdout.write
        if not applied:
            write('Dry run: nothing is changed. Run again with --apply, --instruction and --carried-out-by to carry it out.')
        if found.held_by:
            names = ', '.join(user.get_username() for user in found.held_by)
            write(f'REFUSED: {found.address} is the address of an account now ({names}). This erases a stranger\'s '
                  f'address only; with --apply nothing would be changed.')
        if found.waiting:
            write(f'REFUSED for now: a mail to {found.address} is being sent right now (account_mails '
                  f'{", ".join(str(mail.pk) for mail in found.waiting)}). Run this again when its row says what became '
                  f'of it.')
        if found.empty:
            write(f'Nothing found: no account_mails row and no activity-log row of a user account holds {found.address}.')
        else:
            done = 'changed' if applied else 'would change'
            write(f'{len(found.mails)} account_mails row(s) {done}:')
            for mail, mine, error in found.mails:
                what = ' and '.join(filter(None, ['address' if mine else '', 'error' if error is not None else '']))
                write(f'  account_mails {mail.pk}: {mail.kind} of {mail.created_at:%Y-%m-%d %H:%M} UTC for account '
                      f'{mail.user_id} ({mail.user.get_username()}): {what}')
            write(f'{len(found.entries)} activity-log row(s) {done}:')
            for entry, labels, _changes in found.entries:
                write(f'  audit_log {entry.pk}: {entry.action} of {entry.created_at:%Y-%m-%d %H:%M} UTC on account '
                      f'{entry.entity_id} ({entry.entity_label}): {", ".join(labels)}')
            accounts = ', '.join(str(pk) for pk in found.accounts)
            write(f'One “Erased on request” row {"added" if applied else "would be added"} on each account touched: '
                  f'{accounts}.')
        if found.elsewhere:
            write('The text also stands here, left as it is (not this command\'s to change):')
            for where in found.elsewhere:
                write(f'  {where}')
        if applied and not found.empty:
            write('The activity log\'s append-only trigger is in force. Backups taken before this still hold the address.')
