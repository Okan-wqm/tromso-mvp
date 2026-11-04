"""What the data map (core.datamap) cannot read from the code, for the messaging tables: it has no tabs, its pages are
the inbox, a conversation and its dialogs, and one write path (messaging/services.py) serves them all."""
from core.datamap import Screen, gap, no, system

from . import forms, views

NOT_BUILT = 'not built yet: nothing creates an assistant, the AI module will (README, Messages)'

SCREENS = {
    'Assistant': Screen(
        create=gap(NOT_BUILT), edit=gap(NOT_BUILT), delete=gap(NOT_BUILT), read=gap(NOT_BUILT),
        restore=no('not built yet'),
        columns={'*': system('written by the AI module, which does not exist yet')},
    ),
    'Conversation': Screen(
        create=(views.start, views.create_channel),
        edit=gap('no page renames a channel once it is created'),
        delete=gap('no page deletes a conversation or a channel; a person only leaves a channel'),
        read=(views.inbox, views.inbox_list, views.conversation),
        restore=no('nothing deletes a conversation yet'),
        note='A direct conversation is made by choosing a person; the existing one opens if there is one.',
        forms=(forms.DirectForm, forms.ChannelForm),
        columns={'kind': system('a direct conversation or a channel, by the dialog used')},
    ),
    'Participant': Screen(
        create=(views.start, views.create_channel, views.add_members),
        edit=(views.set_role,),
        delete=(views.remove_member, views.leave),
        read=(views.conversation, views.members),
        restore=no('adding the person again brings the same row back'),
        note='Leaving or being removed is a soft delete; adding the person again brings the same row back.',
        forms=(forms.RoleForm, forms.DirectForm, forms.ChannelForm, forms.AddMembersForm),
        fills={'person': 'user', 'members': 'user', 'people': 'user'},
        columns={'conversation': system('the conversation the person joins'),
                 'assistant': gap('assistants cannot be added yet: the AI module will'),
                 'last_read': system('the last message read: moved when the conversation is opened or polled')},
    ),
    'Message': Screen(
        create=(views.post,),
        edit=no('a message is written once and never edited'),
        delete=(views.delete_message,),
        read=(views.conversation, views.poll, views.inbox_list),
        note='The author deletes their own message: the row stays, shown as deleted, the text is never served again.',
        forms=(forms.MessageForm,),
        columns={'conversation': system('the conversation the message is posted to'),
                 'author': system('the sender, as a participant of the conversation')},
    ),
}
