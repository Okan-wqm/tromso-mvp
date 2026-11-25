"""THE slot rule of a monitoring wall of fitted cards: how many columns and rows of equal cells a screen is cut into,
as a pure function (no model, no query). frontend/wall/slots.ts is the same rule for the browser, which is where the
screen's size is known; this is the authority, as validate.py is for a layout's geometry, and both run
monitoring/tests/slot_vectors.json.

A fitted card is `mw` units wide and `mh` high (its template's measure, monitoring/models.py CardTemplate.measure) and
every length inside it is a multiple of its unit, so the unit a cell gives is

    min((cell width - the card's own padding) / mw, (cell height - the card's own padding) / mh)

Of every grid whose cells hold all the cards, the rule takes the one that gives the largest unit (with equal units, the
fewer cells). When that unit is under the smallest that can be read (`min_u`; never under FLOOR), the wall turns pages
instead of shrinking the type: the grid with the MOST cells whose unit can still be read (with equal cells, the larger
unit). When no grid reaches it (a board read from farther than its screen allows, or a window too small), ONE card a
page at the largest unit a cell gives: never the densest grid, whose type would be the smallest of all. A cell is never
lower than `mh` units of FLOOR: a window too low for one row scrolls."""
import math
from collections import namedtuple

# Under this unit (px) a card's smallest text, 0.8 of it, is under 11 px.
FLOOR = 14
MAX_COLS, MAX_ROWS = 16, 12
# A FULL-HEIGHT card (its measure is higher than wide: the Big card, read from across the room) keeps at least this
# share of the unit one card alone on the screen would have: the wall turns pages rather than set more of them side by
# side and shrink them (`fill_unit` is its `min_u`).
FILL = 0.97
EPSILON = 1e-6

Slots = namedtuple('Slots', 'cols rows u pages')


def slots(count, width, height, gap, mw, mh, min_u=FLOOR, pad_x=0, pad_y=0):
    """The grid (Slots) for `count` cards on a screen `width` by `height` px (the room under the band) with `gap` px
    between cells, for cards of `mw` by `mh` units whose own padding and borders take `pad_x` and `pad_y` px."""
    least = max(min_u, FLOOR)
    whole = paged = largest = None
    for cols in range(1, MAX_COLS + 1):
        for rows in range(1, MAX_ROWS + 1):
            room = (height - (rows - 1) * gap) / rows
            cell = max(room, mh * FLOOR + pad_y)
            u = min(((width - (cols - 1) * gap) / cols - pad_x) / mw, (cell - pad_y) / mh)
            fits = cell <= room + 0.5
            cells = cols * rows
            found = Slots(cols, rows, u, max(1, math.ceil(count / cells)))
            if cells == 1:
                largest = found
            if fits and cells >= count and (whole is None or u > whole.u + EPSILON or (
                    abs(u - whole.u) <= EPSILON and cells < whole.cols * whole.rows)):
                whole = found
            if u >= least - EPSILON and (fits or rows == 1) and (
                    paged is None or cells > paged.cols * paged.rows
                    or (cells == paged.cols * paged.rows and u > paged.u)):
                paged = found
    if whole is not None and whole.u >= least - EPSILON:
        return whole
    return paged or largest or Slots(1, 1, FLOOR, max(1, count))


def fill_unit(width, height, mw, mh, pad_x=0, pad_y=0):
    """The smallest unit (`min_u`) of a wall of full-height cards: FILL of the unit one card alone would have."""
    return FILL * max(min((width - pad_x) / mw, (height - pad_y) / mh), 0)


# ---- how large a wall's type must be to be read from where it is watched (frontend-redesign CONSENSUS §9) -----------
# A board may say which screen it is shown on (its diagonal) and from how far it is read; the browser knows the screen's
# size in px. The character height a text subtends at that distance must be at least
#   - ARCMIN_CRITICAL for a critical value or a state's word (FHWA-RD-98-057, ch. 3: 20 arcmin for critical elements);
#   - ARCMIN_SECONDARY for every other text (16 arcmin: the least character height for reading of ANSI/HFES 100-2007
#     and ISO 9241-303; coordinator's decision of 2026-11-24, after review round 2).
# These are the standards' figures, not a farm's preference (a farm chooses its screen and its distance). On a fitted card
# the state's word is the step 1.25 of the unit (tw:text-u-l) and the smallest text 0.8 of it (tw:text-u-s); a
# character's height is the cap height of the text face, CAP of its size (Atkinson Hyperlegible Next, measured).
ARCMIN_CRITICAL, ARCMIN_SECONDARY = 20, 16
CAP = 0.67
STEP_STATE, STEP_SMALLEST = 1.25, 0.8
MM_PER_INCH = 25.4


