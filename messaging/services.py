"""The one write path of Messages. The pages (messaging/views.py) call these functions, and so will a mobile
app's API and the AI assistants: each rule is here once.

- Who: a person uses Messages with Read on the access area Messages (`messaging.view_conversation`) and an
  active account; Create on it (`messaging.add_conversation`) also creates channels. Only the members of a
  conversation read and write it (`member`): to anyone else it does not exist (Http404), whatever their role,
  the platform admin included. A channel's owners add and remove members and make them owners.
- A direct conversation is one per pair: `start_direct` finds it or creates it, and the database's unique
  key decides when both people start it at the same moment.
- `post` locks the conversation, so its messages are numbered in the order they are committed: the read
  pointer (the last message read) never passes a message that was still being written.
- Messages are never edited (a correction is a new message); `delete_message` hides one for good, by its
  author, keeping who and when.
- `mark_read` moves a participant's pointer forward, never back.

The activity log records the channels: created, members added and removed, owners changed, by name and
without a word of what is written. Direct conversations and messages are not logged: the log is read by
roles that are not in the conversation, and would tell them who writes to whom (README, Messages).

A refusal raises ValidationError (a dict of field to message) for what was entered, PermissionDenied for
what the person may not do, and Http404 for a conversation they are not a member of."""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy

from core import access, audit

from . import events
from .models import CHANNEL_NAME_TAKEN, MAX_BODY, Conversation, Message, Participant, person_name

USE, CREATE_CHANNEL = 'messaging.view_conversation', 'messaging.add_conversation'
# How the activity log names a channel and the two lists it keeps of one.
CHANNEL = gettext_lazy('channel')
MEMBERS, OWNERS = gettext_lazy('Members'), gettext_lazy('Owners')
NAME = gettext_lazy('Channel name')


def contacts(user=None):
    """The people one can write to, by name: active accounts that may use Messages; without `user` among them."""
    people = get_user_model().objects.with_perm(USE, is_active=True, include_superusers=True)
    if user is not None:
        people = people.exclude(pk=user.pk)
    return people.order_by('first_name', 'last_name', 'username')


def _reachable(people, field):
    """Refuses anyone who cannot use Messages: they could never read what is written to them."""
    allowed = set(contacts().filter(pk__in=[person.pk for person in people]).values_list('pk', flat=True))
    refused = sorted(person_name(person) for person in people if person.pk not in allowed)
    if refused:
        raise ValidationError({field: _('%(names)s cannot use Messages.') % {'names': ', '.join(refused)}})


def direct_key(*parties):
    """The key of the direct conversation between two people (Conversation.direct_key): the same whichever
    starts it. An assistant's part will read 'assistant:<id>'."""
    return ' '.join(sorted(f'user:{party.pk}' for party in parties))


def member(user, conversation_id):
    """The person's live membership of a live conversation. Http404 when there is none: a page never says
    whether a conversation the person is not in exists."""
    access.require(user, USE)
    return get_object_or_404(Participant.objects.select_related('conversation'), user=user,
                             conversation_id=conversation_id, conversation__is_deleted=False)


def _locked(conversation_id):
    """The conversation, locked until the end of the transaction: posts and membership changes take turns."""
    return get_object_or_404(Conversation.objects.select_for_update(), pk=conversation_id)


def owner(user, conversation_id, lock=False):
    """The person's membership of a channel they own (the channel locked when asked); PermissionDenied when they
    are a member who does not own it."""
    if lock:
        _locked(conversation_id)
    actor = member(user, conversation_id)
    if not (actor.conversation.is_channel and actor.is_owner):
        raise PermissionDenied
    return actor


# ---- conversations ---------------------------------------------------------------------------------------
@transaction.atomic
def start_direct(user, other):
    """The direct conversation between `user` and `other`, created the first time."""
    access.require(user, USE)
    if other.pk == user.pk:
        raise ValidationError({'person': _('Choose someone else: a conversation is with another person.')})
    _reachable([other], 'person')
    key = direct_key(user, other)
    found = Conversation.all_objects.filter(direct_key=key).first()
    if found is not None:
        return found
    try:
        with transaction.atomic():
            conversation = Conversation.objects.create(kind=Conversation.Kind.DIRECT, direct_key=key,
                                                       created_by=user, updated_by=user)
            Participant.objects.bulk_create([
                Participant(conversation=conversation, user=person, created_by=user, updated_by=user)
                for person in (user, other)])
    except IntegrityError:
        # Started by the other person a moment ago: theirs is the one.
        return Conversation.all_objects.get(direct_key=key)
    return conversation


