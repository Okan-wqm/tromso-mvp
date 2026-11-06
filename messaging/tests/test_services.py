"""The one write path (messaging/services.py) and what is read from it (messaging/read.py)."""
from unittest import mock

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404

from core.models import AuditLog

from .. import events, read, services
from ..models import Conversation, Message, Participant
from . import MessagingTestCase, person


class DirectConversationTests(MessagingTestCase):
    def test_a_pair_has_one_conversation_whoever_starts_it(self):
        first = services.start_direct(self.ali, self.egon)
        self.assertEqual(services.start_direct(self.egon, self.ali), first)
        self.assertEqual(Conversation.objects.filter(kind='direct').count(), 1)
        self.assertEqual({p.user for p in first.participants.all()}, {self.ali, self.egon})
        self.assertEqual(first.created_by, self.ali)

    def test_started_by_both_at_the_same_moment_it_is_still_one(self):
        theirs = services.start_direct(self.egon, self.ali)
        with mock.patch.object(Conversation.all_objects, 'filter', return_value=Conversation.objects.none()):
            mine = services.start_direct(self.ali, self.egon)     # missed theirs: the unique key decides
        self.assertEqual(mine, theirs)
        self.assertEqual(Conversation.objects.count(), 1)
        self.assertEqual(Participant.objects.count(), 2)

    def test_only_with_someone_else_who_can_use_messages(self):
        inactive = person('gone', 'view_conversation', is_active=False)
        for other, field in ((self.ali, 'person'), (self.outsider, 'person'), (inactive, 'person')):
            with self.subTest(other=other.username), self.assertRaises(ValidationError) as caught:
                services.start_direct(self.ali, other)
            self.assertIn(field, caught.exception.message_dict)
        with self.assertRaises(PermissionDenied):
            services.start_direct(self.outsider, self.ali)
        self.assertFalse(Conversation.objects.exists())

    def test_the_people_offered_are_the_active_ones_who_may_use_messages(self):
        admin = person('root', is_superuser=True)
        person('gone', 'view_conversation', is_active=False)
        self.assertEqual(list(services.contacts(self.ali)), [admin, self.egon, self.kari])

    def test_a_direct_conversation_is_not_left_and_has_no_members_to_manage(self):
        direct = services.start_direct(self.ali, self.egon)
        egon = Participant.objects.get(conversation=direct, user=self.egon)
        for change in (lambda: services.leave(self.ali, direct.pk),
                       lambda: services.add_members(self.ali, direct.pk, [self.kari]),
                       lambda: services.remove_member(self.ali, direct.pk, egon.pk)):
            with self.assertRaises(PermissionDenied):
                change()
        self.assertEqual(direct.participants.count(), 2)

    def test_direct_conversations_and_messages_are_not_in_the_activity_log(self):
        direct = services.start_direct(self.ali, self.egon)
        message = services.post_as(self.ali, direct.pk, 'Lunch at noon?')
        services.delete_message(self.ali, direct.pk, message.pk)
        self.assertFalse(AuditLog.objects.exists())


class MembershipTests(MessagingTestCase):
    def setUp(self):
        self.direct = services.start_direct(self.ali, self.egon)

    def test_only_members_read_and_write(self):
        for user in (self.kari, self.outsider):
            for call in (lambda: services.member(user, self.direct.pk),
                         lambda: services.post_as(user, self.direct.pk, 'Hi')):
                with self.subTest(user=user.username), self.assertRaises((Http404, PermissionDenied)):
                    call()
        self.assertFalse(Message.objects.exists())

    def test_a_member_who_lost_the_right_to_use_messages_reads_nothing(self):
        self.egon.groups.clear()
        self.egon = type(self.egon).objects.get(pk=self.egon.pk)    # permissions are cached on the user
        with self.assertRaises(PermissionDenied):
            services.member(self.egon, self.direct.pk)

    def test_an_unknown_conversation_is_not_found(self):
        with self.assertRaises(Http404):
            services.member(self.ali, Participant.objects.first().pk)


