"""The rules the database holds, whatever writes the rows."""
from django.db import DataError, IntegrityError, transaction
from django.utils import timezone

from ..models import MAX_BODY, Assistant, Conversation, Message, Participant
from ..services import direct_key
from . import MessagingTestCase, check_deferred


class DatabaseRuleTests(MessagingTestCase):
    def refused(self, error=IntegrityError):
        return self.assertRaises(error)

    def channel(self, name='Hall A'):
        return Conversation.objects.create(kind='channel', name=name)

    def test_a_pair_has_one_direct_conversation(self):
        Conversation.objects.create(kind='direct', direct_key=direct_key(self.ali, self.egon))
        with self.refused(), transaction.atomic():
            Conversation.objects.create(kind='direct', direct_key=direct_key(self.egon, self.ali))
        self.assertEqual(direct_key(self.ali, self.egon), direct_key(self.egon, self.ali))

    def test_a_direct_conversation_has_a_key_and_no_name_and_a_channel_the_other_way_round(self):
        for fields in ({'kind': 'direct', 'direct_key': 'user:1 user:2', 'name': 'x'}, {'kind': 'direct'},
                       {'kind': 'channel', 'name': ''}, {'kind': 'channel', 'name': 'x', 'direct_key': 'user:1 user:2'},
                       {'kind': 'group', 'name': 'x'}):
            with self.subTest(fields=fields), self.refused(), transaction.atomic():
                Conversation.objects.create(**fields)

    def test_a_channel_name_is_unique_among_live_channels_whatever_its_case(self):
        first = self.channel('Hall A')
        with self.refused(), transaction.atomic():
            self.channel('hall a')
        first.soft_delete(self.ali)
        self.channel('HALL A')

    def test_a_participant_is_a_person_or_an_assistant_exactly_one(self):
        channel = self.channel()
        assistant = Assistant.objects.create(name='Feeding assistant', owner=self.ali)
        with self.refused(), transaction.atomic():
            Participant.objects.create(conversation=channel)
        with self.refused(), transaction.atomic():
            Participant.objects.create(conversation=channel, user=self.ali, assistant=assistant)
        Participant.objects.create(conversation=channel, user=self.ali)
        Participant.objects.create(conversation=channel, assistant=assistant)

    def test_a_party_is_in_a_conversation_once_left_or_not(self):
        channel = self.channel()
        member = Participant.objects.create(conversation=channel, user=self.ali)
        member.soft_delete(self.ali)
        with self.refused(), transaction.atomic():
            Participant.objects.create(conversation=channel, user=self.ali)

    def test_a_role_is_owner_or_member(self):
        with self.refused(), transaction.atomic():
            Participant.objects.create(conversation=self.channel(), user=self.ali, role='admin')

    def test_a_message_is_written_by_a_participant_of_its_own_conversation(self):
        here, there = self.channel('Here'), self.channel('There')
        author = Participant.objects.create(conversation=there, user=self.ali)
        with self.refused(), transaction.atomic():
            Message.objects.create(conversation=here, author=author, body='Hello')
            check_deferred()

    def test_a_read_pointer_points_at_a_message_of_its_own_conversation(self):
        here, there = self.channel('Here'), self.channel('There')
        reader = Participant.objects.create(conversation=here, user=self.ali)
        writer = Participant.objects.create(conversation=there, user=self.egon)
        elsewhere = Message.objects.create(conversation=there, author=writer, body='Hello')
        with self.refused(), transaction.atomic():
            Participant.objects.filter(pk=reader.pk).update(last_read=elsewhere)
            check_deferred()

    def test_a_message_has_text_within_its_length(self):
        channel = self.channel()
        author = Participant.objects.create(conversation=channel, user=self.ali)
        for body in ('', '  \n\t '):
            with self.subTest(body=body), self.refused(), transaction.atomic():
                Message.objects.create(conversation=channel, author=author, body=body)
        with self.refused(DataError), transaction.atomic():
            Message.objects.create(conversation=channel, author=author, body='x' * (MAX_BODY + 1))
        Message.objects.create(conversation=channel, author=author, body='x' * MAX_BODY)

    def test_a_deleted_message_says_when(self):
        channel = self.channel()
        author = Participant.objects.create(conversation=channel, user=self.ali)
        message = Message.objects.create(conversation=channel, author=author, body='Hello')
        with self.refused(), transaction.atomic():
            Message.objects.filter(pk=message.pk).update(is_deleted=True)
        with self.refused(), transaction.atomic():
            Message.objects.filter(pk=message.pk).update(deleted_at=timezone.now())

    def test_a_message_never_shows_its_text_as_a_name(self):
        channel = self.channel()
        author = Participant.objects.create(conversation=channel, user=self.ali)
        message = Message.objects.create(conversation=channel, author=author, body='The secret recipe')
        self.assertNotIn('secret', str(message))
        self.assertEqual(str(author), 'Ali Kaya')