def _roster(conversation):
    """The members and the owners of a channel, as the activity log keeps them (people's names, as written)."""
    live = sorted(conversation.participants.select_related('user', 'assistant'), key=str)
    return {audit.english(MEMBERS): ', '.join(str(p) for p in live) or None,
            audit.english(OWNERS): ', '.join(str(p) for p in live if p.is_owner) or None}


def _log_roster(user, conversation, before):
    audit.record_update(user, conversation, before, _roster(conversation), entity_type=CHANNEL)


@transaction.atomic
def create_channel(user, name, members=()):
    """A channel called `name`, owned by `user`, with `members`."""
    access.require(user, CREATE_CHANNEL)
    name = ' '.join(name.split())
    if not name:
        raise ValidationError({'name': _('Give the channel a name.')})
    others = [person for person in members if person.pk != user.pk]
    _reachable(others, 'members')
    conversation = Conversation(kind=Conversation.Kind.CHANNEL, name=name, created_by=user, updated_by=user)
    try:
        with transaction.atomic():
            conversation.save()
    except IntegrityError as error:
        if getattr(getattr(error.__cause__, 'diag', None), 'constraint_name', '') != 'channel_name_unique':
            raise
        raise ValidationError({'name': CHANNEL_NAME_TAKEN}) from error
    Participant.objects.bulk_create(
        [Participant(conversation=conversation, user=user, role=Participant.Role.OWNER, created_by=user,
                     updated_by=user)]
        + [Participant(conversation=conversation, user=person, created_by=user, updated_by=user) for person in others])
    audit.record_create(user, conversation, {audit.english(NAME): name, **_roster(conversation)}, entity_type=CHANNEL)
    return conversation


@transaction.atomic
def add_members(user, conversation_id, people):
    """Adds people to a channel (by one of its owners). Someone who was a member before gets their row back;
    their unread messages start from now, as a new member's do."""
    actor = owner(user, conversation_id, lock=True)
    conversation = actor.conversation
    _reachable(people, 'people')
    before = _roster(conversation)
    latest = conversation.messages.order_by('-id').first()
    for person in people:
        participant, created = Participant.all_objects.get_or_create(
            conversation=conversation, user=person,
            defaults={'created_by': user, 'updated_by': user, 'last_read': latest})
        if created or not participant.is_deleted:
            continue
        participant.is_deleted, participant.deleted_at, participant.deleted_by = False, None, None
        participant.role, participant.last_read, participant.updated_by = Participant.Role.MEMBER, latest, user
        participant.version += 1
        participant.save()
    _log_roster(user, conversation, before)


def _keep_an_owner(conversation, target, leaving):
    """A channel with members keeps an owner: the last one cannot leave, be removed or stop being one while
    others remain."""
    live = list(conversation.participants.all())
    owners = [p for p in live if p.is_owner]
    if owners == [target] and (len(live) > 1 if leaving else True):
        raise ValidationError(_('A channel needs an owner: make another member an owner first.'))


def _remove(user, conversation, target):
    """Takes `target` out of the channel. A channel its last member leaves is deleted with that membership (F-110):
    with nobody in it nobody could reach its history or take it over, and its name stayed taken. Its messages stay
    with it, and the admin can restore it with its member."""
    _keep_an_owner(conversation, target, leaving=True)
    before = _roster(conversation)
    if conversation.participants.exclude(pk=target.pk).exists():
        target.soft_delete(user)
        _log_roster(user, conversation, before)
        return
    # The last one: the membership and the channel go at one moment, so a restore brings the channel back with its
    # member (core.softdelete.restore, cross review F5).
    moment = timezone.now()
    target.mark_deleted(user, moment)
    _log_roster(user, conversation, before)
    conversation.mark_deleted(user, moment)
    audit.record_delete(user, conversation, entity_type=CHANNEL)


