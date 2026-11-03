"""Reading Messages for the pages (and later the API): a person's conversations with their last message and
unread count, the unread total of the menu's badge, and a conversation's messages. Nothing here writes.

Unread, for a participant: the messages of the conversation after their read pointer, written by someone
else, not deleted. A new member starts with the conversation's latest message as read (services.add_members),
so joining a channel does not bring its whole history in as unread."""
from dataclasses import dataclass

from django.db.models import BigIntegerField, Count, Exists, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.urls import reverse

from core.navigation import Badge

from .models import Conversation, Message, Participant

# How many messages a conversation shows at once; earlier ones are a link away.
PAGE = 50
# How many new messages one poll brings at most; the next poll brings the rest.
POLL_LIMIT = 200


def unread_total(user):
    """Every unread message of the person, in all their conversations."""
    mine = Participant.objects.filter(user=user, conversation=OuterRef('conversation'),
                                      conversation__is_deleted=False).filter(
        Q(last_read__isnull=True) | Q(last_read__lt=OuterRef('pk'))).exclude(pk=OuterRef('author'))
    return Message.objects.filter(is_deleted=False).filter(Exists(mine)).count()


def unread_badge(user):
    """The number beside Messages in the menu (config/navigation.py), and the fragment that renders it again."""
    return Badge(unread_total(user), reverse('messaging:unread'))


@dataclass
class Row:
    """A conversation as the person's list shows it."""
    conversation: Conversation
    participant: Participant
    title: str
    other: Participant = None      # the other party of a direct conversation
    members: int = 0               # a channel's members
    last: Message = None
    unread: int = 0


def inbox(user):
    """The person's conversations, latest activity first."""
    latest = Message.objects.filter(conversation=OuterRef('conversation')).order_by('-id')
    unread = (Message.objects.filter(conversation=OuterRef('conversation'), is_deleted=False,
                                     id__gt=Coalesce(OuterRef('last_read'), Value(0), output_field=BigIntegerField()))
              .exclude(author=OuterRef('pk')).values('conversation').annotate(count=Count('pk')).values('count'))
    memberships = list(
        Participant.objects.filter(user=user, conversation__is_deleted=False)
        .select_related('conversation')
        .annotate(last_id=Subquery(latest.values('id')[:1]),
                  last_at=Subquery(latest.values('created_at')[:1]),
                  unread=Coalesce(Subquery(unread, output_field=IntegerField()), Value(0)))
        .order_by(Coalesce('last_at', 'conversation__created_at').desc(), 'conversation__name'))
    conversations = [m.conversation_id for m in memberships]
    last = Message.objects.select_related('author__user', 'author__assistant').in_bulk(
        [m.last_id for m in memberships if m.last_id])
    others = {p.conversation_id: p for p in Participant.all_objects.filter(
        conversation__in=conversations, conversation__kind=Conversation.Kind.DIRECT).exclude(user=user)
        .select_related('user', 'assistant')}
    counts = dict(Participant.objects.filter(conversation__in=conversations, conversation__kind=Conversation.Kind.CHANNEL)
                  .values_list('conversation').annotate(Count('pk')))
    rows = []
    for membership in memberships:
        conversation, other = membership.conversation, others.get(membership.conversation_id)
        rows.append(Row(conversation, membership, conversation.name if conversation.is_channel else str(other),
                        other=other, members=counts.get(conversation.pk, 0), last=last.get(membership.last_id),
                        unread=membership.unread))
    return rows


def title(participant):
    """What the person sees as the conversation's name: a channel's name, or the other party's."""
    conversation = participant.conversation
    if conversation.is_channel:
        return conversation.name
    return str(Participant.all_objects.select_related('user', 'assistant')
               .exclude(pk=participant.pk).get(conversation=conversation))


def members(conversation):
    """A channel's members, the owners first, by name."""
    return sorted(conversation.participants.select_related('user', 'assistant'),
                  key=lambda p: (not p.is_owner, str(p).lower()))


def _messages(conversation):
    return conversation.messages.select_related('author__user', 'author__assistant')


def timeline(participant, before=None):
    """The latest PAGE messages, or the PAGE before message `before`, oldest first; and whether there are
    earlier ones."""
    messages = _messages(participant.conversation)
    if before is not None:
        messages = messages.filter(id__lt=before)
    page = list(messages.order_by('-id')[:PAGE + 1])
    return page[:PAGE][::-1], len(page) > PAGE


def after(participant, message_id):
    """The messages after `message_id`, oldest first (a poll); at most POLL_LIMIT."""
    return list(_messages(participant.conversation).filter(id__gt=message_id).order_by('id')[:POLL_LIMIT])


def first_unread(participant, messages):
    """The first of these messages the participant had not read (where the page marks "New")."""
    pointer = participant.last_read_id or 0
    return next((m.pk for m in messages if m.pk > pointer and m.author_id != participant.pk and not m.is_deleted),
                None)
