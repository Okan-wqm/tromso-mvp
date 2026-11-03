"""Messages through the pages, checked against the stored rows: the menu and its badge, the role matrix, the
conversation page and its polled fragments, the dialogs, who is refused, the languages and the database viewer."""
from django.contrib.auth import get_user_model
from django.urls import reverse

from core import access, navigation
from core.models import Profile

from .. import read, services
from ..models import Conversation, Message, Participant
from . import CHANNELS, MessagingTestCase, person

MODAL = {'X-Modal': '1'}


def conversation_url(conversation):
    return reverse('messaging:conversation', args=[conversation.pk])


class PageTestCase(MessagingTestCase):
    def setUp(self):
        self.client.force_login(self.ali)

    def as_user(self, user):
        self.client.force_login(user)

    def post_message(self, conversation, body):
        return self.client.post(reverse('messaging:post', args=[conversation.pk]), {'body': body})


class MenuAndAccessTests(PageTestCase):
    def test_messages_sit_under_production_communication_with_the_unread_count(self):
        direct = services.start_direct(self.egon, self.ali)
        services.post_as(self.egon, direct.pk, 'One')
        services.post_as(self.egon, direct.pk, 'Two')
        response = self.client.get(reverse('messaging:inbox'))
        self.assertEqual(response.context['workspace']['key'], 'production')
        sections = [(s['label'], [e['label'] for g in s['groups'] for e in g['entries']])
                    for s in response.context['rail_sections']]
        self.assertEqual(sections[-1], ('Communication', ['Messages']))
        self.assertContains(response, f'<span class="rail-badge" data-poll="{reverse("messaging:unread")}" '
                                      f'data-poll-every="30">2</span>', html=True)
        self.assertContains(response, '<span class="menu-badge">2</span>', html=True)   # beside the panel too
        self.assertEqual(str(navigation.place('messaging.view_conversation').path), 'Production · Communication')

    def test_the_role_matrix_offers_read_and_create_channels(self):
        areas = {area.model: area for area in access.areas()}
        self.assertEqual((str(areas['messaging.Conversation'].label), areas['messaging.Conversation'].actions),
                         ('Messages', ('view', 'add')))

    def test_messages_alone_bring_the_production_panel(self):
        self.as_user(self.egon)
        response = self.client.get(reverse('messaging:inbox'))
        self.assertEqual([p['key'] for p in response.context['workspaces']], ['company', 'production'])
        self.assertNotContains(response, reverse('messaging:create_channel'))      # Create is not given

    def test_without_the_area_everything_is_refused(self):
        direct = services.start_direct(self.ali, self.egon)
        self.as_user(self.outsider)
        for url in (reverse('messaging:inbox'), reverse('messaging:inbox_list'), reverse('messaging:unread'),
                    reverse('messaging:start'), reverse('messaging:create_channel'), conversation_url(direct),
                    reverse('messaging:poll', args=[direct.pk])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.post_message(direct, 'Hi').status_code, 403)
        self.assertNotContains(self.client.get(reverse('home')), 'rail-badge')
        self.assertFalse(Message.objects.exists())


