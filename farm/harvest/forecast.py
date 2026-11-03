"""When a batch in a unit reaches its target weight: the feeding protocols' estimate now, walked forward a day at a
time, computed on read and never stored (harvest.md §3.6).

- The start is today's estimated average (farm/feeding/projection.py: the estimate from the last measured point,
  after today's feedings).
- Each day ahead reads the ration's basis of that day at the weight reached (farm/feeding/ration.py, Policy.basis):
  the protocol in force, the band at that weight, its SFR at the temperature. The fish eat the day's ration and
  grow by it ÷ the band's expected FCR: w × SFR / 100 ÷ FCR grams per fish (feed above the ration is never growth,
  owner decision Q4).
- The temperature is the unit's latest usable one held constant (the policy reads "now" for every day from today),
  and the page says at what temperature. Temperature scenarios come later.
- A fasting day ahead (a planned harvest or transport, farm/handling/fasting.py) gives no growth.
- No protocol, a weight outside its bands, no temperature or one outside its table stops the walk: the page shows
  the basis's reason, never a default. Two years ahead without reaching it stops too.
- Weight per fish needs no mortality; nothing is said about the biomass then."""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.utils.translation import gettext as _

from farm.feeding import read as feeding_read
from farm.handling import fasting
from farm.stock.dates import local_today

HUNDRED = Decimal(100)
HORIZON_DAYS = 730


@dataclass(frozen=True)
class Forecast:
    """The estimated average now, the day the target is reached (None when it is not), and why not."""
    now_g: Decimal
    day: date = None
    temperature_c: Decimal = None
    why: str = ''

    @property
    def reached(self):
        return self.day is not None


def forecasts(shares, targets):
    """{(unit id, batch id): Forecast} of the shares ((unit, stock.read BatchShare) pairs): the estimate now, and,
    for a batch with a target (`targets`: batch id -> grams), the day it is reached. One projection walk for all."""
    wanted = list(shares)
    if not wanted:
        return {}
    today = {unit.pk: local_today(unit) for unit, _share in wanted}
    projection = feeding_read.project(list(today), [(unit_id, day) for unit_id, day in today.items()])
    units = list({unit.pk: unit for unit, _share in wanted}.values())
    first, last = min(today.values()), max(today.values()) + timedelta(days=HORIZON_DAYS)
    fasts = fasting.fasts(units, first, last)
    found = {}
    for unit, share in wanted:
        unit_day = projection.days.get((unit.pk, today[unit.pk]))
        estimate = next((item for item in (unit_day.shares if unit_day else []) if item.batch_id == share.batch.pk),
                        None)
        if estimate is None:
            continue
        target = targets.get(share.batch.pk)
        found[(unit.pk, share.batch.pk)] = (
            Forecast(estimate.end_g) if target is None else
            _walk(projection.projector.policy, unit, share.batch, today[unit.pk], estimate.end_g, target, fasts))
    return found


def _walk(policy, unit, batch, today, weight, target, fasts):
    start = weight
    day, temperature = today, None
    for _n in range(HORIZON_DAYS + 1):
        if weight >= target:
            return Forecast(start, day, temperature)
        day += timedelta(days=1)
        if (unit.pk, day) in fasts:
            continue
        basis = policy.basis(unit.pk, batch.pk, day, weight)
        if not basis.has_ration or basis.fcr is None:
            return Forecast(start, why=basis.why(batch))
        temperature = basis.temperature.value_c
        weight += weight * basis.sfr.value / HUNDRED / basis.fcr
    return Forecast(start, temperature_c=temperature, why=_('Not reached within %(days)d days at this rate.') % {
        'days': HORIZON_DAYS})
