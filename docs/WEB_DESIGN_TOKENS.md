# EQ Recorder — Web design tokens

Reference for carrying the app's visual style over to the web (for example a
landing page). All values match `app/theme.py`, `app/ui.py`, `app/strings.py`
and `app/config.py`. **If this document and the code disagree, the code
wins.** [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) describes the macOS app itself;
this file covers only what a web port needs.

Conventions:

- **pt → px.** AppKit points map 1:1 to CSS `px` (at `devicePixelRatio` 2
  these are the sizes seen in Retina screenshots).
- **A value without a name in `theme.py`** (hard-coded in `ui.py`) is marked
  ⚠︎ and says where the number comes from.
- All grays and greens are solid; **the palette has no transparency**. The
  only alpha change is the blinking `● REC` (section 6).
- The app has **no gradients, glow, shadows, blur or vibrancy.** (Vibrancy is
  deliberately disabled, see the comment in `_build_window`.) The only glow in
  the branding is inside the logo itself (section 5), which is a raster image.
- The app is **dark only**; there is no light theme.

---

## 1. Color tokens

### 1.1 Palette

| Token (`theme.py`) | Hex | Suggested CSS variable |
|---|---|---|
| `BG` | `#141614` | `--bg` |
| `SURFACE` | `#1C1F1C` | `--surface` |
| `CARD_BG_HOVER` | `#212421` | `--surface-hover` |
| `SURFACE_SELECTED` | `#20362B` | `--surface-selected` |
| `BORDER` | `#2B2F2B` | `--border` |
| `ACCENT` | `#34C085` | `--accent` |
| `ACCENT_BUTTON_BG` | `#1A724E` | `--accent-button-bg` |
| `TEXT_PRIMARY` | `#EDEFEC` | `--text-primary` |
| `TEXT_SECONDARY` | `#8B948C` | `--text-secondary` |
| `STATUS_DONE` | `#34C085` (= `ACCENT`) | `--status-done` |
| `STATUS_PROCESSING` | `#4FA8D8` | `--status-processing` |
| `STATUS_ERROR` | `#FF4D6D` | `--status-error` |
| `REMOVE_ICON_MUTED` | `#A85560` | `--trash-muted` |
| `RECORDING` | `#FF5F57` | `--recording` |

Derived aliases in `theme.py` (they add no new shades):
`CARD_BG = SURFACE`, `CARD_BG_SELECTED = SURFACE_SELECTED`,
`CARD_BORDER_SELECTED = ACCENT`, `COUNTER_READY_COLOR = STATUS_DONE`,
`COUNTER_PROCESSING_COLOR = STATUS_PROCESSING`. `CARD_KIND_COLOR`:
`current → STATUS_PROCESSING`, `pending → TEXT_SECONDARY`,
`orphan → TEXT_SECONDARY`, `done → STATUS_DONE`, `error → STATUS_ERROR`.

```css
:root {
  --bg: #141614;
  --surface: #1C1F1C;
  --surface-hover: #212421;
  --surface-selected: #20362B;
  --border: #2B2F2B;
  --accent: #34C085;
  --accent-button-bg: #1A724E;
  --text-primary: #EDEFEC;
  --text-secondary: #8B948C;
  --status-processing: #4FA8D8;
  --status-error: #FF4D6D;
  --trash-muted: #A85560;
  --recording: #FF5F57;
}
```

### 1.2 Where each color is used

