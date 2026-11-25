"""Production › Communication › Messages: the person's conversations beside the one open, the dialogs that start a
direct conversation, create a channel and manage its members, and the fragments the page polls for what is new.

Every view reads through messaging/read.py and writes through messaging/services.py, which hold the rules: a
conversation the person is not a member of answers 404 everywhere (it is not said to exist), what they may not
do 403. The dialogs render in the shared dialog or as a page (core.crud.render_page), as every dialog does.

Live updates are polled (frontend/poll.ts, while the page is in view): the open conversation asks for the
messages after the last one it shows every 5 s, the list for itself every 15 s, the menu's badge for the unread
count every 30 s. A push (server-sent events or a WebSocket, messaging/events.py) replaces the timers later and
asks for the same fragments."""
from django.contrib import messages as flash
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core import navigation, query
from core.crud import done, render_page
from core.ui import is_next

from . import read, services
from .forms import AddMembersForm, ChannelForm, DirectForm, MessageForm, RoleForm

USE, CREATE_CHANNEL = services.USE, services.CREATE_CHANNEL
# Seconds between two polls: the open conversation, the list of conversations.
POLL_MESSAGES, POLL_LIST = 5, 15


def _context(**extra):
    place = navigation.place(USE)
    return {'title': place.entry.label, 'eyebrow': f'{place.section.label} · {place.entry.label}', **extra}


def conversation_url(conversation_id):
    return reverse('messaging:conversation', args=[conversation_id])


def _refused(request, template, context):
    response = render_page(request, template, context)
    response.status_code = 422
    return response


def _no_store(response):
    response['Cache-Control'] = 'no-store'
    return response


def _inbox_template(request):
    """The page of the conversations: the new look (core.ui.is_next) draws the same context as two plates around the same
    polled fragments."""
    return 'messaging/inbox_next.html' if is_next(request) else 'messaging/inbox.html'


def _list_context(user, open_id=None):
    return {'rows': read.inbox(user), 'open_id': open_id,
            'list_url': reverse('messaging:inbox_list') + (f'?{urlencode({"open": open_id})}' if open_id else ''),
            'poll_list': POLL_LIST, 'may_create_channel': user.has_perm(CREATE_CHANNEL)}


# ---- the page ------------------------------------------------------------------------------------------
@permission_required(USE, raise_exception=True)
def inbox(request):
    """The person's conversations; none open."""
    return render_page(request, _inbox_template(request), _context(**_list_context(request.user)))


@permission_required(USE, raise_exception=True)
def conversation(request, pk, form=None):
    """A conversation the person is a member of, beside their list: its latest messages (or the ones before
    `?before=`), the compose form and, for a channel, its members. Opening it marks what it shows as read."""
    participant = services.member(request.user, pk)
    before = query.number(request.GET.get('before', ''))
    shown, earlier = read.timeline(participant, before)
    first_new = read.first_unread(participant, shown)
    reading_latest = before is None
    if reading_latest and shown:
        services.mark_read(participant, shown[-1].pk)
    last_id = shown[-1].pk if shown else 0
    context = _context(
        participant=participant, conversation=participant.conversation, heading=read.title(participant),
        shown=shown, first_new=first_new, earlier_url=f'?{urlencode({"before": shown[0].pk})}' if earlier else '',
        latest_url=conversation_url(pk) if not reading_latest else '',
        poll_url=f"{reverse('messaging:poll', args=[pk])}?{urlencode({'after': last_id})}" if reading_latest else '',
        poll_messages=POLL_MESSAGES, form=form or MessageForm(),
        members=read.members(participant.conversation) if participant.conversation.is_channel else [],
        **_list_context(request.user, open_id=pk))
    if form is not None:
        return _refused(request, _inbox_template(request), context)
    return render_page(request, _inbox_template(request), context)


@require_POST
@permission_required(USE, raise_exception=True)
def post(request, pk):
    """Sends a message; back to the conversation at its end. A refusal shows the page again with the text kept."""
    form = MessageForm(request.POST)
    if form.is_valid():
        try:
            services.post_as(request.user, pk, form.cleaned_data['body'])
        except ValidationError as error:
            form.refused(error)
        else:
            return redirect(f'{conversation_url(pk)}#latest')
    return conversation(request, pk, form=form)


# ---- the fragments the page polls -------------------------------------------------------------------------
@permission_required(USE, raise_exception=True)
def poll(request, pk):
    """The messages after `?after=`, as rows to add to the open conversation, marked read; 204 when there are
    none. X-Poll-Next is the address of the next poll."""
    participant = services.member(request.user, pk)
    last_id = query.number(request.GET.get('after', '')) or 0
    new = read.after(participant, last_id)
    if new:
        services.mark_read(participant, new[-1].pk)
        last_id = new[-1].pk
        response = render(request, 'messaging/_messages.html', {'shown': new, 'participant': participant})
    else:
        response = HttpResponse(status=204)
    response['X-Poll-Next'] = f"{reverse('messaging:poll', args=[pk])}?{urlencode({'after': last_id})}"
    return _no_store(response)


@permission_required(USE, raise_exception=True)
def inbox_list(request):
    """The list of conversations again, with the open one (`?open=`) marked."""
    open_id = request.GET.get('open', '')
    context = _list_context(request.user)
    context['open_id'] = next((row.conversation.pk for row in context['rows'] if str(row.conversation.pk) == open_id),
                              None)
    return _no_store(render(request, 'messaging/_conversation_list.html', context))