class ConversationPageTests(PageTestCase):
    def setUp(self):
        super().setUp()
        self.direct = services.start_direct(self.ali, self.egon)

    def test_a_message_sent_through_the_page_is_stored_and_shown(self):
        response = self.post_message(self.direct, 'Feed T-01 twice today')
        self.assertRedirects(response, f'{conversation_url(self.direct)}#latest', fetch_redirect_response=False)
        message = Message.objects.get()
        self.assertEqual((message.body, message.author.user, message.conversation), ('Feed T-01 twice today', self.ali,
                                                                                     self.direct))
        self.as_user(self.egon)
        page = self.client.get(conversation_url(self.direct))
        self.assertContains(page, 'Feed T-01 twice today')
        self.assertContains(page, '<span>New</span>', html=True)
        self.assertContains(page, '<h2 class="chat-title">Ali Kaya</h2>', html=True)

    def test_an_empty_message_shows_the_reason_and_stores_nothing(self):
        response = self.post_message(self.direct, '   ')
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'This field is required.', status_code=422)
        self.assertFalse(Message.objects.exists())

    def test_opening_the_conversation_marks_what_it_shows_as_read(self):
        services.post_as(self.egon, self.direct.pk, 'One')
        services.post_as(self.egon, self.direct.pk, 'Two')
        self.assertEqual(read.unread_total(self.ali), 2)
        self.client.get(conversation_url(self.direct))
        self.assertEqual(read.unread_total(self.ali), 0)
        self.assertEqual(Participant.objects.get(conversation=self.direct, user=self.ali).last_read,
                         Message.objects.last())

    def test_the_poll_brings_the_new_messages_and_marks_them_read(self):
        first = services.post_as(self.egon, self.direct.pk, 'One')
        page = self.client.get(conversation_url(self.direct))
        poll = reverse('messaging:poll', args=[self.direct.pk])
        self.assertEqual(page.context['poll_url'], f'{poll}?after={first.pk}')
        nothing = self.client.get(page.context['poll_url'])
        self.assertEqual(nothing.status_code, 204)
        self.assertEqual(nothing['X-Poll-Next'], f'{poll}?after={first.pk}')
        second = services.post_as(self.egon, self.direct.pk, 'Two is new')
        self.assertEqual(read.unread_total(self.ali), 1)
        new = self.client.get(page.context['poll_url'])
        self.assertEqual(new.status_code, 200)
        self.assertEqual(new['X-Poll-Next'], f'{poll}?after={second.pk}')
        self.assertEqual(new['Cache-Control'], 'no-store')
        self.assertContains(new, 'Two is new')
        self.assertNotContains(new, '>One<')
        self.assertEqual(read.unread_total(self.ali), 0)

    def test_the_list_and_the_badge_fragments(self):
        services.post_as(self.egon, self.direct.pk, 'Hello Ali')
        badge = self.client.get(reverse('messaging:unread'))
        self.assertEqual((badge.content.decode(), badge['Cache-Control']), ('1', 'no-store'))
        listed = self.client.get(reverse('messaging:inbox_list'))
        self.assertContains(listed, 'Egon Berg')
        self.assertContains(listed, 'Hello Ali')
        self.assertContains(listed, '<span class="chat-unread">1<span class="sr-only"> unread</span></span>', html=True)
        opened = self.client.get(reverse('messaging:inbox_list'), {'open': self.direct.pk})
        self.assertNotContains(opened, 'chat-unread')                 # the open one is being read
        self.assertContains(opened, 'aria-current="page"')
        self.assertEqual(self.client.get(reverse('messaging:unread')).content.decode(), '1')

    def test_a_non_member_is_told_nothing(self):
        message = services.post_as(self.ali, self.direct.pk, 'Between us')
        self.as_user(self.kari)
        for url in (conversation_url(self.direct), reverse('messaging:poll', args=[self.direct.pk]),
                    reverse('messaging:members', args=[self.direct.pk]),
                    reverse('messaging:delete_message', args=[self.direct.pk, message.pk])):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn('Between us', response.content.decode())
        self.assertEqual(self.post_message(self.direct, 'Let me in').status_code, 404)
        self.assertEqual(self.client.post(reverse('messaging:delete_message', args=[self.direct.pk, message.pk]))
                         .status_code, 404)
        self.assertEqual(Message.objects.count(), 1)
        self.assertFalse(Message.objects.get().is_deleted)
        self.assertNotContains(self.client.get(reverse('messaging:inbox')), 'Between us')

    def test_deleting_a_message_through_the_page(self):
        message = services.post_as(self.ali, self.direct.pk, 'Wrong unit, sorry')
        url = reverse('messaging:delete_message', args=[self.direct.pk, message.pk])
        confirm = self.client.get(url, headers=MODAL)
        self.assertContains(confirm, 'Delete this message?')
        self.assertContains(confirm, 'Wrong unit, sorry')
        self.as_user(self.egon)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.as_user(self.ali)
        response = self.client.post(url, headers=MODAL)
        self.assertEqual(response['X-Modal-Redirect'], conversation_url(self.direct))
        stored = Message.objects.get()
        self.assertEqual((stored.is_deleted, stored.deleted_by), (True, self.ali))
        self.as_user(self.egon)
        page = self.client.get(conversation_url(self.direct))
        self.assertContains(page, 'Message deleted')
        self.assertNotContains(page, 'Wrong unit')
        self.assertNotContains(self.client.get(reverse('messaging:inbox')), 'Wrong unit')

    def test_earlier_messages_are_a_link_away(self):
        for number in range(read.PAGE + 5):
            services.post_as(self.egon, self.direct.pk, f'Message {number}')
        page = self.client.get(conversation_url(self.direct))
        self.assertEqual(len(page.context['shown']), read.PAGE)
        self.assertContains(page, 'Show earlier messages')
        earlier = self.client.get(conversation_url(self.direct) + page.context['earlier_url'])
        self.assertEqual([m.body for m in earlier.context['shown']], [f'Message {n}' for n in range(5)])
        self.assertEqual(earlier.context['poll_url'], '')               # an older page does not poll
        self.assertContains(earlier, 'Back to the latest messages')


