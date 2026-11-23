"""Whether anything an alarm reads has changed since the alarm worker's last pass (alarms/worker.py looks every tick, and
passes at once when it has): the reaction within the owner's 10 s, from a value's commit to its alarm. A token of what
changes, read in three short statements, never a second judgement of what changed:

- the sensors' values: the ingest writes each channel's newest value into `sensors_channel_state` in the same
  transaction as its readings, and every row it inserts or updates carries that transaction's id (`xmin`), so the rows'
  count and the sum of their ids move with every batch the ingest commits, whatever device clock stamped the values;
- every record written through the platform's write paths (a water sample or its void, a water limit, a stock
  operation, a sensor binding, an alarm rule or recipient rule, an acknowledgement): each writes its activity-log entry
  in the same transaction (core/audit.py), so `core.audit.revision()` moves.
What only time moves (a value going stale, the delays, escalation) is the sweep's. The token is read BEFORE the pass it
stands for, so a change that lands during the pass makes the next look differ: none is lost, at worst one pass more.

Why not LISTEN/NOTIFY (the alarm plan's wake-up): a NOTIFY inside the ingest's transaction ties the ingest's commits to
every listener, and a listener that stalls makes those commits fail (measured, live-arch ROUND2-F §3). Looking costs a
few milliseconds a tick and cannot stop the ingest. The alarms never read a precomputed water store (live-arch stage 3):
the pass reads the live tables (farm/water/read.py), and so does this."""
from django.db import connection

from core import audit

CHANNELS = ('SELECT count(*), coalesce(sum(xmin::text::bigint), 0) FROM sensors_channel_state')


def token():
    """What the worker compares from one look to the next."""
    with connection.cursor() as cursor:
        cursor.execute(CHANNELS)
        channels = tuple(cursor.fetchone())
    return channels, audit.revision()
