"""EQ Recorder design system: colors, typography, icons, components.

The single source of visual constants for the UI layer (app/ui.py). Changing
the look of the app means editing THIS file rather than hunting for colors in
the code.

The palette is narrow (one accent, neutrals, status colors), the type is the
monospaced Roboto Mono, and the row card has explicit variants so that
hover/selected/kind are defined here rather than scattered through the code.

Icons are SF Symbols (the macOS system set): one line style, automatic
scaling, no custom PNGs.
"""

# ─────────────────────────── Colors (dark, minimal) ────────────────
#
# Few colors on purpose: one accent (green), neutrals for text and surfaces,
# and separate colors only for explicit statuses (processing/error).
# RECORDING is the one deliberate exception (see below).

BG = "#141614"                 # window background
SURFACE = "#1C1F1C"             # row cards, buttons
SURFACE_SELECTED = "#20362B"    # selected card — a very muted accent
BORDER = "#2B2F2B"              # outline of secondary buttons

ACCENT = "#34C085"              # the only accent color: markers/hover/done/
                                # selection outline (NOT button fills — see
                                # ACCENT_BUTTON_BG below)
# Fill of accent buttons (START RECORDING/IMPORT) — deliberately darker than
# ACCENT: TEXT_PRIMARY on the pure ACCENT gives a WCAG contrast of only
# 2.01:1, which fails even AA for large text (threshold 3.0). This shade with
# the same TEXT_PRIMARY gives above 4.5:1, which passes AA for normal text.
# It is the same green, just deeper, so the identity is kept.
ACCENT_BUTTON_BG = "#1A724E"

TEXT_PRIMARY = "#EDEFEC"        # main text
TEXT_SECONDARY = "#8B948C"      # secondary (captions, status labels)

# File row statuses — color is used only where it carries information that
# the icon/text does not (done is deliberately ACCENT, with no separate hue:
# "done" already reads as "all good" and the accent color is enough).
STATUS_DONE = ACCENT
STATUS_PROCESSING = "#4FA8D8"   # in progress — blue, to avoid confusion with done/error
# A bright red, deliberately a different hue from RECORDING below (crimson,
# not orange-coral) so that "error" and "recording" do not read as the same
# color. Contrast on SURFACE: 5.18:1.
STATUS_ERROR = "#FF4D6D"        # transcription failed; also the active
                                # (clickable) trash icon, see below

# The Remove icon has two explicit states rather than the system dimming of
# setEnabled_, which would leave the button equally dim regardless of the
# selection. This is the muted but visible resting state: contrast on SURFACE
# is 3.27:1 (the active STATUS_ERROR above gives 5.18:1, clearly brighter).
REMOVE_ICON_MUTED = "#A85560"

RECORDING = "#FF5F57"           # the one deliberate exception to the palette
                                # above: red for "recording" is a universal
                                # convention (camera/Zoom/QuickTime/OBS);
                                # green here would read as "ready to record"
                                # rather than "recording now"

# ─────────────────────────────── Typography ────────────────────────────
#
# Roboto Mono (Apache-2.0, bundled through ATSApplicationFontsPath — see
# build_app.sh) is a monospaced face. The file is a VARIABLE font (one .ttf,
# weight on the "wght" axis) rather than separate static files: its named
# instances have their own PostScript names, and NSFont.fontWithName_size_
# resolves them like ordinary static fonts.
#   RobotoMono-Regular / -Medium / -SemiBold / -Bold

FONT_REGULAR = "RobotoMono-Regular"
FONT_MEDIUM = "RobotoMono-Medium"
FONT_SEMIBOLD = "RobotoMono-SemiBold"
FONT_BOLD = "RobotoMono-Bold"

FONT_BY_WEIGHT = {
    "regular": FONT_REGULAR, "medium": FONT_MEDIUM,
    "semibold": FONT_SEMIBOLD, "bold": FONT_BOLD,
}

# (size, weight) — the weight is a key into FONT_BY_WEIGHT in ui.py.
TYPE_DISPLAY = (28, "bold")        # large recording timer
TYPE_TITLE = (12, "semibold")      # section titles ("RECORDINGS")
TYPE_BODY = (13, "medium")         # file name in a card
TYPE_BUTTON = (12, "semibold")     # button labels (bolder for legibility on
                                   # the green fill)
TYPE_CAPTION = (11, "regular")     # quality line, secondary hints

# ─────────────────────────────────── Spacing (8pt grid) ────────────────

SPACE_XXS = 4
SPACE_XS = 8
SPACE_S = 12
SPACE_M = 16
SPACE_L = 24
SPACE_XL = 32

# The single horizontal padding of the whole panel: every row (header,
# record + timer, RECORDINGS/ALL, record cards, bottom button row) is inset by
# this same number on the left and right, with no per-row hardcoded offset,
# so all edges line up.
PANEL_PADDING_H = SPACE_M