class DialogTests(PageTestCase):
    def test_new_message_opens_the_one_conversation_with_that_person(self):
        url = reverse('messaging:start')
        form = self.client.get(url, headers=MODAL)
        self.assertContains(form, 'Egon Berg')
        self.assertNotContains(form, 'olav')                         # may not use Messages
        response = self.client.post(url, {'person': self.egon.pk}, headers=MODAL)
        direct = Conversation.objects.get()
        self.assertEqual(response['X-Modal-Redirect'], conversation_url(direct))
        self.as_user(self.egon)
        self.client.post(url, {'person': self.ali.pk}, headers=MODAL)
        self.assertEqual(Conversation.objects.count(), 1)
        refused = self.client.post(url, {'person': self.outsider.pk}, headers=MODAL)
        self.assertEqual(refused.status_code, 422)

    def test_new_channel_with_members_and_its_permission(self):
        url = reverse('messaging:create_channel')
        response = self.client.post(url, {'name': 'Hall A', 'members': [self.egon.pk]}, headers=MODAL)
        channel = Conversation.objects.get(kind='channel')
        self.assertEqual(response['X-Modal-Redirect'], conversation_url(channel))
        self.assertEqual({(p.user, p.role) for p in channel.participants.all()},
                         {(self.ali, 'owner'), (self.egon, 'member')})
        again = self.client.post(url, {'name': 'HALL A'}, headers=MODAL)
        self.assertContains(again, 'A channel with this name already exists.', status_code=422)
        self.as_user(self.egon)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {'name': 'Mine'}).status_code, 403)
        self.assertEqual(Conversation.objects.count(), 1)

    def test_an_owner_manages_the_members_through_the_dialog(self):
        channel = services.create_channel(self.ali, 'Hall A', [self.egon])
        members = reverse('messaging:members', args=[channel.pk])
        page = self.client.get(members, headers=MODAL)
        self.assertContains(page, 'Kari Nord')                       # can be added
        added = self.client.post(reverse('messaging:add_members', args=[channel.pk]), {'people': [self.kari.pk]},
                                 headers=MODAL)
        self.assertEqual(added['X-Modal-Load'], members)
        kari = Participant.objects.get(conversation=channel, user=self.kari)
        self.client.post(reverse('messaging:set_role', args=[channel.pk, kari.pk]), {'role': 'owner'}, headers=MODAL)
        egon = Participant.objects.get(conversation=channel, user=self.egon)
        self.client.post(reverse('messaging:remove_member', args=[channel.pk, egon.pk]), headers=MODAL)
        self.assertEqual({(p.user, p.role) for p in channel.participants.all()},
                         {(self.ali, 'owner'), (self.kari, 'owner')})

    def test_a_member_sees_the_members_and_changes_nothing(self):
        channel = services.create_channel(self.ali, 'Hall A', [self.egon, self.kari])
        self.as_user(self.egon)
        page = self.client.get(reverse('messaging:members', args=[channel.pk]))
        self.assertContains(page, 'Kari Nord')
        self.assertNotContains(page, 'Make owner')
        kari = Participant.objects.get(conversation=channel, user=self.kari)
        for url, data in ((reverse('messaging:remove_member', args=[channel.pk, kari.pk]), {}),
                          (reverse('messaging:set_role', args=[channel.pk, kari.pk]), {'role': 'owner'}),
                          (reverse('messaging:add_members', args=[channel.pk]), {'people': [self.ali.pk]})):
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, data).status_code, 403)
        self.assertEqual(channel.participants.count(), 3)

    def test_the_last_owner_is_told_why_they_cannot_leave_and_others_leave(self):
        channel = services.create_channel(self.ali, 'Hall A', [self.egon])
        leave = reverse('messaging:leave', args=[channel.pk])
        refused = self.client.post(leave, headers=MODAL)
        self.assertContains(refused, 'A channel needs an owner', status_code=422)
        self.as_user(self.egon)
        self.assertContains(self.client.get(leave, headers=MODAL), 'Leave Hall A?')
        response = self.client.post(leave, headers=MODAL)
        self.assertEqual(response['X-Modal-Redirect'], reverse('messaging:inbox'))
        self.assertEqual([p.user for p in channel.participants.all()], [self.ali])
        self.assertEqual(self.client.get(conversation_url(channel)).status_code, 404)