class PostTests(MessagingTestCase):
    def setUp(self):
        self.direct = services.start_direct(self.ali, self.egon)

    def test_a_message_is_stored_trimmed_with_its_author(self):
        message = services.post_as(self.ali, self.direct.pk, '  Feed T-01 twice today\r\nplease  ')
        stored = Message.objects.get()
        self.assertEqual(stored, message)
        self.assertEqual(stored.body, 'Feed T-01 twice today\nplease')
        self.assertEqual(stored.author.user, self.ali)
        self.assertEqual(stored.conversation, self.direct)

    def test_an_empty_or_too_long_message_is_refused(self):
        for body in ('', '   \n '):
            with self.subTest(body=body), self.assertRaises(ValidationError) as caught:
                services.post_as(self.ali, self.direct.pk, body)
            self.assertIn('body', caught.exception.message_dict)
        with self.assertRaises(ValidationError):
            services.post_as(self.ali, self.direct.pk, 'x' * 4001)
        self.assertFalse(Message.objects.exists())

    def test_the_rest_of_the_system_hears_of_a_message_once_it_is_committed(self):
        heard = []
        events.message_posted.connect(lambda **kwargs: heard.append(kwargs), weak=False, dispatch_uid='test')
        self.addCleanup(events.message_posted.disconnect, dispatch_uid='test')
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            message = services.post_as(self.ali, self.direct.pk, 'Hello')
            self.assertEqual(heard, [])                  # not before the commit
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(heard[0]['message_id'], message.pk)
        self.assertEqual(heard[0]['conversation_id'], self.direct.pk)

    def test_only_the_author_deletes_a_message_and_it_keeps_its_row(self):
        message = services.post_as(self.ali, self.direct.pk, 'Wrong unit, sorry')
        with self.assertRaises(PermissionDenied):
            services.delete_message(self.egon, self.direct.pk, message.pk)
        services.delete_message(self.ali, self.direct.pk, message.pk)
        stored = Message.objects.get()
        self.assertTrue(stored.is_deleted)
        self.assertEqual(stored.deleted_by, self.ali)
        self.assertIsNotNone(stored.deleted_at)
        deleted_at = stored.deleted_at
        services.delete_message(self.ali, self.direct.pk, message.pk)        # again: nothing changes
        self.assertEqual(Message.objects.get().deleted_at, deleted_at)
        with self.assertRaises(Http404):
            services.delete_message(self.kari, self.direct.pk, message.pk)


class UnreadTests(MessagingTestCase):
    def setUp(self):
        self.direct = services.start_direct(self.ali, self.egon)
        self.egon_in = Participant.objects.get(conversation=self.direct, user=self.egon)

    def test_unread_are_the_others_messages_after_the_pointer_not_deleted(self):
        first = services.post_as(self.ali, self.direct.pk, 'One')
        services.post_as(self.ali, self.direct.pk, 'Two')
        services.post_as(self.egon, self.direct.pk, 'Mine')                  # one's own never counts
        gone = services.post_as(self.ali, self.direct.pk, 'Three')
        services.delete_message(self.ali, self.direct.pk, gone.pk)           # a deleted one never counts
        self.assertEqual(read.unread_total(self.egon), 2)
        self.assertEqual(read.unread_total(self.ali), 1)
        services.mark_read(self.egon_in, first.pk)
        self.assertEqual(read.unread_total(self.egon), 1)
        self.assertEqual([row.unread for row in read.inbox(self.egon)], [1])

    def test_the_pointer_only_moves_forward(self):
        first = services.post_as(self.ali, self.direct.pk, 'One')
        second = services.post_as(self.ali, self.direct.pk, 'Two')
        services.mark_read(self.egon_in, second.pk)
        services.mark_read(self.egon_in, first.pk)
        self.egon_in.refresh_from_db()
        self.assertEqual(self.egon_in.last_read, second)
        self.assertEqual(read.unread_total(self.egon), 0)

    def test_a_message_of_another_conversation_is_never_the_pointer(self):
        other = services.start_direct(self.ali, self.kari)
        elsewhere = services.post_as(self.ali, other.pk, 'Hi Kari')
        with self.assertRaises(ValidationError):
            services.mark_read(self.egon_in, elsewhere.pk)
        self.egon_in.refresh_from_db()
        self.assertIsNone(self.egon_in.last_read)

    def test_the_inbox_has_the_last_message_and_the_latest_activity_first(self):
        other = services.start_direct(self.egon, self.kari)
        services.post_as(self.kari, other.pk, 'Older')
        services.post_as(self.ali, self.direct.pk, 'Newer')
        rows = read.inbox(self.egon)
        self.assertEqual([row.title for row in rows], ['Ali Kaya', 'Kari Nord'])
        self.assertEqual([row.last.body for row in rows], ['Newer', 'Older'])
        self.assertEqual([row.unread for row in rows], [1, 1])
        self.assertEqual(read.unread_badge(self.egon).text, '2')


