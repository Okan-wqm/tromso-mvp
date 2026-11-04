"""The quality of a stored reading: one bitset, 0 is clean. The ONE definition. The table `sensors_quality_flag` holds the
same rows (seeded by migration 0001; a test compares it with these constants), the ingest service (Rust) holds the same
numbers (its tests read the table), and the continuous aggregates filter on `quality & BAD_MASK = 0` with the literal
number, which a test compares with BAD_MASK.

A bad reading (any bit of BAD_MASK) is stored, so the evidence is kept, and left out of the rollups, of the latest value
and of every chart line. The other bits describe a good reading: a heartbeat row, a time taken at receipt."""
from django.utils.translation import gettext_lazy as _

HEARTBEAT = 1          # stored because the heartbeat ran out, not because the value moved past the deadband
RECEIVE_TIME = 2       # the payload had no device time: the time is when the ingest received it
CLOCK_SUSPECT = 4      # the device's time was in the future beyond the allowed skew and was replaced by receipt time
LATE = 8               # older than the newest stored row of the channel: written by the late path
OUT_OF_RANGE = 16      # outside the channel's range (range_min .. range_max): kept as evidence, never dead-lettered
DEVICE_BAD = 32        # the device itself marked the value bad
MAINTENANCE = 64       # the channel was in maintenance when the value arrived
SIMULATED = 128        # a simulated value (the field simulator), never the real water

# (bit, name, is bad, what it means), in bit order.
FLAGS = (
    (HEARTBEAT, 'heartbeat', False, _('Stored because the heartbeat ran out, not because the value moved.')),
    (RECEIVE_TIME, 'receive_time', False, _('The message had no device time: the time is when it was received.')),
    (CLOCK_SUSPECT, 'clock_suspect', False, _('The device time was in the future: the time is when it was received.')),
    (LATE, 'late', False, _('Older than the newest stored value of the channel when it arrived.')),
    (OUT_OF_RANGE, 'out_of_range', True, _('Outside the channel’s range: kept as evidence, not used.')),
    (DEVICE_BAD, 'device_bad', True, _('The device marked the value bad.')),
    (MAINTENANCE, 'maintenance', True, _('The channel was in maintenance.')),
    (SIMULATED, 'simulated', True, _('A simulated value, not the real water.')),
)
BAD_MASK = sum(bit for bit, _name, bad, _text in FLAGS if bad)       # 240
ALL_BITS = sum(bit for bit, *_rest in FLAGS)                          # 255


def is_bad(quality):
    """Whether a reading of this quality is left out of rollups, latest values and chart lines."""
    return bool(quality & BAD_MASK)


def names(quality):
    """The names of the bits set, in bit order: ['heartbeat', 'late']."""
    return [name for bit, name, _bad, _text in FLAGS if quality & bit]


def describe(quality):
    """The meanings of the bits set, translated, for a page."""
    return [text for bit, _name, _bad, text in FLAGS if quality & bit]