class SecondPersonWritesToTheAdminTests(PageTestCase):
    """The path the owner walks: a second person, given Messages through a role, writes to the platform admin
    through the pages, and the admin sees it in the badge, the list and the conversation."""

    def test_a_new_person_writes_to_the_admin(self):
        admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        newcomer = person('nils', *CHANNELS)
        self.as_user(newcomer)
        self.assertContains(self.client.get(reverse('messaging:start')), 'root')
        opened = self.client.post(reverse('messaging:start'), {'person': admin.pk})
        direct = Conversation.objects.get()
        self.assertRedirects(opened, conversation_url(direct))
        self.post_message(direct, 'Hello, this is Nils from Hall A.')
        self.as_user(admin)
        home = self.client.get(reverse('production_home'))
        self.assertContains(home, 'data-poll-every="30">1</span>')
        self.assertContains(self.client.get(reverse('messaging:inbox')), 'Hello, this is Nils from Hall A.')
        self.assertContains(self.client.get(conversation_url(direct)), 'Hello, this is Nils from Hall A.')
        self.assertEqual(self.client.get(reverse('messaging:unread')).content.decode(), '')
        self.post_message(direct, 'Welcome, Nils.')
        self.assertEqual(Message.objects.filter(conversation=direct).count(), 2)


class LanguageTests(PageTestCase):
    def test_every_page_and_dialog_renders_in_each_language(self):
        channel = services.create_channel(self.ali, 'Hall A', [self.egon])
        message = services.post_as(self.ali, channel.pk, 'Hello')
        services.post_as(self.egon, channel.pk, 'Hi')
        urls = [reverse('messaging:inbox'), conversation_url(channel), reverse('messaging:start'),
                reverse('messaging:create_channel'), reverse('messaging:members', args=[channel.pk]),
                reverse('messaging:leave', args=[channel.pk]),
                reverse('messaging:delete_message', args=[channel.pk, message.pk]), reverse('messaging:inbox_list')]
        words = {'en': 'New message', 'tr': 'Yeni mesaj', 'nb': 'Ny melding'}
        for language, word in words.items():
            Profile.objects.update_or_create(user=self.ali, defaults={'language': language})
            self.client.force_login(self.ali)
            for url in urls:
                for headers in ({}, MODAL):
                    with self.subTest(language=language, url=url, modal=bool(headers)):
                        response = self.client.get(url, headers=headers)
                        self.assertEqual(response.status_code, 200)
                        self.assertNotIn('%(', response.content.decode())
                        self.assertEqual(response['Content-Language'], language)
            self.assertContains(self.client.get(reverse('messaging:inbox')), word)


class DatabaseViewerTests(PageTestCase):
    def test_the_viewer_shows_who_wrote_when_but_never_what(self):
        direct = services.start_direct(self.ali, self.egon)
        services.post_as(self.egon, direct.pk, 'The secret recipe')
        admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.as_user(admin)
        grid = self.client.get(reverse('core:database_table', args=['messages']))
        self.assertEqual(len(grid.context['grid'].rows), 1)
        self.assertNotContains(grid, 'secret')
        self.assertContains(grid, 'masked')
        # It cannot be found by its text: the search box does not look in it, its filter and sort are ignored.
        for query, rows in (({'q': 'secret'}, 0), ({'f_body': 'nothing like it'}, 1), ({'sort': 'body'}, 1)):
            response = self.client.get(reverse('core:database_table', args=['messages']), query)
            self.assertNotContains(response, 'The secret recipe')
            self.assertEqual(len(response.context['grid'].rows), rows, query)
        export = self.client.get(reverse('core:database_export', args=['messages']))
        self.assertNotIn('secret', b''.join(export.streaming_content).decode())
        for table in ('conversations', 'conversation_participants', 'assistants'):
            self.assertEqual(self.client.get(reverse('core:database_table', args=[table])).status_code, 200)
