"""The words of the sensors panels of their own, one source for both looks: the classic templates read them through the
template tag `sensor_words` (templatetags/sensors_words.py) and the new look's panels (core/formpanels.py, Resource.next_panels)
from here. Each is the msgid the template said itself."""
from django.utils.functional import lazy
from django.utils.translation import gettext_lazy as _

CHANNELS = _('Channels')
PLACEMENT = _('Placement')
CHANNEL = _('Channel')
QUANTITY = _('Quantity')
VALUE = _('Value')
HEARTBEAT_S = _('Heartbeat (s)')
STATE = _('State')
NO_CHANNELS_YET_ADD_THEM_ON = _('No channels yet: add them on the Channels page.')
PLACED_AT = _('Placed at')
NOT_PLACED_OUT_OF_THE_WATER = _('Not placed: out of the water, its readings belong to no place.')
MOVE_DEVICE = _('Move device')
WHERE = _('Where')
FROM = _('From')
UNTIL = _('Until')
NOW = _('now')
NEVER_PLACED_YET = _('Never placed yet.')
REPLACING_THE_SECRET_MAKES_A_NEW = _('Replacing the secret makes a new one, shown once. The old one stops working once the broker’s '
      'files are written again.')
REPLACE_THE_SECRET = _('Replace the secret')

# For a template: {name in lower case: the words}, said as the template's trans tag said them (a msgid's per cent signs are
# doubled, as a template's msgid has them: core.formpanels.said).
_said = lazy(lambda text: str(text).replace('%%', '%'), str)
WORDS = {name.lower(): _said(value) for name, value in dict(globals()).items() if name.isupper() and name != 'WORDS'}


def fresh_for(channel):
    """How long a channel's value stays fresh, on its Storing tab."""
    from django.utils import formats
    from django.utils.translation import gettext
    return gettext('Channel number %(number)s. A value is fresh for %(heartbeats)s heartbeats: %(seconds)s seconds.') % {
        'number': formats.localize(channel.channel_no), 'heartbeats': formats.localize(channel.fresh_heartbeats),
        'seconds': formats.localize(channel.fresh_s)}
