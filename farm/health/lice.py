"""The statutory sea-lice rules, as lakselusforskriften (FOR-2012-12-05-1140, last amended by
FOR-2023-12-14-2087) states them; read on lovdata.no on 2026-11-03.

- § 8: the average of adult female lice per fish on the site must at all times be below ("færre enn") 0.2
  from Monday of week 16 to Sunday of week 21 in Nord-Trøndelag and southwards, and from Monday of week 21
  to Sunday of week 26 in Nordland, Troms and Finnmark; below 0.5 the rest of the year. A site at the limit
  is over it.
- Vedlegg 1 point 2 and 3: at least 20 fish are counted in every cage from Monday of week 14 to Sunday of
  week 21 (Nord-Trøndelag and southwards) or of week 19 to week 26 (Nordland, Troms and Finnmark), at least
  10 the rest of the year.
- Vedlegg 1 point 6: a cage's average per stage is the lice of that stage on all fish examined in it divided
  by the fish examined; the site's average is the sum of the cages' averages divided by the number of
  cages. Every cage weighs the same, however many fish were examined in it (the source weighted the cages
  by their fish, HLT-22).
- § 6: lice are counted at least every 7 days at 4 °C or above, every 14 days below.

The weeks are ISO weeks (Monday to Sunday), as the regulation's "mandag i uke … søndag i uke" reads. Which
area a site is in is set on the site (Facility › Sites); a site without one is judged by the stricter of the
two areas, and the page says so.

Which treatments the weekly lice report lists: those given for sea lice (the reason). A sea-lice medicine given for
another reason is right sometimes (hydrogen peroxide is also an AGD treatment) and is never refused, but it is left out of
the report: `left_out_of_lice_report` is that rule, read by the treatment's dialog (a warning) and the report (audit F-083,
F-239)."""
from decimal import Decimal

SOUTH, NORTH = 'south', 'north'
AREAS = (SOUTH, NORTH)
LIMIT = Decimal('0.5')
SPRING_LIMIT = Decimal('0.2')
# The weeks of the lower limit, and of the larger sample, both ends included.
SPRING_WEEKS = {SOUTH: (16, 21), NORTH: (21, 26)}
LARGE_SAMPLE_WEEKS = {SOUTH: (14, 21), NORTH: (19, 26)}
SAMPLE, LARGE_SAMPLE = 10, 20


def _within(week, weeks):
    first, last = weeks
    return first <= week <= last


def limit(area, week):
    """The most adult female lice per fish a site may average in this ISO week (it must stay below it); for a
    site without an area, the stricter of the two."""
    if area not in AREAS:
        return min(limit(known, week) for known in AREAS)
    return SPRING_LIMIT if _within(week, SPRING_WEEKS[area]) else LIMIT


def minimum_fish(area, week):
    """The fewest fish to count in a cage in this ISO week; for a site without an area, the larger of the two."""
    if area not in AREAS:
        return max(minimum_fish(known, week) for known in AREAS)
    return LARGE_SAMPLE if _within(week, LARGE_SAMPLE_WEEKS[area]) else SAMPLE


def over(average, area, week):
    """Whether a site's average of adult female lice breaks the limit: it must be below it."""
    return average >= limit(area, week)


def left_out_of_lice_report(medicine, reason):
    """Whether a treatment with `medicine` for `reason` is a sea-lice medicine the weekly sea-lice report leaves out: it
    lists the treatments for sea lice only."""
    from farm.models.health import MedicineKind, TreatmentReason   # the models read this module's limits (Site)
    return medicine is not None and medicine.kind == MedicineKind.LICE and reason != TreatmentReason.SEA_LICE
