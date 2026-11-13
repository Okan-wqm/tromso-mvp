"""`manage.py erase_stranger_address ADDRESS`: erases, on request, an address an invitation was mis-sent to
(core/erasure.py; docs/erasure.md, step 8). Run by the platform's database administrator on the data-protection
officer's written instruction; no page does this.

It checks only that no account has the address now (and refuses while a mail to it is still being sent). It cannot
tell a stranger's address from a person's own former one, or from one an intruder put on an account: so the dry run
shows, for each account touched, what the activity log says (from when to when the address was the account's own,
whether it replaced an earlier address, whether a password was set through a link sent to it, what the account wrote
meanwhile) and says so plainly when it does not look like a stranger's. The data-protection officer judges; the
command obeys.

Without `--apply` it changes nothing: it says exactly which `account_mails` rows and which activity-log rows and
labels would change, and where else the text of the address stands (left as it is). That is the default because the
erasure cannot be undone and sets the log's append-only trigger aside: the operator reads what will change, then
runs it again with `--apply`, the instruction and their name. With `--apply` the log is locked against writers for
the moment of the change; the command waits for that lock at most `--lock-wait` seconds (a positive number) and gives
up otherwise, and it does not wait at all for `account_mails` once it holds the log: when a mail is being written
just then it gives up and says so.

    python manage.py erase_stranger_address stranger@example.com
    python manage.py erase_stranger_address stranger@example.com --apply \\
        --instruction "DPO instruction of 2026-11-11, ref. DP-17" --carried-out-by "Kari Nordmann" """
import argparse
import math

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email

from core import erasure


def seconds(text):
    """`--lock-wait`: a positive number of seconds (zero, a negative number, `nan` and `inf` are refused: a wait of no
    time is no wait, and the others are no time)."""
    try:
        value = float(text)
    except ValueError:
        value = math.nan
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError(f'“{text}” is not a positive number of seconds.')
    return value


class Command(BaseCommand):
    help = ('Erases an address an invitation was mis-sent to, on the data-protection officer\'s instruction: in '
            'account_mails and in the activity log\'s rows of the account (the address replaced by a placeholder, one '
            '"Erased on request" row added on each account touched). Without --apply nothing is changed: it lists '
            'what would be, and what the log says of each account. It checks only that no account has the address now: '
            'it cannot tell a stranger’s address from a person’s own former one, which is the data-protection '
            'officer\'s to judge. Cannot be undone.')

    def add_arguments(self, parser):
        parser.add_argument('address', help='The address to erase, as it was typed (case and outer spaces do not matter).')
        parser.add_argument('--apply', action='store_true', help='Carry it out. Without it nothing is changed.')
        parser.add_argument('--instruction', default='',
                            help='The instruction it is done on: its reference and date, never the address itself '
                                 '(written in the log\'s row).')
        parser.add_argument('--carried-out-by', default='', help='Who carries it out (written in the log\'s row).')
        parser.add_argument('--lock-wait', type=seconds, default=erasure.LOCK_WAIT_SECONDS, metavar='SECONDS',
                            help='How long to wait for the lock on the activity log before giving up, a positive '
                                 'number (default %(default)s): every writer of the log, the alarms among them, waits '
                                 'meanwhile.')

    def handle(self, *args, address, apply=False, instruction='', carried_out_by='', lock_wait=None, **options):
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
            found = erasure.erase(address, instruction, by,
                                  lock_wait=erasure.LOCK_WAIT_SECONDS if lock_wait is None else lock_wait)
        except erasure.Refused as refusal:
            raise CommandError(str(refusal)) from refusal
        self.said(found, applied=True)

    def said(self, found, applied):
        write = self.stdout.write
        if not applied:
            write('Dry run: nothing is changed. Run again with --apply, --instruction and --carried-out-by to carry it out.')
        if found.held_by:
            write(f'REFUSED: {found.address} is the address of an account now ({erasure.held_by_names(found)}). This '
                  f'command erases only an address that no account has now; with --apply nothing would be changed.')
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
                      f'{mail.user_id} ({mail.user.get_username()}): {what}{self.as_stored(found, "mail", mail.pk)}')
            write(f'{len(found.entries)} activity-log row(s) {done}:')
            for entry, labels, _changes in found.entries:
                write(f'  audit_log {entry.pk}: {entry.action} of {entry.created_at:%Y-%m-%d %H:%M} UTC on account '
                      f'{entry.entity_id} ({entry.entity_label}): {", ".join(labels)}'
                      f'{self.as_stored(found, "entry", entry.pk)}')
            accounts = ', '.join(str(pk) for pk in found.accounts)
            write(f'One “Erased on request” row {"added" if applied else "would be added"} on each account touched: '
                  f'{accounts}.')
            if not applied:
                self.judged(found)
        if found.elsewhere:
            write('The text also stands here, left as it is (not this command\'s to change):')
            for where in found.elsewhere:
                write(f'  {where}')
        if found.near:
            write('NOT changed, and to be looked at: these hold an address that is this one only when the Turkish '
                  'capital İ and the dotless ı are read as i. To the command they are other letters, so another address. '
                  'If it is the same address, run the command again with the address written as it is stored:')
            for where in found.near:
                write(f'  {where}')
        if applied and not found.empty:
            write('The activity log\'s append-only trigger is in force. Backups taken before this still hold the address.')

    @staticmethod
    def as_stored(found, kind, pk):
        """The value as the row holds it, when that is not how it was typed (another case, another Unicode form)."""
        stored = found.stored.get((kind, pk))
        return f' (stored as “{stored}”)' if stored else ''

    def judged(self, found):
        """What is checked, and what the log says of each account: what the data-protection officer judges the case by."""
        write, stamp = self.stdout.write, '%Y-%m-%d %H:%M'
        write('Checked: no account has this address now. Not checked: whose address it was. This command cannot tell a '
              'stranger\'s address from a person\'s own former one, or from one an intruder put on an account and took '
              'off again. What the activity log says of each account:')
        for history in found.histories:
            write(f'Account {history.account} ({history.name}):')
            for start, how, until, end in history.own:
                closed = f'to {until:{stamp}} UTC ({end})' if until is not None else 'with no row that ends it'
                write(f'  its own address from {start:{stamp}} UTC ({how}) {closed}')
            for when, how in history.replaced:
                write(f'  it replaced an earlier address of the account: {when:{stamp}} UTC ({how})')
            if not history.own:
                write('  the log has no row that made it the account\'s own address')
            for when, who in history.invitations:
                write(f'  an invitation was sent, or tried, to it: {when:{stamp}} UTC, by {who}')
            for when, who in history.passwords:
                write(f'  a password was set through a link sent to it: {when:{stamp}} UTC, by {who}')
            if not history.passwords:
                write('  no password was set through a link sent to it')
            if history.used:
                write(f'  the account wrote {history.used} other log row(s) itself while it was its address')
            if history.warnings:
                write(f'  WARNING: this does not look like a stranger’s address: {"; ".join(history.warnings)}. '
                      f'Erasing it removes the evidence of where this account\'s links went. The data-protection '
                      f'officer decides.')
