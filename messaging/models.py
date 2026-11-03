"""Messages: conversations between the people of the farm, and later their AI assistants.

A conversation is direct (two parties, exactly one conversation per pair) or a channel (a name and its
members). Who takes part is a Participant: a person or an assistant, exactly one of them, so an assistant
joins the same conversations and writes the same messages as a person does. A message is written once:
it is never edited, and its author can delete it (soft: who and when are kept, the text is never shown
again). What a participant has read is one pointer, the last message they read.

The rules the database can hold are constraints here; the others (who may do what) are in the one write
path, messaging/services.py, which the pages call and an API will call."""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel

# The longest message, in characters: a long report fits, a pasted log file does not.
MAX_BODY = 4000
CHANNEL_NAME_TAKEN = _('A channel with this name already exists.')


def person_name(user):
    """How Messages names a person: the full name, else the username."""
    return user.get_full_name() or user.get_username()


class Assistant(AuditedModel):
    """An AI assistant that takes part in conversations like a person. A person's own assistant has an owner;
    one that watches the farm's systems has none. Nothing creates one yet: the AI module will (README,
    Messages). It exists now so that a participant is a person or an assistant from the first migration on."""

    name = models.CharField(_('Name'), max_length=100)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                              related_name='assistants', verbose_name=_('Owner'))

    class Meta:
        db_table = 'assistants'
        verbose_name = _('assistant')
        verbose_name_plural = _('assistants')

    def __str__(self):
        return self.name


class Conversation(AuditedModel):
    """A conversation: direct between two parties, or a channel with a name and members."""

    class Kind(models.TextChoices):
        DIRECT = 'direct', _('Direct conversation')
        CHANNEL = 'channel', _('Channel')

    kind = models.CharField(_('Kind'), max_length=10, choices=Kind.choices)
    # A channel's name; a direct conversation has none (each side sees the other's name).
    name = models.CharField(_('Channel name'), max_length=80, blank=True)
    # The two parties of a direct conversation as one key, e.g. 'user:3 user:7' (messaging.services.direct_key):
    # unique, so a pair has one direct conversation whoever starts it, also when both start it at the same
    # moment. NULL for a channel. It is written once, with the two participants, which never change.
    direct_key = models.CharField(max_length=100, null=True, blank=True, unique=True, editable=False)

    class Meta:
        db_table = 'conversations'
        verbose_name = _('conversation')
        verbose_name_plural = _('conversations')
        constraints = [
            # A direct conversation has its key and no name; a channel a name and no key.
            models.CheckConstraint(
                condition=Q(kind='direct', direct_key__isnull=False, name='')
                | (Q(kind='channel', direct_key__isnull=True) & ~Q(name='')),
                name='conversation_kind_shape'),
            models.UniqueConstraint(
                Lower('name'), condition=Q(kind='channel', is_deleted=False), name='channel_name_unique',
                violation_error_message=CHANNEL_NAME_TAKEN),
        ]

    def __str__(self):
        return self.name if self.kind == self.Kind.CHANNEL else f'{self.direct_key}'

    @property
    def is_channel(self):
        return self.kind == self.Kind.CHANNEL


class Participant(AuditedModel):
    """A member of a conversation: a person or an assistant, exactly one of them. A member who leaves or is
    removed is soft-deleted (who and when kept) and their name stays on their messages; adding them again
    brings the same row back. `last_read` is the last message they have read: the later messages of others,
    not deleted, are their unread ones."""

    class Role(models.TextChoices):
        OWNER = 'owner', _('Owner')
        MEMBER = 'member', _('Member')

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='participants',
                                     verbose_name=_('Conversation'))
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                             related_name='+', verbose_name=_('Person'))
    assistant = models.ForeignKey(Assistant, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name='participations', verbose_name=_('Assistant'))
    role = models.CharField(_('Role'), max_length=10, choices=Role.choices, default=Role.MEMBER)
    # A message of the same conversation (a database rule, migration 0001); it only moves forward.
    last_read = models.ForeignKey('Message', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                  verbose_name=_('Last read'))

    class Meta:
        db_table = 'conversation_participants'
        verbose_name = _('participant')
        verbose_name_plural = _('participants')
        constraints = [
            models.CheckConstraint(
                condition=Q(user__isnull=False, assistant__isnull=True) | Q(user__isnull=True, assistant__isnull=False),
                name='participant_person_or_assistant'),
            models.CheckConstraint(condition=Q(role__in=['owner', 'member']), name='participant_role_valid'),
            # One row per party and conversation, live or not: rejoining brings the row back.
            models.UniqueConstraint(fields=['conversation', 'user'], name='participant_person_once'),
            models.UniqueConstraint(fields=['conversation', 'assistant'], name='participant_assistant_once'),
            # What a message's author points at with its conversation (migration 0001).
            models.UniqueConstraint(fields=['id', 'conversation'], name='participant_in_conversation'),
        ]

    def __str__(self):
        return person_name(self.user) if self.user_id else str(self.assistant)

    @property
    def is_owner(self):
        return self.role == self.Role.OWNER


class Message(models.Model):
    """A message: its author (a participant of the same conversation, a database rule), the text and the time.
    Never edited; a deleted message keeps its row, who deleted it and when, and is shown as deleted."""

    # Numbered in the order messages are committed within a conversation (messaging.services.post locks the
    # conversation), so the read pointer never passes a message that was still being written.
    id = models.BigAutoField(primary_key=True)
    conversation = models.ForeignKey(Conversation, on_delete=models.PROTECT, related_name='messages',
                                     db_index=False, verbose_name=_('Conversation'))
    author = models.ForeignKey(Participant, on_delete=models.PROTECT, related_name='messages',
                               verbose_name=_('Author'))
    body = models.CharField(_('Message'), max_length=MAX_BODY)
    created_at = models.DateTimeField(_('Sent at'), default=timezone.now, editable=False)
    is_deleted = models.BooleanField(_('Deleted'), default=False)
    deleted_at = models.DateTimeField(_('Deleted at'), null=True, blank=True)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', verbose_name=_('Deleted by'))

    class Meta:
        db_table = 'messages'
        verbose_name = _('message')
        verbose_name_plural = _('messages')
        ordering = ['id']
        indexes = [models.Index(fields=['conversation', 'id'], name='message_timeline')]
        constraints = [
            models.CheckConstraint(condition=Q(body__regex=r'\S'), name='message_has_text'),
            models.CheckConstraint(
                condition=Q(is_deleted=False, deleted_at__isnull=True) | Q(is_deleted=True, deleted_at__isnull=False),
                name='message_deleted_when'),
            # What a participant's read pointer points at with its conversation (migration 0001).
            models.UniqueConstraint(fields=['id', 'conversation'], name='message_in_conversation'),
        ]

    def __str__(self):
        # Never the text: the activity log and the admin must not show what was written.
        return f'{self.conversation_id} #{self.pk}'