@permission_required(USE, raise_exception=True)
def unread(request):
    """The number beside Messages in the menu."""
    return _no_store(HttpResponse(read.unread_badge(request.user).text, content_type='text/plain; charset=utf-8'))


# ---- dialogs ----------------------------------------------------------------------------------------------
@permission_required(USE, raise_exception=True)
def start(request):
    """New message: choose a person; their direct conversation with you opens (the existing one, if any)."""
    form = DirectForm(request.POST or None, user=request.user)
    context = _context(heading=_('New message'), form=form)
    if request.method == 'POST':
        if form.is_valid():
            try:
                found = services.start_direct(request.user, form.cleaned_data['person'])
            except ValidationError as error:
                form.refused(error)
            else:
                return done(request, conversation_url(found.pk))
        return _refused(request, 'messaging/start.html', context)
    return render_page(request, 'messaging/start.html', context)


@permission_required(CREATE_CHANNEL, raise_exception=True)
def create_channel(request):
    """New channel: a name and its first members; the person who creates it is its owner."""
    form = ChannelForm(request.POST or None, user=request.user)
    context = _context(heading=_('New channel'), form=form)
    if request.method == 'POST':
        if form.is_valid():
            try:
                channel = services.create_channel(request.user, form.cleaned_data['name'],
                                                  form.cleaned_data['members'])
            except ValidationError as error:
                form.refused(error)
            else:
                flash.success(request, _('Channel %(name)s created.') % {'name': channel.name})
                return done(request, conversation_url(channel.pk))
        return _refused(request, 'messaging/channel_form.html', context)
    return render_page(request, 'messaging/channel_form.html', context)


def _members_page(request, pk, form=None, error=None):
    participant = services.member(request.user, pk)
    channel = participant.conversation
    if not channel.is_channel:
        return redirect(conversation_url(pk))
    owner = participant.is_owner
    context = _context(heading=_('Members of %(channel)s') % {'channel': channel.name}, conversation=channel,
                       participant=participant, members=read.members(channel), is_owner=owner,
                       form=(form or AddMembersForm(conversation=channel)) if owner else None, error=error,
                       back_url=conversation_url(pk))
    if form is not None or error is not None:
        return _refused(request, 'messaging/members.html', context)
    return render_page(request, 'messaging/members.html', context)


@permission_required(USE, raise_exception=True)
def members(request, pk):
    """A channel's members: an owner adds people, removes members and makes them owners; anyone can leave."""
    return _members_page(request, pk)


def _member_change(request, pk, change):
    """Runs a change of the channel's members and opens the members again, or shows why it was refused."""
    try:
        change()
    except ValidationError as error:
        return _members_page(request, pk, error=' '.join(error.messages))
    return done(request, reverse('messaging:members', args=[pk]), stay=True)


@require_POST
@permission_required(USE, raise_exception=True)
def add_members(request, pk):
    channel = services.owner(request.user, pk).conversation
    form = AddMembersForm(request.POST, conversation=channel)
    if not form.is_valid():
        return _members_page(request, pk, form=form)
    try:
        services.add_members(request.user, pk, form.cleaned_data['people'])
    except ValidationError as error:
        form.refused(error)
        return _members_page(request, pk, form=form)
    return done(request, reverse('messaging:members', args=[pk]), stay=True)


@require_POST
@permission_required(USE, raise_exception=True)
def remove_member(request, pk, participant):
    return _member_change(request, pk, lambda: services.remove_member(request.user, pk, participant))


@require_POST
@permission_required(USE, raise_exception=True)
def set_role(request, pk, participant):
    form = RoleForm(request.POST)
    role = form.cleaned_data['role'] if form.is_valid() else ''
    return _member_change(request, pk, lambda: services.set_role(request.user, pk, participant, role))


@permission_required(USE, raise_exception=True)
def leave(request, pk):
    """Leave a channel: asked first, then back to the list."""
    participant = services.member(request.user, pk)
    channel = participant.conversation
    if not channel.is_channel:
        return redirect(conversation_url(pk))
    context = _context(heading=_('Leave channel'), back_url=conversation_url(pk), action_label=_('Leave'),
                       question=_('Leave %(channel)s?') % {'channel': channel.name},
                       detail=_('You stop seeing its messages. Your messages stay, with your name; an owner can add '
                                'you again.'))
    if request.method == 'POST':
        try:
            services.leave(request.user, pk)
        except ValidationError as error:
            return _refused(request, 'messaging/confirm.html', {**context, 'error': ' '.join(error.messages)})
        flash.success(request, _('You left %(channel)s.') % {'channel': channel.name})
        return done(request, reverse('messaging:inbox'))
    return render_page(request, 'messaging/confirm.html', context)


@permission_required(USE, raise_exception=True)
def delete_message(request, pk, message):
    """Delete one of your messages: asked first; the conversation then shows it as deleted, to everyone."""
    back = conversation_url(pk)     # no fragment: from the dialog the page loads again, without the message's text
    if request.method == 'POST':
        services.delete_message(request.user, pk, message)
        return done(request, back)
    shown = services.own_message(request.user, pk, message)
    if shown.is_deleted:
        return redirect(back)
    return render_page(request, 'messaging/confirm.html', _context(
        heading=_('Delete message'), back_url=back, action_label=_('Delete'), danger=True, quote=shown.body,
        question=_('Delete this message?'),
        detail=_('Everyone in the conversation sees that a message was deleted, not what it said.')))