| Role | Token | Notes |
|---|---|---|
| Window background | `BG` | solid, no blur |
| Cards, secondary buttons, dropdown, icon buttons, progress track | `SURFACE` | |
| Card hover | `CARD_BG_HOVER` | between `SURFACE` and `SURFACE_SELECTED` |
| Selected card | `SURFACE_SELECTED` + 1.5 px `ACCENT` outline | |
| Secondary button outline | `BORDER` 1 px | OUTPUT FOLDER, LAST FILE only |
| Primary button fill (START RECORDING, IMPORT) | `ACCENT_BUTTON_BG` | **not** `ACCENT`, see contrast below |
| Record button fill while recording (STOP RECORDING) | `RECORDING` | |
| Text on primary buttons | `TEXT_PRIMARY` | |
| Text on secondary buttons | `TEXT_SECONDARY` | |
| `EQ RECORDER` title, file names, `ALL`, body text | `TEXT_PRIMARY` | |
| `RECORDINGS`, `ENGINE: PRO`, `READY` status, gear icon | `TEXT_SECONDARY` | |
| Progress bar fill | `ACCENT` | track is `SURFACE` |
| `READY: N` | `ACCENT` | |
| `PROCESSING: N` | `STATUS_PROCESSING` | shown only when N > 0 |
| Timer at rest | `TEXT_PRIMARY` | |
| Timer while recording | `RECORDING` | |
| Timer during the SAVED toast | `ACCENT` | 10 s |
| Status dot: rest / recording / toast | `TEXT_SECONDARY` / `RECORDING` / `ACCENT` | |
| `● REC` | `RECORDING` | blinks, section 6 |
| Card status done | `ACCENT` | |
| Card status current (transcribing) | `STATUS_PROCESSING` | |
| Card status pending / orphan | `TEXT_SECONDARY` | |
| Card status error | `STATUS_ERROR` | |
| Trash at rest (nothing selected) | `REMOVE_ICON_MUTED` | |
| Trash active (card selected) | `STATUS_ERROR` | |

There is no pure white, pure black or transparent color in the UI.

### 1.3 Contrast

- `TEXT_PRIMARY` on plain `ACCENT` is **2.01:1**, which fails WCAG even for
  large text. Buttons therefore use the deeper `ACCENT_BUTTON_BG`
  (`#1A724E`): **5.10:1** (AA for normal text). **On the web, never put
  white text on `--accent`; use `--accent-button-bg`.**
- `STATUS_ERROR` on `SURFACE`: 5.18:1.
- `REMOVE_ICON_MUTED` on `SURFACE`: 3.27:1 (dimmer but visible).
- `STATUS_ERROR` (crimson) and `RECORDING` (coral) are **intentionally
  different reds** so "failed" and "recording" never look the same.

### 1.4 Logo colors (not UI tokens)

The logo (`resources/icon.png`) has a dark green background with a soft
green glow around a document icon and a sound wave. It is part of the raster
image; there are no CSS tokens for it. The UI takes its colors only from
`theme.py`.

---

## 2. Typography

**Typeface: Roboto Mono** (Apache-2.0, redistributable), a single
**variable font file** `resources/fonts/RobotoMono[wght].ttf` (`wght` axis).
License: `resources/fonts/LICENSE.txt`.

Weights (PostScript instance name → CSS `font-weight`):

| Token | PostScript | CSS |
|---|---|---|
| `FONT_REGULAR` | RobotoMono-Regular | 400 |
| `FONT_MEDIUM` | RobotoMono-Medium | 500 |
| `FONT_SEMIBOLD` | RobotoMono-SemiBold | 600 |
| `FONT_BOLD` | RobotoMono-Bold | 700 |

CSS (the variable file is served directly):

```css
@font-face {
  font-family: "Roboto Mono";
  src: url("RobotoMono[wght].ttf") format("truetype");
  font-weight: 100 700;
  font-display: swap;
}
```

The app falls back to the system font only outside the bundle; on the web
use `ui-monospace, "SF Mono", Menlo, monospace` as the fallback stack.

The app sets no `letter-spacing` or `line-height` (AppKit defaults). On the
web use `letter-spacing: normal` and pick a `line-height` that fits the row
heights in section 3 (for example 1.2–1.3). Labels are **uppercase in the
strings themselves** (`strings.py`), not through `text-transform`; file
names keep their original case (for example `09-15_30-09-26_DAILY.md`).