@transaction.atomic
def remove_member(user, conversation_id, participant_id):
    """Removes a member from a channel (by one of its owners). Their messages stay, with their name."""
    actor = owner(user, conversation_id, lock=True)
    target = get_object_or_404(Participant.objects.select_related('user', 'assistant'), pk=participant_id,
                               conversation_id=conversation_id)
    _remove(user, actor.conversation, target)


@transaction.atomic
def leave(user, conversation_id):
    """The person leaves a channel. A direct conversation is not left: it is between two people."""
    _locked(conversation_id)
    actor = member(user, conversation_id)
    if not actor.conversation.is_channel:
        raise PermissionDenied
    _remove(user, actor.conversation, actor)


@transaction.atomic
def set_role(user, conversation_id, participant_id, role):
    """Makes a member of a channel an owner, or an owner a member (by one of its owners)."""
    actor = owner(user, conversation_id, lock=True)
    if role not in Participant.Role.values:
        raise ValidationError({'role': _('Choose owner or member.')})
    target = get_object_or_404(Participant.objects.select_related('user', 'assistant'), pk=participant_id,
                               conversation_id=conversation_id)
    if target.role == role:
        return
    if role == Participant.Role.MEMBER:
        _keep_an_owner(actor.conversation, target, leaving=False)
    before = _roster(actor.conversation)
    target.role, target.updated_by = role, user
    target.version += 1
    target.save(update_fields=['role', 'updated_by', 'version', 'updated_at'])
    _log_roster(user, actor.conversation, before)


# ---- messages --------------------------------------------------------------------------------------------
@transaction.atomic
def post(author, body):
    """A message by `author`, a participant: a person's (`post_as`), or later an assistant's. The conversation
    is locked so that its messages are numbered in the order they are committed. `events.message_posted` is
    sent once the message is committed."""
    Conversation.objects.select_for_update().get(pk=author.conversation_id)
    author = Participant.objects.filter(pk=author.pk).first()
    if author is None:
        raise PermissionDenied     # left or removed meanwhile
    text = body.replace('\r\n', '\n').strip()
    if not text:
        raise ValidationError({'body': _('Write a message first.')})
    if len(text) > MAX_BODY:
        raise ValidationError({'body': _('A message has at most %(count)d characters.') % {'count': MAX_BODY}})
    message = Message.objects.create(conversation_id=author.conversation_id, author=author, body=text)
    transaction.on_commit(lambda: events.message_posted.send(
        sender=Message, message_id=message.pk, conversation_id=message.conversation_id))
    return message


def post_as(user, conversation_id, body):
    """A message by the person, in a conversation they are a member of."""
    return post(member(user, conversation_id), body)


def own_message(user, conversation_id, message_id, lock=False):
    """A message the person wrote, in a conversation they are a member of; Http404 when there is no such message
    there, PermissionDenied when someone else wrote it."""
    actor = member(user, conversation_id)
    messages = Message.objects.select_for_update() if lock else Message.objects
    message = get_object_or_404(messages, pk=message_id, conversation_id=conversation_id)
    if message.author_id != actor.pk:
        raise PermissionDenied
    return message


@transaction.atomic
def delete_message(user, conversation_id, message_id):
    """Deletes a message, by its author: the row stays with who deleted it and when, the text is never shown
    again. Deleting it again changes nothing."""
    message = own_message(user, conversation_id, message_id, lock=True)
    if not message.is_deleted:
        message.is_deleted, message.deleted_at, message.deleted_by = True, timezone.now(), user
        message.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])
    return message


def mark_read(participant, message_id):
    """Moves the participant's read pointer forward to `message_id`, a message of their conversation; a pointer
    already there or further stays. Reading is not an edit: no version, no activity-log row."""
    if message_id is None:
        return
    if not Message.objects.filter(pk=message_id, conversation_id=participant.conversation_id).exists():
        raise ValidationError({'message': _('That message is not in this conversation.')})
    Participant.objects.filter(pk=participant.pk).filter(
        Q(last_read__isnull=True) | Q(last_read_id__lt=message_id)).update(last_read_id=message_id)