class ChannelTests(MessagingTestCase):
    def channel(self, *members):
        return services.create_channel(self.ali, '  Hall   A ', members)

    def membership(self, channel, user):
        return Participant.all_objects.get(conversation=channel, user=user)

    def test_a_channel_has_its_creator_as_owner_and_its_members(self):
        channel = self.channel(self.egon, self.kari)
        self.assertEqual(channel.name, 'Hall A')
        self.assertEqual([(str(p), p.role) for p in read.members(channel)],
                         [('Ali Kaya', 'owner'), ('Egon Berg', 'member'), ('Kari Nord', 'member')])
        log = AuditLog.objects.get()
        self.assertEqual((log.action, log.entity_type, log.entity_label), ('create', 'channel', 'Hall A'))
        self.assertEqual(log.changes['Members'], [None, 'Ali Kaya, Egon Berg, Kari Nord'])
        self.assertEqual(log.changes['Owners'], [None, 'Ali Kaya'])

    def test_creating_one_needs_create_on_messages_and_a_free_name(self):
        with self.assertRaises(PermissionDenied):
            services.create_channel(self.egon, 'Hall B')
        self.channel()
        with self.assertRaises(ValidationError) as caught:
            services.create_channel(self.ali, 'hall a')
        self.assertEqual(caught.exception.message_dict['name'], ['A channel with this name already exists.'])
        with self.assertRaises(ValidationError) as caught:
            services.create_channel(self.ali, 'Hall C', [self.outsider])
        self.assertEqual(caught.exception.message_dict['members'], ['olav cannot use Messages.'])
        self.assertEqual(Conversation.objects.count(), 1)

    def test_owners_add_and_remove_members_and_it_is_logged(self):
        channel = self.channel(self.egon)
        services.add_members(self.ali, channel.pk, [self.kari])
        services.remove_member(self.ali, channel.pk, self.membership(channel, self.egon).pk)
        self.assertEqual([str(p) for p in read.members(channel)], ['Ali Kaya', 'Kari Nord'])
        removed = self.membership(channel, self.egon)
        self.assertTrue(removed.is_deleted)
        self.assertEqual(removed.deleted_by, self.ali)
        changes = [log.changes['Members'] for log in AuditLog.objects.filter(action='update').order_by('created_at')]
        self.assertEqual(changes, [['Ali Kaya, Egon Berg', 'Ali Kaya, Egon Berg, Kari Nord'],
                                   ['Ali Kaya, Egon Berg, Kari Nord', 'Ali Kaya, Kari Nord']])
        with self.assertRaises(Http404):
            services.post_as(self.egon, channel.pk, 'Still here?')

    def test_a_member_who_is_not_an_owner_manages_nothing(self):
        channel = self.channel(self.egon, self.kari)
        kari = self.membership(channel, self.kari)
        for change in (lambda: services.add_members(self.egon, channel.pk, [self.outsider]),
                       lambda: services.remove_member(self.egon, channel.pk, kari.pk),
                       lambda: services.set_role(self.egon, channel.pk, kari.pk, 'owner')):
            with self.assertRaises(PermissionDenied):
                change()
        with self.assertRaises(Http404):
            services.add_members(self.kari, services.start_direct(self.ali, self.egon).pk, [self.kari])

    def test_a_channel_with_members_keeps_an_owner(self):
        channel = self.channel(self.egon)
        ali = self.membership(channel, self.ali)
        for change in (lambda: services.leave(self.ali, channel.pk),
                       lambda: services.set_role(self.ali, channel.pk, ali.pk, 'member')):
            with self.assertRaisesMessage(ValidationError, 'A channel needs an owner'):
                change()
        services.set_role(self.ali, channel.pk, self.membership(channel, self.egon).pk, 'owner')
        services.leave(self.ali, channel.pk)
        self.assertEqual([(str(p), p.role) for p in read.members(channel)], [('Egon Berg', 'owner')])
        services.leave(self.egon, channel.pk)                           # the last one may go
        self.assertFalse(channel.participants.exists())

    def test_a_channel_its_last_member_leaves_is_deleted_and_frees_its_name(self):
        # F-110: left without members it stayed live, its name taken for good and its history out of everyone's reach.
        channel = self.channel()
        services.post_as(self.ali, channel.pk, 'Before I go')
        services.leave(self.ali, channel.pk)
        stored = Conversation.all_objects.get(pk=channel.pk)
        self.assertTrue(stored.is_deleted)
        self.assertEqual(stored.messages.count(), 1)                    # the history stays, for a restore
        self.assertTrue(AuditLog.objects.filter(entity_id=str(channel.pk), action='delete').exists())
        self.assertNotEqual(self.channel().pk, channel.pk)              # the name is free again

    def test_a_member_added_again_gets_their_row_back_and_unread_starts_from_now(self):
        channel = self.channel(self.egon)
        services.post_as(self.ali, channel.pk, 'Before Kari')
        services.add_members(self.ali, channel.pk, [self.kari])
        self.assertEqual(read.unread_total(self.kari), 0)
        services.post_as(self.ali, channel.pk, 'For everyone')
        self.assertEqual(read.unread_total(self.kari), 1)
        services.leave(self.kari, channel.pk)
        self.assertEqual(read.unread_total(self.kari), 0)
        services.post_as(self.ali, channel.pk, 'While Kari was away')
        services.add_members(self.ali, channel.pk, [self.kari])
        again = self.membership(channel, self.kari)
        self.assertFalse(again.is_deleted)
        self.assertEqual(Participant.all_objects.filter(conversation=channel, user=self.kari).count(), 1)
        self.assertEqual(read.unread_total(self.kari), 0)

    def test_a_removed_member_keeps_their_name_on_their_messages(self):
        channel = self.channel(self.egon)
        services.post_as(self.egon, channel.pk, 'Signing off')
        services.remove_member(self.ali, channel.pk, self.membership(channel, self.egon).pk)
        shown, _earlier = read.timeline(self.membership(channel, self.ali))
        self.assertEqual([(str(m.author), m.body) for m in shown], [('Egon Berg', 'Signing off')])

    def test_the_log_never_holds_what_was_written(self):
        channel = self.channel(self.egon)
        services.post_as(self.ali, channel.pk, 'The secret recipe')
        services.add_members(self.ali, channel.pk, [self.kari])
        self.assertFalse(any('secret' in str(log.changes) or 'secret' in log.entity_label
                             for log in AuditLog.objects.all()))