### 2.1 Type tokens

| Token | Size / weight | Context |
|---|---|---|
| `TYPE_DISPLAY` | 28 / bold (700) | `00:00` timer |
| `TYPE_TITLE` | 12 / semibold (600) | section header `RECORDINGS` |
| `TYPE_BODY` | 13 / medium (500) | card file name; status line, see below |
| `TYPE_BUTTON` | 12 / semibold (600) | all button labels |
| `TYPE_CAPTION` | 11 / regular (400) | caption under the file name, `ENGINE: PRO`, dropdown label |
| `COUNTER_TYPE` | 11 / medium (500) | `READY: N`, `PROCESSING: N` |

### 2.2 Values not in tokens (hard-coded in `ui.py`) ⚠︎

| Element | Size / weight | Color | Where |
|---|---|---|---|
| `EQ RECORDER` title | **14 / semibold** | `TEXT_PRIMARY` | header construction in `_build_window` |
| `● REC` | **12 / bold** | `RECORDING` | record-row construction |
| Dropdown menu items (ALL/TODAY/LONGEST/SHORTEST) | 11 / medium | `TEXT_PRIMARY` | filter menu construction |
| Status line (`READY`, `QUEUED…`, `ERROR…`) at rest | **13 / regular** | `TEXT_SECONDARY` | `refresh()` |
| Status line during the `SAVED: …` toast | 13 / medium | `ACCENT` | `refresh()` |

The status line is created at 11 pt, but `refresh()` resets its size to
`TYPE_BODY[0]` (13) on every tick, so the effective size is **13**; use 13 on
the web.

### 2.3 Typography by context

| Element | Size / weight | Color |
|---|---|---|
| `EQ RECORDER` | 14 / 600 | `--text-primary` |
| `ENGINE: PRO` | 11 / 400 | `--text-secondary` |
| `00:00` timer | 28 / 700, right-aligned | `--text-primary` → `--recording` while recording → `--accent` during the toast |
| Button labels (START RECORDING, STOP RECORDING, IMPORT, OUTPUT FOLDER, LAST FILE) | 12 / 600 | `--text-primary` (primary), `--text-secondary` (secondary) |
| Card file name | 13 / 500 | `--text-primary` |
| Card caption (`14 MIN 52 SEC`, `QUEUED`, `FAILED · …`), including the small `SEC`/`MIN` text | 11 / 400 | card status color (section 1.2) |
| `RECORDINGS` | 12 / 600 | `--text-secondary` |
| `READY: N` | 11 / 500 | `--accent` |
| `PROCESSING: N` | 11 / 500 | `--status-processing` |
| Dropdown label (`ALL`) | 11 / 400 | `--text-primary` |

There is no separate style for `SEC`/`MIN`: `N MIN M SEC` is a single
11 / 400 string in one color. Format: `N SEC` (under a minute), `N MIN`
(whole minutes), otherwise `N MIN M SEC`; always whole numbers. Timer:
`MM:SS`, and `H:MM:SS` from one hour (`config.tc`). In a monospaced font the
digits do not jump, so `font-variant-numeric` is not needed.

File names and long statuses **truncate in the middle** (the `…` sits in the
middle, so both the start and the `.md` stay visible). CSS has no single rule
for this; see "Limits of the web port".

---

## 3. Spacing, radius, layout

8 pt grid: `SPACE_XXS` 4 · `SPACE_XS` 8 · `SPACE_S` 12 · `SPACE_M` 16 ·
`SPACE_L` 24 · `SPACE_XL` 32.

### 3.1 Container

| Token | Value | What |
|---|---|---|
| `PANEL_PADDING_H` | **16** | the one horizontal padding: header, record row, progress, section, cards and bottom buttons all use the same guide |
| `PANEL_PADDING_TOP` | 44 | below the transparent title bar with traffic lights (not needed on the web) |
| `PANEL_PADDING_BOTTOM` | 16 | |
| `WINDOW_WIDTH × HEIGHT` | 520 × 750 | app window size (reference for a panel mockup) |