def text_px(arcmin, inches, distance_m, screen_w, screen_h):
    """The font size (CSS px) whose characters subtend `arcmin` at `distance_m` on a screen of `inches` diagonal that is
    `screen_w` by `screen_h` CSS px (the device's pixel ratio cancels out: a CSS px is the diagonal over the CSS px)."""
    px_mm = inches * MM_PER_INCH / math.hypot(screen_w, screen_h)
    height_mm = 2 * distance_m * 1000 * math.tan(math.radians(arcmin / 60) / 2)
    return height_mm / CAP / px_mm


def legible_unit(inches, distance_m, screen_w, screen_h, critical_step=STEP_STATE):
    """The smallest unit (`min_u`) of a wall read from `distance_m` on that screen: its state words at ARCMIN_CRITICAL and
    its smallest text at ARCMIN_SECONDARY, never under FLOOR; FLOOR when the board says no screen or no distance.
    `critical_step`: the step of the unit its critical words are set in (a card's state word; the band's tally, 1)."""
    if not (inches and distance_m and screen_w and screen_h):
        return FLOOR
    return max(FLOOR, text_px(ARCMIN_CRITICAL, inches, distance_m, screen_w, screen_h) / critical_step,
               text_px(ARCMIN_SECONDARY, inches, distance_m, screen_w, screen_h) / STEP_SMALLEST)


# ---- whether a board's screen and distance can be met at all (the board's form: monitoring/models.py MonitorBoard) ---
# The browser lays the wall out with its real lengths (frontend/wall.ts); the form has no browser, so this is the same
# arithmetic on the screen's nominal size: the wall's padding round the page (--wall-pad, clamp(6px, .7vh, 16px)) and
# between the cells (--wall-gap, clamp(5px, .5vh, 12px)), a fitted card's own padding (.6 and 1.1 of --wall-pad) and
# its frame (static/css/monitor.css html[data-wall]), and a band of at most BAND_SHARE of the height (frontend/wall.ts
# BAND_SHARE: a band whose legible type would take more is kept to that). Every length of it is in CSS px and the
# legible unit is too, so the answer is the same at any pixel ratio but for the clamps (a 4K panel that says 1920 x 1080
# is the same screen).
BAND_SHARE = 1 / 6
FRAME_X, FRAME_Y = 8, 4
# (enough cards for the densest grid the rule may draw: how many one page holds)
MANY = MAX_COLS * MAX_ROWS

Reach = namedtuple('Reach', 'least most per_page farthest')


def room(screen_w, screen_h):
    """(width, height, gap, pad_x, pad_y) of the cells of a wall on a screen of `screen_w` by `screen_h` CSS px."""
    pad = min(max(6, 0.007 * screen_h), 16)
    gap = min(max(5, 0.005 * screen_h), 12)
    return (screen_w - 2 * pad, screen_h * (1 - BAND_SHARE) - 2 * pad - gap, gap,
            2 * 1.1 * pad + FRAME_X, 2 * 0.6 * pad + FRAME_Y)


def reach(inches, distance_m, screen_w, screen_h, mw, mh):
    """What a wall of fitted cards of `mw` by `mh` units can be on that screen read from that distance (Reach): the
    least unit it may use (`legible_unit`), the most one card a page gets, how many cards a page holds at the least
    (0: not one card can be read from there), and the farthest distance at which one card a page can be read, to the
    0.1 m below (None when the board says no screen or no distance)."""
    least = legible_unit(inches, distance_m, screen_w, screen_h)
    width, height, gap, pad_x, pad_y = room(screen_w, screen_h)
    most = min((width - pad_x) / mw, (height - pad_y) / mh)
    found = slots(MANY, width, height, gap, mw, mh, least, pad_x, pad_y)
    per_page = found.cols * found.rows if found.u >= least - EPSILON else 0
    farthest = None
    if inches and distance_m and least > FLOOR:
        # (the legible unit grows in proportion to the distance once it is over the floor)
        farthest = math.floor(float(distance_m) * most / least * 10 + EPSILON) / 10
    return Reach(least, most, per_page, farthest)
