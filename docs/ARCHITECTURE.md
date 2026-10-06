# Architecture

One process, one `NSApplication`. No IPC, no second process, no daemon.

```
┌─────────────────────────────────────────────────────────┐
│                     recorder.py (main)                   │
│                                                           │
│   Engine ───────────────┐          run_app() starts:     │
│   - mic capture         │                                │
│   - IDLE/RECORDING      │          ui.AppDelegate         │
│   - self.events queue ◄─┼──────────  (NSApplicationDelegate,│
│   - self.last_errors    │           NSWindowDelegate,     │
│                         │           NSTableView data      │
│   TranscriptionQueue    │           source + delegate,    │
│   (own thread, FIFO) ───┘           all in one class)     │
│         │                                                 │
│         ▼                                                 │
│   transcriber.py                    0.5s NSTimer tick:    │
│   - transcribe_with_progress()      drains engine.events, │
│   - per-30s-window language         calls refresh()       │
│     detection + uk prior (uk/ru/en)                       │
│   - build_md() / smart_filename() (time only)             │
└─────────────────────────────────────────────────────────┘
```

## Why one process

The panel is pure AppKit, so it *is* the `NSApplication`. `Engine` and the
UI live in the same process, and the UI reads `Engine`'s state directly
instead of polling files. (A menu-bar library that wraps `NSApplication`
and a `tkinter` window cannot share a thread on macOS, which is why a
pure-AppKit panel is the simplest option.)

## The three layers

**`Engine` (`recorder.py`)** — owns the microphone stream and recording
state (`IDLE` / `RECORDING`). It knows nothing about AppKit. It talks to
the rest of the app only through:
- plain attributes (`state`, `status`, `progress`, `last_md`, `last_name`,
  `last_errors`) that `ui.py` reads on every tick,
- `self.events`, a thread-safe `queue.Queue` that `TranscriptionQueue`'s
  worker thread pushes `(kind, payload)` tuples into (`"done"`, `"empty"`,
  `"error"`, `"queued"`, `"model_ready"`, `"model_fail"`) — the *only*
  thing the worker thread is allowed to touch directly; everything else
  goes through this queue so the AppKit main thread stays the sole owner
  of UI/state mutation.