# ─────────────────── Panel layout (AutoLayout, ui.py) ────────────────────
#
# These are the only layout numbers. ui.py computes no x/y by hand: every row
# is pinned to one shared padding guide (PANEL_PADDING_H on both sides), rows
# form a vertical chain with the gaps below, and text within a row is aligned
# by baseline.

WINDOW_WIDTH = 520
WINDOW_HEIGHT = 750
PANEL_PADDING_TOP = 44          # below the transparent title bar with traffic lights
PANEL_PADDING_BOTTOM = SPACE_M

HEADER_HEIGHT = 40              # = ICON_BUTTON_SIZE (hotkeys gear)
HEADER_LOGO_SIZE = 22
RECORD_BUTTON_WIDTH = 200
PROGRESS_HEIGHT = 6
SECTION_ROW_HEIGHT = 22         # = DROPDOWN_HEIGHT

GAP_HEADER_RECORD = SPACE_M     # vertical gaps between rows
GAP_RECORD_PROGRESS = SPACE_S
GAP_PROGRESS_SECTION = SPACE_M
GAP_SECTION_LIST = SPACE_XS
GAP_LIST_BUTTONS = SPACE_M

# Custom filter dropdown (ALL/TODAY/LONGEST/SHORTEST). Padding is symmetric
# by construction: the text and chevron are vertically centered inside the
# button rather than tuned with a y offset.
DROPDOWN_HEIGHT = 22
DROPDOWN_MIN_WIDTH = 96
DROPDOWN_PADDING_LEFT = SPACE_S
DROPDOWN_PADDING_RIGHT = 10
DROPDOWN_CHEVRON_SIZE = 14

# Record card. The status marker sits in a fixed-width slot, so the ring
# (pending/orphan/error/current) and the checkmark (done) share a center and
# the text starts on the same line in every state.
CARD_HEIGHT = 52
CARD_GAP = 6                    # vertical gap between cards
CARD_PADDING_LEFT = SPACE_M
CARD_MARKER_SLOT = 14
CARD_MARKER_SIZE = 10
CARD_CHECK_SIZE = 13
CARD_TEXT_GAP = 2               # between the title and the caption
CARD_ACTION_SIZE = 32
CARD_ACTION_INSET = SPACE_S     # from the right edge of the card

CORNER_RADIUS = 10             # card corner radius (table rows)

# Buttons are pill-shaped (radius = half the height).
BUTTON_HEIGHT = 44
BUTTON_RADIUS = BUTTON_HEIGHT / 2        # 22 — fully rounded ends
ICON_BUTTON_SIZE = 40                     # icon-only buttons are circles
ICON_BUTTON_RADIUS = ICON_BUTTON_SIZE / 2  # 20

# ────────────────────────────────── Icons (SF Symbols) ─────────────────

ICONS = {
    "record_start": "mic.fill",
    "import_file": "square.and.arrow.down",
    "open_folder": "folder.fill",
    "remove_queue": "trash.fill",
    "reveal_last": "doc.text.fill",
    "hotkeys": "gearshape.fill",
    "sort_chevron": "chevron.up.chevron.down",
    "status_done": "checkmark",   # compact checkmark for "done"
}

# ───────────────────── Component: RECORDINGS section counters ───────────
#
# "READY: N" is the number of finished transcripts (always visible).
# "PROCESSING: N" is how many files are still waiting for whisper (current +
# queue); it is shown ONLY when N > 0 and otherwise takes no space at all (a
# hidden view in the horizontal stack). The colors match the corresponding
# cards (done / current), so the counter and the cards read as one unit.

COUNTER_READY_COLOR = STATUS_DONE
COUNTER_PROCESSING_COLOR = STATUS_PROCESSING
COUNTER_TYPE = (11, "medium")
COUNTER_GAP = SPACE_S            # between READY: N and PROCESSING: N

# ────────────────────────── Component: row card ─────────────────────────
#
# All card states in one place rather than scattered through ui.py.
# kind → color of the status icon/text. hover/selected are separate and
# orthogonal to kind (any kind can be hovered and selected at the same time).

CARD_KIND_COLOR = {
    "current": STATUS_PROCESSING,
    "pending": TEXT_SECONDARY,
    "orphan": TEXT_SECONDARY,
    "done": STATUS_DONE,
    "error": STATUS_ERROR,
}

CARD_BG = SURFACE                # regular card
CARD_BG_SELECTED = SURFACE_SELECTED
CARD_BORDER_SELECTED = ACCENT     # thin outline marking the selection
CARD_BG_HOVER = "#212421"         # slightly lighter than SURFACE, darker than
                                  # SURFACE_SELECTED, so hover and selected
                                  # do not blend visually
