"""Centralized interface strings: US English, labels and buttons in caps.

The single source of the text the user sees in the panel (buttons, statuses,
notifications). Changing the interface language means editing only this file.

Deliberately NOT included (data and ASR parameters, not interface):
  - config.INITIAL_PROMPT — the prompt in the language of the meetings
    (Ukrainian on purpose, see the comment in config.py).
  - The headings of the generated .md document (date, duration, language,
    source, transcript, full text, meeting title) — they are the content of
    the output file, separate from the app panel, and stay in Ukrainian.
"""

APP_TITLE = "EQ RECORDER"          # label in the panel header (C.APP_NAME is left
                                   # alone: it is the bundle identity)

# ── Buttons (all caps) ──────────────────────────────────────────────
BTN_START_RECORDING = "START RECORDING"
BTN_STOP_RECORDING = "STOP RECORDING"
BTN_IMPORT = "IMPORT"
BTN_OUTPUT_FOLDER = "OUTPUT FOLDER"
BTN_REMOVE = "REMOVE"
BTN_LAST_FILE = "LAST FILE"

TOOLTIP_HOTKEYS = "ENABLE HOTKEYS (ACCESSIBILITY)"
TOOLTIP_REMOVE = "DELETE THE SELECTED RECORDING"
PICKER_TITLE = "SELECT AN AUDIO OR VIDEO FILE"
QUIT_MENU_ITEM = "Quit {app}"       # system menu item — Title Case per macOS
                                    # convention, the one deliberate exception

# ── Panel labels/statuses ────────────────────────────────────────────
STATUS_READY = "READY"
STATUS_RECORDING = "RECORDING…"
STATUS_TOO_SHORT = "RECORDING TOO SHORT (<0.5S)"
STATUS_FILE_NOT_FOUND = "FILE NOT FOUND"
STATUS_MICROPHONE_ERROR = "MICROPHONE: {exc}"
STATUS_CONVERTING = "CONVERTING {name}…"
STATUS_QUEUED_FILE = "QUEUED: {name}"
STATUS_SAVED = "SAVED: {name}"
STATUS_LANGUAGE_NOT_DETECTED = "LANGUAGE NOT DETECTED"
STATUS_QUEUED_PAYLOAD = "QUEUED: {payload}"
STATUS_ERROR = "ERROR: {payload}"
STATUS_MODEL_LOAD_FAILED = "MODEL FAILED TO LOAD: {payload}"
STATUS_NO_FFMPEG = "FFMPEG NOT FOUND — BREW INSTALL FFMPEG"

QUALITY_LABEL = "ENGINE: PRO"        # deliberately without the model/whisper name —
                                     # a product label, not a technical one
SECTION_RECORDINGS = "RECORDINGS"
FILTER_ALL = "ALL"
FILTER_TODAY = "TODAY"
FILTER_LONGEST = "LONGEST"
FILTER_SHORTEST = "SHORTEST"

REC_INDICATOR = "● REC"

ROW_TRANSCRIBING = "TRANSCRIBING — {detail}"
ROW_QUEUED = "QUEUED"
ROW_NO_TRANSCRIPT = "NO TRANSCRIPT"
ROW_ERROR = "FAILED"
ROW_DONE_FALLBACK = "DONE"          # only if the duration could not be determined
ROW_SECONDS = "{n} SEC"
ROW_MINUTES = "{n} MIN"
ROW_MIN_SEC = "{m} MIN {s} SEC"

QUEUE_DONE_N = "READY: {n}"
QUEUE_PROCESSING_N = "PROCESSING: {n}"   # in progress + queued; only when N > 0

# ── Notifications (title, message) ──────────────────────────────────
NOTIFY_ALREADY_RUNNING_TITLE = "ALREADY RUNNING"
NOTIFY_ALREADY_RUNNING_BODY = "{app} IS ALREADY RUNNING"
NOTIFY_NO_FFMPEG_TITLE = "FFMPEG NOT FOUND"
NOTIFY_QUEUED_TITLE = "QUEUED"
NOTIFY_HOTKEYS_TITLE = "HOTKEYS"
NOTIFY_HOTKEYS_BODY = "ADD {app} TO ACCESSIBILITY AND RESTART THE APP"
NOTIFY_DONE_TITLE = "TRANSCRIPTION COMPLETE"
NOTIFY_DONE_BODY = "{name} → {where}"
NOTIFY_EMPTY_TITLE = "EMPTY TRANSCRIPT"
NOTIFY_EMPTY_BODY = ("WHISPER DIDN'T DETECT SPEECH. THE WAV FILE STAYS IN "
                     "RECORDINGS/ — YOU CAN RE-IMPORT IT.")
NOTIFY_ERROR_TITLE = "ERROR"
NOTIFY_REMOVE_CONFIRM_TITLE = "DELETE {name}?"
NOTIFY_REMOVE_CONFIRM_BODY = "THIS CANNOT BE UNDONE."
BTN_DELETE = "DELETE"
BTN_CANCEL = "CANCEL"

# ── Conversion / media-tool errors (shown as STATUS_ERROR) ──────────
ERR_FFMPEG_MISSING = "FFMPEG NOT FOUND ({path}). INSTALL: BREW INSTALL FFMPEG"
ERR_FFMPEG_CONVERT_FAILED = "FFMPEG CONVERSION FAILED: {detail}"
ERR_FFMPEG_NO_AUDIO = "FFMPEG PRODUCED NO AUDIO (THE FILE MAY HAVE NO SOUND)"
ERR_EMPTY_PATH = "(EMPTY PATH)"
ERR_MEDIA_TOOLS_MISSING = "MISSING: {tools}. INSTALL: BREW INSTALL FFMPEG"

# ── Transcription progress (transcriber.py) ─────────────────────────
PROGRESS_MODEL_LOADING = "MODEL {model}…"
PROGRESS_CHECKPOINT_FOUND = "CHECKPOINT FOUND: {n} PIECES DONE"
PROGRESS_DETECTING_LANGUAGE = "DETECTING LANGUAGE (30S WINDOWS)…"
PROGRESS_LANGUAGES = "LANGUAGES: {found}"
PROGRESS_FROM_CHECKPOINT = "↻ {label} FROM CHECKPOINT"
PROGRESS_DECODING = "[{lang}] {label} OF {duration}…"
PROGRESS_CLEANING_AUDIO = "CLEANING AUDIO (FFMPEG)…"