**`TranscriptionQueue` (`transcribe_queue.py`)** — a `deque` +
`threading.Condition` (not `queue.Queue`, because the panel needs to
inspect/reorder/cancel pending items, which `queue.Queue` doesn't allow),
with exactly one worker thread, alive for the whole process. One worker is
deliberate: two transcriptions competing for the same GPU are slower than
one, not faster — and MLX needs a single owning thread anyway (below). `snapshot()` gives the UI a read-only, lock-safe copy of queue
state to render from.

**`transcriber.py`** — pure functions, no threading/UI concerns of its
own. `transcribe_with_progress()` is the whole pipeline for one file:
detect language per 30-second window → group into language runs →
decode each run separately → `build_md()`. See `README.md`'s "Quality"
section for why the per-window detection and the `EQ_FORCE_UKRAINIAN` /
`EQ_LANG_UK_MARGIN` knobs exist — that's product-facing detail, not
architecture.

**One model, two jobs.** With `ENGINE=mlx` (the default) the same
`large-v3-turbo` instance does both the language detection and the
decoding. `get_model()` takes it from `mlx_whisper`'s own `ModelHolder`
cache — the cache `mlx_whisper.transcribe()` reads — so the 1.6 GB of
weights are in memory once. Switching the model therefore changes both
decoding and language detection.

**Language logic in short.** Each 30 s window's probabilities are
renormalised over `SUPPORTED_LANGS = ("uk", "ru", "en")`; Polish is
deliberately not a candidate because the detector tends to label Ukrainian
as Polish. Then `LANG_UK_BIAS = 2.0` multiplies the `uk` probability
and `LANG_UK_MARGIN = 0.15` swaps uk/ru when `ru` wins by less than
that. With the turbo detector these two change the language of ~3.5 % of
speech time.

**MLX streams belong to a thread.** In MLX 0.32 a GPU stream is
thread-local, and part of a Whisper model (positional embeddings, the
decoder mask) stays lazy after loading, bound to the thread that built it.
A model built on one thread and used on another kills the whole process
(`libc++abi: … There is no Stream(gpu, 1) in current thread`). So:

- `recorder._preload_model` (a short-lived startup thread) calls
  `transcriber.preload_model()`, which only makes sure the weights are in
  the Hugging Face cache — it does **not** build the model;
- the model is built by the first `get_model()` call from
  `TranscriptionQueue`'s worker, the only thread that ever uses it.

Single-threaded scripts don't hit this, so test threading changes in the
real app.

## `ui.py`: one class doing four AppKit jobs

`AppDelegate` is simultaneously the `NSApplicationDelegate`, the
`NSWindowDelegate`, and the `NSTableView` data source *and* delegate.
This isn't an accident of laziness — PyObjC subclasses need real
`__init__`-free construction (`alloc().init()`, attributes assigned
after), and splitting these roles into separate small classes would only
add indirection between objects that already need to share the same
mutable state (`self._rows`, `self.engine`, `self.table`) every single
tick.

The 0.5-second `NSTimer` (`onTick_`) is the only clock in the app: it
drains `engine.events`, updates every label, and re-renders the
recordings list *only if the row data actually changed*
(`refresh()`'s `_rows_signature` check): calling `NSTableView.reloadData()`
unconditionally twice a second can crash the app at random (see the comment
above `refresh()`).

## Defensive wrapping

Several methods that AppKit calls synchronously from inside its own
Objective-C layout/draw passes (`drawRect_`, `tableView:viewForTableColumn:row:`,
the timer callback) are wrapped so a stray Python exception can't
silently kill the process. The reason this matters *specifically* here:
an exception raised inside a callback invoked directly by AppKit (as
opposed to one your own Python code calls) gets converted by PyObjC into
a native Objective-C exception, which `NSApplication` handles by calling
`_crashOnException:` and terminating immediately — with no Python
traceback ever printed. `_safe_draw` / `_safe_event` and the various
`try/except` wrappers around delegate methods exist for this reason; see
`RowActionButton`'s docstring in `ui.py` for a concrete case.

## Layout: AutoLayout, one padding guide

`theme.py` owns every number that decides how the window looks: colors,
type, spacing **and** layout sizes (`WINDOW_*`, `PANEL_PADDING_*`,
`HEADER_HEIGHT`, `GAP_*`, `DROPDOWN_*`, `CARD_*`). `ui.py` owns only the
*relationships* between views, written as `NSLayoutConstraint`s. There is
no `x`/`y` arithmetic anywhere in `ui.py`.

Rows are positioned by constraints rather than by computed frames, so
changing one value cannot silently move an unrelated view. The structure:

```
contentView
├── TintOverlay                  pinned to all four edges (background)
└── pad  (NSLayoutGuide)         leading/trailing = ±PANEL_PADDING_H,
    │                            top = PANEL_PADDING_TOP, bottom = PANEL_PADDING_BOTTOM
    ├── header guide   h=HEADER_HEIGHT   logo · title ········ ENGINE: PRO · [gear]
    ├── record guide   h=BUTTON_HEIGHT   [START RECORDING] ● status ···· 00:00
    ├── progress guide h=PROGRESS_HEIGHT (space always reserved, rows never jump)
    ├── section guide  h=SECTION_ROW_HEIGHT  RECORDINGS READY: N PROCESSING: N ··· [ALL ⌃]
    ├── scroll view    fills the space between section and buttons
    └── buttons guide  h=BUTTON_HEIGHT   [🗑] [OUTPUT FOLDER] [LAST FILE] [IMPORT]
```

Every row guide is pinned to `pad.leading` / `pad.trailing`, so every row
shares the same left and right edge by construction. Rules that keep it
from drifting when content changes:

- **Widths come from content.** Labels are `NSTextField.labelWithString_`,
  so they have an intrinsic size. `READY: 1234`, `SHORTEST` or a long file
  name simply make their view wider.
- **Long text truncates instead of overlapping.** The status line and card
  titles have low horizontal compression resistance and middle truncation
  (`SAVED: 11…09-26.md`); an `≤` constraint keeps them clear of the timer
  or the card's action icon. The full text is in the tooltip.
- **Text in a row shares a baseline.** `firstBaselineAnchor` is used where
  it is real: title ↔ `ENGINE: PRO`, `RECORDINGS` ↔ `READY: N` ↔
  `PROCESSING: N` ↔ the dropdown's `ALL`. A borderless `NSButton` reports
  a baseline ~13 pt from its top even though it draws its title centered,
  so text next to the record button is centered on the button instead.
- **Symmetric padding by construction.** The dropdown's text and chevron
  are its own subviews, each centered vertically inside it
  (`DropdownButton.hitTest_` sends clicks on them to the button).
- **Alignment-rect insets are zero** for our custom buttons and images
  (`_zero_insets`). AutoLayout positions the *alignment rect*, and
  `NSButton` / SF Symbol image views have non-zero insets by default: an
  icon-only 40×40 button actually came out 40×48.5.
- **Visibility toggles swap constraints, not frames.** `ENGINE: PRO` has
  two trailing constraints (to the gear or to the edge); `refresh()`
  activates one of them when the gear's visibility changes.
- **The table column always spans the table** (`LastColumnOnly`
  autoresizing), so cards share the dropdown's right edge without any
  measurement. Cards (`_make_card`) lay out their marker slot, text stack
  and action button with constraints relative to the card itself.

**Checking it with numbers.** `open --env EQ_LAYOUT_DEBUG=1 "/Applications/EQ Recorder.app"`
prints the frame (`L`, `R`, `top`, `w`, `h`, baseline) of every key view
to `app.log` 1.5 s after launch (`AppDelegate.dumpLayout_`). Every row reports `L=16.0` and `R=504.0` (text labels show ±2 pt,
the `NSTextField` cell inset outside the alignment rect).

## Launcher and app identity

The app bundle's executable is a tiny native binary
(`launcher/launcher.m`, compiled by `build_app.sh`) that embeds
`Python.framework` and runs `boot.py` **in the same process**
(`Py_BytesMain`). It points Python at the project venv through
`__PYVENV_LAUNCHER__`, the same variable Homebrew's own `python3.10` stub
uses.

Why not a script: Homebrew's `python@3.10` is a framework build, and its
`bin/python3.10` is a stub that `execv`s
`Python.framework/…/Resources/Python.app/Contents/MacOS/Python`. With a
shebang launcher that hop happens after LaunchServices has registered the
launch, and the process checks in as **`org.python.python`** instead of
`com.eq.recorder` (visible in `lsappinfo list`). Consequences:

- a second, generic "Python" icon in the Dock;
- clicking the EQ Recorder icon again starts a *new* process instead of
  activating the running one;
- Accessibility / System Events see zero windows, so UI automation is
  impossible.

With the native launcher the executable lives in the bundle, so
`NSBundle.mainBundle()` is `EQ Recorder.app` and the process registers as
`com.eq.recorder`. macOS then handles "already running" itself: a Dock
click or a second `open` sends the running app a reopen event
(`applicationShouldHandleReopen_`) instead of launching again.

**Single instance, three layers** (each covers a case the others can't):

1. macOS / LaunchServices — same bundle path: reopen event, no new process.
2. `launcher.m` — a *different* bundle copy (Desktop vs /Applications)
   with the same bundle id: activates the running app through
   `NSRunningApplication` and exits before Python starts. That matters: a
   duplicate that got as far as reading `.venv` on `~/Desktop` sat blocked
   on a TCC "access Desktop folder" prompt.
3. `config.running_instance_pid()` — `./start.sh` next to a bundle, or
   vice versa: bundle id lookup, then `.state/engine.pid` plus the
   process command line (a stale PID reused by another program doesn't
   count). The duplicate activates the running instance
   (`activate_instance()`), and `applicationDidBecomeActive_` shows the
   window if it was hidden.

**Signing.** `build_app.sh` signs ad-hoc with
`-r='designated => identifier "com.eq.recorder"'`. Without that, an ad-hoc
signature's identity is its cdhash, which changes on every build, and
macOS would treat every rebuild as a new app and ask again for every
permission (Desktop folder, microphone, Accessibility).

**`./start.sh`:** it runs `.venv/bin/python3.10` directly,
so the `Python.app` re-exec still happens there. Use the bundle for
everyday work.

## Global hotkeys

Registered in `UI._install_hotkeys` with two `NSEvent` monitors on key-down:
a global one (events while another app is frontmost; needs the Accessibility
permission) and a local one (events while EQ Recorder itself is active —
a global monitor never sees the app's own events). Both go through one
handler.

| Action | Mac | Future Windows equivalent (reference only) |
|---|---|---|
| Toggle recording (press again to stop) | `Cmd+E` | `Ctrl+E` |
| Show/hide panel | `Cmd+Shift+H` | `Ctrl+Shift+H` |

Without Accessibility the global monitor registers fine but silently
receives nothing — there is no error. `config.hotkeys_enabled()` wraps
`AXIsProcessTrusted()`; while it is false the header shows a gear that opens
System Settings → Privacy & Security → Accessibility
(`x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility`).
The permission is read at process start, so grant it and relaunch. At
startup the app logs `[hotkey] registered: … accessibility_trusted=…` to
`app.log`, and each handled press logs `[hotkey] …`. The Windows column is a
note for later, not a plan.

## Its own Python environment

The app runs out of `.venv/` (gitignored, created from `requirements.txt`),
not the shared Homebrew `python3.10`. The bundle launcher
(`VENV_PYTHON`, set by `build_app.sh`) and `start.sh` both point at
`.venv/bin/python3.10` by absolute path. This isolates the pinned
dependency versions from any other tool that uses the system Python (an
upgraded `scipy` elsewhere would otherwise break imports). The tradeoff:
`.venv/` has to be created once per
machine (`python3.10 -m venv .venv && .venv/bin/pip install -r requirements.txt`).