### 3.2 Heights and sizes

| Token | Value | What |
|---|---|---|
| `HEADER_HEIGHT` | 40 | header row (= `ICON_BUTTON_SIZE`) |
| `HEADER_LOGO_SIZE` | 22 | 22×22 logo in the header |
| `BUTTON_HEIGHT` | 44 | text buttons |
| `RECORD_BUTTON_WIDTH` | 200 | START / STOP RECORDING |
| `ICON_BUTTON_SIZE` | 40 | round icon button (trash, gear) |
| `PROGRESS_HEIGHT` | 6 | progress bar |
| `SECTION_ROW_HEIGHT` | 22 | `RECORDINGS` row (= dropdown height) |
| `DROPDOWN_HEIGHT` | 22 | |
| `DROPDOWN_MIN_WIDTH` | 96 | |
| `DROPDOWN_PADDING_LEFT / RIGHT` | 12 / 10 | |
| `DROPDOWN_CHEVRON_SIZE` | 14 | chevron frame (symbol 10 pt) |
| `CARD_HEIGHT` | 52 | |
| `CARD_GAP` | 6 | vertical gap between cards |
| `CARD_PADDING_LEFT` | 16 | |
| `CARD_MARKER_SLOT` | 14 | marker slot width |
| `CARD_MARKER_SIZE` | 10 | dot/ring diameter |
| `CARD_CHECK_SIZE` | 13 | checkmark frame (symbol 12 pt semibold) |
| `CARD_TEXT_GAP` | 2 | between title and caption |
| `CARD_ACTION_SIZE` | 32 | clickable area of the action icon (symbol 15 pt semibold) |
| `CARD_ACTION_INSET` | 12 | from the card's right edge |
| Status dot in the record row | 10×10 | hard-coded in `ui.py` ⚠︎ |

### 3.3 Border radius

| Element | Value |
|---|---|
| Card (`CORNER_RADIUS`) | **10** |
| Text button (`BUTTON_RADIUS`) | **22** (= height / 2, pill) |
| Icon button (`ICON_BUTTON_RADIUS`) | **20** (= 40×40 circle) |
| Dropdown | **11** (= 22 / 2, pill) |
| Progress bar | 3 (= 6 / 2, both track and fill) |
| Progress fill | minimum width = height (6 px), so a small percentage still shows a dot |

In CSS, `border-radius: 9999px` on every pill element gives the same look.

### 3.4 Vertical rhythm (top to bottom)

| Between | Gap |
|---|---|
| top padding → header | 0 (the 44 sits under the title bar) |
| header → record row (`GAP_HEADER_RECORD`) | 16 |
| record row → progress (`GAP_RECORD_PROGRESS`) | 12 |
| progress → section (`GAP_PROGRESS_SECTION`) | 16 |
| section → list (`GAP_SECTION_LIST`) | 8 |
| list → bottom buttons (`GAP_LIST_BUTTONS`) | 16 |

The space for the progress bar is **always reserved** (even when hidden) so
rows do not jump.

### 3.5 Horizontal distances

- Header: logo 22 → 8 → `EQ RECORDER`; `ENGINE: PRO` on the right, 8 from the
  gear (or from the edge when there is no gear).
- Record row: button 200 → 12 → dot 10 → 8 → status; timer at the right edge;
  the status never runs under the timer (minimum 12).
