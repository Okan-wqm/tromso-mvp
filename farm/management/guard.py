"""How a management command goes through the withdrawal guard: it shows the guard's question and writes nothing until
the operator has read it and passes its fingerprint back (`--acknowledge`), as a page's box does."""
from django.contrib.auth import get_user_model
from django.core.management.base import CommandError

from farm.health.withdrawal import WithdrawalChanged


def add_arguments(parser):
    parser.add_argument('--by', required=True, help='The user name of the person who does it (their rights are asked).')
    parser.add_argument('--reason', required=True, help='Why: kept with the record and in the activity log.')
    parser.add_argument('--acknowledge', default='', help=(
        'The fingerprint the command printed with the withdrawal question: pass it to go on past exactly that '
        'question.'))


def person(name):
    try:
        return get_user_model().objects.get(username=name)
    except get_user_model().DoesNotExist:
        raise CommandError(f'No user named {name!r}.') from None


def asked(command, call):
    """Runs `call()`; when the withdrawal guard asks, prints its question and the fingerprint to pass with
    --acknowledge, and stops: nothing was written."""
    try:
        return call()
    except WithdrawalChanged as refused:
        for message in refused.change.messages():
            command.stdout.write(command.style.WARNING(message))
        if refused.change.second_person:
            command.stdout.write(command.style.WARNING(refused.change.second_person))
        raise CommandError(
            'Nothing was written: the withdrawal guard asks first. To go on past exactly this, run it again with '
            f'--acknowledge {refused.change.fingerprint}') from None
