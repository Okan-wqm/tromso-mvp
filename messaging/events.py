"""What Messages tells the rest of the system, once a change is committed.

`message_posted(message_id, conversation_id)` is sent by messaging.services.post after the message is
committed. Nothing in the MVP listens: the pages poll their fragments instead. Two listeners are planned
(README, Messages):
- a push to the browsers and the mobile app (server-sent events or a WebSocket), which tells the members'
  open pages to fetch the same fragments they poll today;
- the AI assistants: a dispatcher that finds the assistants taking part in the conversation, decides whether
  the message is for one of them (a direct conversation with it, or its name mentioned in a channel) and
  queues the work; the worker writes the reply through messaging.services.post as that assistant.
A listener must be quick and must not fail the request: queue the work, do not do it here."""
from django.dispatch import Signal

message_posted = Signal()