- Section: `RECORDINGS` → 12 → `READY: N` → 12 → `PROCESSING: N`; the
  dropdown is pinned to the right edge (= the cards' right edge).
- Card: 16 · marker slot 14 · 8 · [title / 2 / caption] · ≥ 8 · action 32 · 12.
- Bottom row: trash 40 → 8 → OUTPUT FOLDER → 8 → LAST FILE → 8 → IMPORT. The
  three text buttons have **equal width** (on the web `flex: 1` / grid `1fr`);
  the trash is a fixed 40.
- Alignment: texts in one row share a baseline (`align-items: baseline`);
  dots and buttons are centered.

---

## 4. Component states

### 4.1 Buttons

The background is drawn in code (`PillButton.drawRect_`), not by the system
bezel. An icon and a title are **never combined in one button**: text
buttons have only text, icon-only buttons only a symbol.

| Variant | Fill | Border | Text / icon | Where |
|---|---|---|---|---|
| **Primary** | `#1A724E` | — | `#EDEFEC`, 12/600 | START RECORDING, IMPORT |
| **Primary, recording** | `#FF5F57` | — | `#EDEFEC`, 12/600, label `STOP RECORDING` | record button while recording |
| **Secondary** | `#1C1F1C` | 1 px `#2B2F2B` (inner, inset 0.75, radius − 0.75) | `#8B948C`, 12/600 | OUTPUT FOLDER, LAST FILE |
| **Icon-only** | `#1C1F1C` | — | 16 pt medium symbol, color below | trash, gear (40×40 circle) |

**Trash (icon-only) — two explicit states** (not the system dimming):

| State | Icon color | When | Click |
|---|---|---|---|
| At rest | `#A85560` (3.27:1) | nothing selected | does nothing |
| Active | `#FF4D6D` (5.18:1) | a pending/orphan/error/done card is selected | delete |

The trash fill is the same in both states (`SURFACE`) and has no border.
The gear (hotkeys) is `TEXT_SECONDARY` on `SURFACE`, visible only while the
Accessibility permission is missing; when hidden it takes no space.

**Not implemented in the app (left to the system):**

- No hover state on buttons: `PillButton` has no `mouseEntered` handling and
  no color change on hover.
- No custom pressed state: the system `NSButton` provides a brief title dim.
  No disabled state is used in the UI (`removeButton` is always enabled).
- Focus ring: not styled.

A web version has to **define** hover/active/focus-visible itself; the app
offers no reference. To stay in the palette, hovering a primary button should
not switch to `--accent` (contrast); `filter: brightness(1.1)` works better.
This is a design decision, not something taken from the code.

### 4.2 Recording card

52 px high, radius 10, padding-left 16. **Background and kind are two
independent dimensions:** any kind can be hovered and/or selected.

**Background (`RowCard.drawRect_`):**

| Variant | Fill | Outline |
|---|---|---|
| normal | `#1C1F1C` | — |
| hover | `#212421` | — |
| selected | `#20362B` | **1.5 px** `#34C085`, inset 1 px, radius 9 |

Priority: `selected` > `hover` > `normal` (a selected card under the cursor
stays `SURFACE_SELECTED`). Hover only works while the window is active
(`NSTrackingActiveInKeyWindow`). No transparency. Clicking a card only
selects it; the icon on the right performs the action.

**Status (kind):**

| kind | Marker | Caption (11/400) | Color (marker + caption + action icon) | Action icon |
|---|---|---|---|---|
| `current` | filled dot 10 px | `TRANSCRIBING — 37%` | `#4FA8D8` | none |
| `pending` | ring 10 px, 1.5 px line | `QUEUED` | `#8B948C` | none |
| `orphan` | ring | `NO TRANSCRIPT · 1 MIN 30 SEC` (just `NO TRANSCRIPT` without a duration) | `#8B948C` | microphone (transcribe) |
| `error` | ring | `FAILED · <reason, ≤ 48 chars>` | `#FF4D6D` | microphone (retry) |
| `done` | checkmark (12 pt semibold in a 13 frame) | duration (`DONE` if unknown) | `#34C085` | folder (show in Finder) |

Ring: a circle inscribed in 10×10 with a 1 px inset, 1.5 px line, no fill.
The file name is always `#EDEFEC` 13/500, whatever the kind.

### 4.3 Filter dropdown

Closed button: 22 px pill, fill `#1C1F1C`, **no border**, 11/400 `#EDEFEC`
label on the left (padding 12), `chevron.up.chevron.down` (10 pt,
`TEXT_SECONDARY`) on the right (padding 10), minimum width 96, grows to the
left (the right edge is fixed). The whole rectangle is clickable.

| State | What the code does |
|---|---|
| Closed | as above; the label is the current filter (`ALL` by default) |
| Open | **native `NSMenu`** below the button (4 px offset), forced to Dark Aqua, items ALL / TODAY / LONGEST / SHORTEST at 11/500 `#EDEFEC`. The frame, background, radius, hover highlight and checkmark of the menu are drawn by **macOS**; the code holds no values for them |
| Selected item | the button label changes to the selection; **the menu does not mark the selected item** (no checkmark or color) |
| Hover / pressed button | not styled |

The filter applies only to `done` cards; the list shows the 15 newest. The
choice is not kept between launches.

### 4.4 Toast (SAVED → READY)

Not a separate component but a **state of the record row** (status, dot and
timer change color):

| State | Dot 10 px | Status | Timer |
|---|---|---|---|
| Rest | `#8B948C` | `READY`, 13/400 `#8B948C` | `#EDEFEC` |
| Recording | hidden; `● REC` 12/700 `#FF5F57` replaces the status | hidden | `#FF5F57` |
| Toast `SAVED: <file>` (10 s) | `#34C085` | 13/**500** `#34C085` | `#34C085` |
| Error | `#8B948C` | `ERROR: …` (≤ 80 chars), 13/400 `#8B948C` | `#EDEFEC` |

While recording the button is `#FF5F57` / `STOP RECORDING`. The slot next to
the button is shared by `● REC` and dot+status; exactly one is visible. The
status truncates in the middle, with the full text in a tooltip. The toast
disappears by itself **only** when the engine is idle (not recording, nothing
queued); `ERROR` and `MODEL FAILED TO LOAD` do not clear by themselves. There
is no slide-in or fade: text and colors change instantly.

The app also posts macOS notifications (`C.notify`) through Notification
Center; they are not part of the window UI and do not carry over to the web.

### 4.5 Delete alert

A **native `NSAlert`** (Warning style, `runModal`) with nothing styled: title
`DELETE <FILE>?`, body `THIS CANNOT BE UNDONE.`, buttons `DELETE` (first,
default) and `CANCEL`. Background, font, radii, buttons and the app icon are
all system-drawn. Screenshot: `docs/images/states/delete-alert.png`. It is
shown only for files on disk (orphan/error/done); a pending item is removed
from the queue without confirmation. **The code has no values for a web
version**; the modal has to be designed from scratch (the palette from
section 1 can be reused).

---

## 5. Icons

All UI icons are **SF Symbols** (`ICONS` in `theme.py`), loaded through
`NSImage.imageWithSystemSymbolName_` as template images and tinted. **There
are no custom UI icons in `resources/`**, only the app logo. Only the status
dot/ring and the progress bar are drawn in code rather than loaded.

| Role | Where in the UI | Symbol / source | Size / weight | Portability |
|---|---|---|---|---|
| Record / transcribe | action on orphan/error cards | SF Symbol `mic.fill` | 15 pt semibold | Does not carry over to the web directly; needs an SVG equivalent or an icon-set replacement. |
| Import | *(key `import_file` exists in `ICONS`, but the IMPORT button is text only; the icon is not displayed)* | SF Symbol `square.and.arrow.down` | — | Same as above. Not used in the UI. |
| Folder | action on done cards | SF Symbol `folder.fill` | 15 pt semibold | Same as above. |
| Trash | bottom row | SF Symbol `trash.fill` | 16 pt medium | Same as above. |
| Gear | header (when Accessibility is missing) | SF Symbol `gearshape.fill` | 16 pt medium | Same as above. |
| Dropdown chevron | filter dropdown | SF Symbol `chevron.up.chevron.down` | 10 pt regular | Same as above. |
| Done checkmark | done card marker | SF Symbol `checkmark` | 12 pt semibold | Same as above. |
| `doc.text.fill` (`reveal_last`) | *(in `ICONS`, but the LAST FILE button is text only)* | SF Symbol | — | Same as above. Not used in the UI. |
| Status dot / ring | record row, card marker | **not an icon**: drawn with `NSBezierPath` (`StatusDot`) | 10×10; ring line 1.5 | Trivial: `border-radius: 50%` (+ `border: 1.5px solid`). |
| Progress bar | below the record row | **not an icon**: `ProgressBar.drawRect_` | height 6 | Plain CSS (section 3.3). |
| `● REC` | record row | text character `●` (U+25CF) in `strings.REC_INDICATOR` | 12 bold | Carries over as text; check that Roboto Mono has U+25CF, otherwise a fallback font is used. |
| Header logo | header, 22×22 | **custom asset** `resources/icon.png` | PNG 1024×1024, RGBA | Carries over, see below. |
| App icon | Dock | **custom asset** `resources/icon.icns` | — | `.icns` is not used on the web. |

### Logo files that can be used directly

- `resources/icon.png` — 1024×1024 RGBA with the **macOS squircle mask
  applied** (transparent corners). This is the file shown in the app header
  (`config.PNG_PATH`). It is generated by `scripts/update_icon.sh`; do not
  edit it directly.
- `assets/app_icon_source.png` — the **unmasked source**. For the web, use
  this or `icon.png`, depending on whether the squircle crop is wanted.
- `resources/icon.icns` — macOS only.

The logo shows a dark green background, a sound wave on the left, a document
icon on the right and a soft green glow (all inside the PNG). For a favicon
or OG image, crop from `icon.png`; 1024 px is enough for any size.

---

## 6. Micro-animations and transitions

**The app has practically no animations.** `ui.py` uses no
`NSAnimationContext` and no `animator()`. Every state change is
**instant** (a redraw after `setNeedsDisplay`). For most items below there is
therefore no duration or easing to copy; on the web they are a new design
decision.

| What | Duration | Easing / type | Source |
|---|---|---|---|
| **UI tick** (`refresh()`) | **0.5 s**, repeating `NSTimer` | — (a polling rate, not an animation) | `AppDelegate` timer setup |
| **Toast SAVED → READY** | **10 s** (`DONE_FLASH_SEC = 10`) | delay timer; the change is **instant** (no fade). It happens on the first tick after expiry, so after 10.0–10.5 s | `config.py`, `refresh()` |
| **`● REC` blink** | period **1 s**: 0.5 s `alpha 1.0` + 0.5 s `alpha 0.35` | **step, no interpolation**: `blink_on = int(time.time()*2) % 2 == 0`. The phase comes from the clock and is applied once per 0.5 s tick | `refresh()` |
| **Card hover** | 0 ms | instant `SURFACE → #212421` (no transition) | `RowCard.setHovered_` |
| **Card selection** | 0 ms | instant fill change plus the 1.5 px outline | `RowCard.setSelected_` |
| **Trash rest → active** | 0 ms | instant icon color change on the tick (≤ 0.5 s after selection) | `refresh()` |
| **Progress bar** | 0 ms | width jumps on each tick, no smoothing; shown/hidden (`setHidden_`) without fade | `ProgressBar.setProgress_` |
| **Dropdown open/close** | not in the code | the menu is opened with `NSMenu.popUp…`; **any fade or spring is drawn by macOS** | filter menu action |
| **Delete alert** | not in the code | system modal (`runModal`) | delete action |
| **Timer/status color change** (recording/toast/rest) | 0 ms | instant | `refresh()` |

### CSS equivalent

To make a page look like the app, this is enough:

```css
/* ● REC blink: stepped, not smooth */
@keyframes rec-blink { 0%,49.99% { opacity: 1; } 50%,100% { opacity: .35; } }
.rec { animation: rec-blink 1s steps(1, end) infinite; }

/* Card: no transition, like the app */
.card { background: var(--surface); }
.card:hover { background: var(--surface-hover); }
.card.selected { background: var(--surface-selected);
                 box-shadow: inset 0 0 0 1.5px var(--accent); }
```

(`box-shadow: inset` is only a way to draw an outline that does not change
the box size; the app itself has no shadows.)

Transitions on the web are a new decision, not something taken from the
code. If added, keep them short (≈ 120–200 ms, `ease-out`) and only on
`background`/`color`, so they stay close to the app's instant behavior.

---

## Limits of the web port

Everything that cannot be copied straight into CSS/HTML and needs its own
solution:

1. **All SF Symbols** (`mic.fill`, `folder.fill`, `trash.fill`,
   `gearshape.fill`, `chevron.up.chevron.down`, `checkmark` in use;
   `square.and.arrow.down` and `doc.text.fill` are in the dictionary but not
   shown). They are system macOS symbols and **do not carry over directly;
   use an SVG equivalent or an icon set.** SF Symbols are also licensed for
   Apple-platform apps only, so their outlines must not be copied to the web;
   use an icon set (for example Lucide, Phosphor or Material Symbols) rather
   than exporting from SF Symbols.app. Stroke weight (semibold/medium) and
   the filled (`.fill`) style have to be matched by hand.
2. **The open dropdown** is a native `NSMenu`; its look (background, radius,
   shadow, hover, opening animation) is entirely system-drawn. The code has no
   values for CSS, so a custom popover/listbox is needed. The selected item is
   not marked in the menu; decide whether to mark it on the web.
3. **The delete alert** is a native `NSAlert` with nothing styled. The modal
   has to be designed from scratch (text and behavior are known, appearance
   is not).
4. **Hover/pressed/focus for buttons** are not implemented in the app (only
   card hover). There is no reference; it is a design decision (section 4.1).
5. **Animations** are almost absent; the only thing to reproduce is the
   stepped `● REC` blink (section 6). Any other transition is a new decision.
6. **Middle truncation** (`NSLineBreakByTruncatingMiddle`). CSS
   `text-overflow` can only cut the end. Use JS (split the string into
   "start … end") or accept end truncation on a landing page. For a static
   mockup, short names are enough.
7. **Baseline alignment** and fixed row heights come from AppKit AutoLayout.
   Flexbox (`align-items: baseline`) reproduces them, but pixel-exact matches
   with the app need checking in a browser.
8. **Font.** The Roboto Mono variable file is free (Apache-2.0) and can be
   served directly from the site (`resources/fonts/`), but AppKit renders
   text through Core Text (different smoothing and hinting from a browser), so
   glyphs look slightly lighter/sharper on the web. Check that the font has
   U+25CF (`●`) and U+2014 (`—`, used in `TRANSCRIBING — 37%`).
9. **Logo.** `resources/icon.png` already has the squircle mask and the glow
   is baked into the pixels, so it scales losslessly only up to 1024 px.
   There is no vector source (SVG/Figma) in the repository, and `.icns` is
   macOS only.
10. **System notifications** (`C.notify`), the Dock icon, traffic lights, the
    transparent title bar (`PANEL_PADDING_TOP = 44`) and global hotkeys
    (⌘E / ⌘⇧H) are OS features with no web equivalent. A window mockup needs
    traffic lights drawn separately (`panel.png` is a screenshot with the
    standard ones).
11. **Dark only.** There is no light theme; do not invent one without a design.
12. **No gradients, glow or shadows in the UI.** If a web page adds them
    (a glow around the logo or buttons), that is a new idea, not a port. The
    only glow is baked into the logo PNG.
