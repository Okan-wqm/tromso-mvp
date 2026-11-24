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
unit). A cell is never lower than `mh` units of FLOOR: a window too low for one row scrolls."""
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
    whole = paged = None
    for cols in range(1, MAX_COLS + 1):
        for rows in range(1, MAX_ROWS + 1):
            room = (height - (rows - 1) * gap) / rows
            cell = max(room, mh * FLOOR + pad_y)
            u = min(((width - (cols - 1) * gap) / cols - pad_x) / mw, (cell - pad_y) / mh)
            fits = cell <= room + 0.5
            cells = cols * rows
            found = Slots(cols, rows, u, max(1, math.ceil(count / cells)))
            if fits and cells >= count and (whole is None or u > whole.u + EPSILON or (
                    abs(u - whole.u) <= EPSILON and cells < whole.cols * whole.rows)):
                whole = found
            if u >= least - EPSILON and (fits or rows == 1) and (
                    paged is None or cells > paged.cols * paged.rows
                    or (cells == paged.cols * paged.rows and u > paged.u)):
                paged = found
    if whole is not None and whole.u >= least - EPSILON:
        return whole
    return paged or whole or Slots(1, 1, FLOOR, max(1, count))


def fill_unit(width, height, mw, mh, pad_x=0, pad_y=0):
    """The smallest unit (`min_u`) of a wall of full-height cards: FILL of the unit one card alone would have."""
    return FILL * max(min((width - pad_x) / mw, (height - pad_y) / mh), 0)


# ---- how large a wall's type must be to be read from where it is watched (frontend-redesign CONSENSUS §9) -----------
# A board may say which screen it is shown on (its diagonal) and from how far it is read; the browser knows the screen's
# size in px. The character height a text subtends at that distance must be at least
#   - ARCMIN_CRITICAL for a critical value or a state's word (FHWA-RD-98-057, ch. 3: 20 arcmin for critical elements);
#   - ARCMIN_SECONDARY for every other text (MIL-STD-1472H §5.17.18.2: 15 arcmin "should").
# These are the standards' figures, not a farm's preference (a farm chooses its screen and its distance). On a fitted card
# the state's word is the step 1.25 of the unit (tw:text-u-l) and the smallest text 0.8 of it (tw:text-u-s); a
# character's height is the cap height of the text face, CAP of its size (Atkinson Hyperlegible Next, measured).
ARCMIN_CRITICAL, ARCMIN_SECONDARY = 20, 15
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
