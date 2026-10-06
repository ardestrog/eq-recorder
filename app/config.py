"""Shared constants and small helpers for EQ Recorder.

A separate module so that recorder / transcriber / ui / audio_import do not
import each other in a cycle.
"""

import os
import shutil
import subprocess
import time

import strings as S

APP_NAME = "EQ Recorder"
BUNDLE_ID = "com.eq.recorder"

# ──────────────────────── ffmpeg / ffprobe ────────────────────────────
#
# A process started from Finder (.app, Dock, Spotlight) inherits a trimmed
# PATH = /usr/bin:/bin:/usr/sbin:/sbin, without /opt/homebrew/bin. A bare
# subprocess.run(["ffmpeg", ...]) then fails with
#     FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'
# even though the same call works in a terminal.
#
# Two layers handle this:
#   1) FFMPEG / FFPROBE are absolute paths used by our own calls;
#   2) PATH is extended, because whisper.audio.load_audio() runs
#      run(["ffmpeg", ...]) by short name internally and takes no path
#      parameter.

_TOOL_DIRS = [
    "/opt/homebrew/bin",          # Apple Silicon Homebrew
    "/usr/local/bin",             # Intel Homebrew
    "/opt/local/bin",             # MacPorts
    "/usr/bin",
]


def _find_tool(name: str) -> str:
    """Absolute path to a binary; the bare name is the last-resort fallback."""
    found = shutil.which(name)
    if found:
        return found
    for directory in _TOOL_DIRS:
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return name                   # let the caller fail with a clear error


def ensure_tool_path() -> None:
    """Add the ffmpeg/ffprobe folders to the process PATH.

    Needed for whisper, which looks ffmpeg up on PATH rather than using our
    absolute path.
    """
    parts = os.environ.get("PATH", "").split(os.pathsep)
    for directory in _TOOL_DIRS:
        if os.path.isdir(directory) and directory not in parts:
            parts.insert(0, directory)
    os.environ["PATH"] = os.pathsep.join([p for p in parts if p])


ensure_tool_path()                # before the first _find_tool / whisper call

FFMPEG = _find_tool("ffmpeg")
FFPROBE = _find_tool("ffprobe")


def media_tools_ok() -> tuple:
    """(ok, message) — checked at startup, not in the middle of the pipeline."""
    missing = [name for name, path in (("ffmpeg", FFMPEG),
                                       ("ffprobe", FFPROBE))
               if not os.path.isabs(path)]
    if missing:
        return False, S.ERR_MEDIA_TOOLS_MISSING.format(
            tools=" AND ".join(m.upper() for m in missing))
    return True, f"ffmpeg: {FFMPEG}"

# ─────────────────────────────── Paths ────────────────────────────────

APP_DIR = os.path.dirname(os.path.abspath(__file__))        # .../eq-recorder/app
PROJECT_DIR = os.path.dirname(APP_DIR)                      # .../eq-recorder
RESOURCES_DIR = os.path.join(PROJECT_DIR, "resources")
REC_DIR = os.path.join(PROJECT_DIR, "recordings")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output")
STATE_DIR = os.path.join(PROJECT_DIR, ".state")

# Intermediate ASR files (_enhanced.wav, _chunk_*.wav) live apart from
# recordings/. If the process dies mid-transcription (SIGTERM on restart),
# cleanup in a finally block does not run; keeping these files out of
# recordings/ stops leftovers from showing up as "recordings without a
# transcript".
TMP_DIR = os.path.join(STATE_DIR, "tmp")

# Transcription checkpoints are persistent, unlike TMP_DIR (cleaned at
# startup). Transcribing an hour-long file can take a long time, and without
# a checkpoint a killed process would lose all progress. Only the code that
# has already saved the Markdown file removes them.
CHECKPOINT_DIR = os.path.join(STATE_DIR, "checkpoints")

PID_FILE = os.path.join(STATE_DIR, "engine.pid")

ICNS_PATH = os.path.join(RESOURCES_DIR, "icon.icns")
PNG_PATH = os.path.join(RESOURCES_DIR, "icon.png")

# Optional extra folder (e.g. an Obsidian vault): a copy of the Markdown file
# goes there if EQ_VAULT_DIR is set and the folder exists.
VAULT = os.path.expanduser(os.environ.get("EQ_VAULT_DIR", ""))


def save_dirs() -> list:
    """Where to save Markdown: always output/, plus the vault if present."""
    dirs = [OUTPUT_DIR]
    if VAULT and os.path.isdir(VAULT):
        dirs.append(VAULT)
    return dirs


def tmp_path(name: str) -> str:
    """Path for an intermediate ASR file in TMP_DIR."""
    os.makedirs(TMP_DIR, exist_ok=True)
    return os.path.join(TMP_DIR, name)


def clean_tmp() -> int:
    """Remove intermediate ASR files. Called when the engine starts.

    Safe because TMP_DIR holds only files derived from recordings/. Call it
    while the queue is idle (at startup); otherwise a file could be removed
    from under an active whisper run.
    """
    removed = 0
    if not os.path.isdir(TMP_DIR):
        return 0
    for name in os.listdir(TMP_DIR):
        try:
            os.remove(os.path.join(TMP_DIR, name))
            removed += 1
        except OSError:
            pass
    return removed


# Derived files that are not recordings (they may sit in recordings/).
_DERIVED_MARKS = ("_enhanced", "_chunk_")


def _md_sources() -> set:
    """The set of `**Джерело:** ...` lines from all output/*.md files.

    Used for orphan detection when a wav cannot be matched to an md by file
    name (see orphaned_recordings): for recordings the timestamp in the wav
    name and the md name is the same, but for imported files it is not
    (smart_filename() builds their name from the import date / mtime, not
    from the source file's stem). build_md() always writes the full source
    path, so this is a more reliable, if slower, fallback.
    """
    sources = set()
    if not os.path.isdir(OUTPUT_DIR):
        return sources
    for name in os.listdir(OUTPUT_DIR):
        if not name.endswith(".md"):
            continue
        try:
            with open(os.path.join(OUTPUT_DIR, name),
                      "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("- **Джерело:**"):
                        sources.add(line.strip())
                        break
        except OSError:
            continue
    return sources


def latest_transcript():
    """The newest finished .md in OUTPUT_DIR (by mtime), or None.

    The LAST FILE button reads from disk rather than process memory:
    Engine.last_md is set only by a "done" event in the current process, so
    it is None after every restart even when finished transcripts exist.
    """
    try:
        mds = [os.path.join(OUTPUT_DIR, n) for n in os.listdir(OUTPUT_DIR)
               if n.endswith(".md")]
    except OSError:
        return None
    return max(mds, key=os.path.getmtime, default=None)


def orphaned_recordings() -> list:
    """WAVs in recordings/ that have no Markdown file in output/.

    These are recordings whose transcription never finished (for example the
    process died mid-whisper) and that would otherwise be forgotten.

    Matching is by name prefix: an md name may be the wav stem plus a suffix,
    and unique_path() may append _2. Current names
    (HH-MM_DD-MM-YY_DAILY|MID) do not share a prefix with the wav at all, so
    the fallback below catches them. When there is no prefix match (typical
    for imported files, which are named differently from their source), the
    function looks for the wav path inside the md contents. That is slower,
    but it runs only for files the first check did not match.
    """
    if not os.path.isdir(REC_DIR):
        return []
    stems = set()
    if os.path.isdir(OUTPUT_DIR):
        for name in os.listdir(OUTPUT_DIR):
            if name.endswith(".md"):
                stems.add(os.path.splitext(name)[0])

    md_sources = None    # computed lazily, only if needed
    orphans = []
    for name in sorted(os.listdir(REC_DIR)):
        if not name.endswith(".wav"):
            continue
        base = os.path.splitext(name)[0]
        if any(mark in base for mark in _DERIVED_MARKS):
            continue
        if any(stem == base or stem.startswith(base + "_") for stem in stems):
            continue
        if md_sources is None:
            md_sources = _md_sources()
        wav_path = os.path.join(REC_DIR, name)
        if any(wav_path in src for src in md_sources):
            continue
        orphans.append(wav_path)
    return orphans


# ─────────────────────────────── Audio / ASR ──────────────────────────

SAMPLE_RATE = 16000          # Whisper works at 16 kHz
CHANNELS = 1

# large-v3-turbo: compared with small it loops on repeated text less and
# keeps technical terms better; it runs at ~20x realtime (small: ~30x) and
# takes ~1.5 GB on disk. EQ_WHISPER_MODEL=small selects the lighter model.
MODEL_NAME = os.environ.get("EQ_WHISPER_MODEL", "large-v3-turbo")

# Engine. "mlx" runs MLX Whisper on the Metal GPU for both decoding and
# per-window language detection; both use the SAME model (MLX_MODEL_REPO).
# "whisper" is the openai-whisper CPU engine, kept as a fallback in case MLX
# fails (new model version, broken HF cache, etc.):
#     EQ_ENGINE=whisper python3 app/recorder.py
ENGINE = os.environ.get("EQ_ENGINE", "mlx").strip().lower()

# mlx-community repositories are not named uniformly: turbo has no "-mlx" suffix.
_MLX_REPOS = {"large-v3-turbo": "mlx-community/whisper-large-v3-turbo"}
MLX_MODEL_REPO = (os.environ.get("EQ_MLX_MODEL")
                  or _MLX_REPOS.get(MODEL_NAME)
                  or f"mlx-community/whisper-{MODEL_NAME}-mlx")

# Auto-detect (None) is the default. Meetings mix Ukrainian (main), Russian
# (some participants) and English (technical terms), so any fixed value
# breaks recognition of the other languages.
#
# Stock whisper detects the language ONCE on the first 30 seconds and applies
# it to the whole file, with no per-segment switching, so a recording with a
# Russian opening would be transcribed entirely as `ru` and mangle Ukrainian
# words. Our own detection pass avoids this (see
# transcriber.detect_language_windows and PER_CHUNK_LANG below).
#
# A specific language can be forced only through the environment (language
# detection is then disabled and the whole file uses one language):
#     EQ_WHISPER_LANG=uk    — a purely Ukrainian meeting
#     EQ_WHISPER_LANG=en    — an English-language meeting
_lang = os.environ.get("EQ_WHISPER_LANG", "auto").strip().lower()
LANGUAGE = None if _lang in ("", "auto", "none") else _lang

# ──────────────────── Per-window language detection ───────────────────
#
# The language is detected here, in 30 s windows (exactly what the whisper
# encoder sees at once), and each language run is transcribed separately with
# its language already known. The cost is one encoder pass per window, a few
# percent of total time; the gain is that Ukrainian is not read as Russian
# just because the meeting opened in Russian.
PER_CHUNK_LANG = os.environ.get("EQ_PER_CHUNK_LANG", "1") != "0"

# Languages that actually occur in meetings. The whisper detector knows 99
# languages and readily answers bg/sr/mk/be on noise or silence; anything not
# in this list is treated as unreliable and passed to the decoder as None
# (auto) instead of forcing a wrong language.
#
# Polish is deliberately not a candidate: it is not needed, and the detector
# kept taking Ukrainian speech for Polish.
SUPPORTED_LANGS = ("uk", "ru", "en")

LANG_WINDOW_SEC = 30         # detection window = whisper encoder input
LANG_MIN_PROB = 0.6          # below this the window is "unsure" and joins its neighbour

# Silence/noise: on it the whisper detector confidently answers `en`
# (p ≈ 0.99); that is a known artifact, not a language. A single such window
# in the tail of a file can assign `en` to the whole file, so there are two
# thresholds:
#   MIN_RMS       — absolute minimum (below it the window is certainly not
#                   speech);
#   SILENCE_RATIO — relative to the median of the file's OWN windows, because
#                   recording levels differ a lot between sources.
LANG_MIN_RMS = 0.008
LANG_SILENCE_RATIO = 0.35
LANG_RUN_MIN_SEC = 60        # a shorter run is not split off; it merges into a neighbour
LANG_HINT_PROB = 0.8         # "different language here" tag in the MD for short inserts

# Smoothing: a window's language is the argmax over the summed probabilities
# of the window and its ±N neighbours (weight 2 at the centre, 1 for
# neighbours). It targets the hardest pair, uk↔ru: shared phonetics give
# near-equal 0.45/0.55 scores that would flip every window and split the file
# into dozens of runs. A "sticky" first language (a higher bar for switching)
# is deliberately not used: a wrong `ru` at the start could then never be
# left.
LANG_SMOOTH_RADIUS = 1

# Preference for Ukrainian on ru/uk ties: the whisper detector is
# systematically biased towards Russian, which is far better represented in
# its training data. On a verified Ukrainian fragment it answers ru 0.89 vs
# uk 0.05. Comparing avg_logprob of the two decodes does not fix this,
# because ru wins the logprob even where its own output is visibly mangled,
# so the only working lever is a prior weight.
#
# 2.0 = Russian must be at least twice as likely as Ukrainian for a window
# to go as ru. Confident Russian (ru ≥ 0.67 with uk ≤ 0.33) is untouched,
# while near-ties such as 0.48/0.39 go to Ukrainian, which are exactly the
# windows where Ukrainian words would otherwise be mangled. 1.0 disables it.
LANG_UK_BIAS = float(os.environ.get("EQ_LANG_UK_BIAS", "2.0"))

# ── Ukrainian priority: main switch ──────────────────────────────────────
# For meetings where some participants speak Russian.
#
#   False (default) — per-window detection stays as is, with an explicit
#       preference for Ukrainian on ties (see LANG_UK_MARGIN below).
#   True            — ALL segments are decoded with language="uk" and the
#       language scan is skipped entirely (which also saves ~6 % of time).
#
# True is NOT translation. In transcribe mode whisper does not translate; it
# recognises sounds within the given language, so a Russian utterance decoded
# with language="uk" comes out as phonetic mush, not as Ukrainian. Whisper
# cannot translate ru→uk at all: task="translate" translates ONLY into
# English. So True makes sense where the meeting is actually Ukrainian and
# the detector wrongly moves some windows to ru.
FORCE_UKRAINIAN = os.environ.get("EQ_FORCE_UKRAINIAN", "0") == "1"

# uk/ru tie threshold when FORCE_UKRAINIAN=False. If Russian wins by less
# than this margin, the window goes to Ukrainian. It applies AFTER
# LANG_UK_BIAS: the bias is a prior multiplier over the whole scale, while
# this is an explicit rule at the boundary (0.52/0.40 after the bias is
# formally ru, although the difference is within noise). 0.0 disables it and
# leaves a plain argmax.
LANG_UK_MARGIN = float(os.environ.get("EQ_LANG_UK_MARGIN", "0.15"))

# The prompt contains no names, only language context. A prompt listing
# speaker names is echoed verbatim into the transcript and pushes whisper
# into a repetition loop; each loop costs 6 temperature fallbacks x beam 5.
#
# The prompt does not affect language choice (detection works on the
# mel-spectrogram, before the decoder); it only tells the decoder that
# code-switching is expected.
INITIAL_PROMPT = os.environ.get("EQ_WHISPER_PROMPT") or (
    "Розмова може бути українською, російською або англійською мовою."
)

# The default prompt is written in Ukrainian, so when the language is already
# KNOWN (our detection returned e.g. `en`), passing it to the decoder is
# harmful: it pulls the output towards Ukrainian. The default prompt is used
# only in auto mode; a custom one (EQ_WHISPER_PROMPT, which may carry
# terminology) is always used.
PROMPT_IS_CUSTOM = bool(os.environ.get("EQ_WHISPER_PROMPT"))

CHUNK_THRESHOLD_SEC = 1800   # longer files are split into chunks
CHUNK_SIZE_SEC = 600         # chunk = 10 minutes

# ffmpeg audio-cleaning filter (applied exactly once)
AUDIO_FILTER = ("highpass=f=100,lowpass=f=8000,"
                "afftdn=nf=-25,dynaudnorm=f=150:g=15")

# ─────────────────────────────── Appearance ───────────────────────────

ICON_IDLE = "🎙️"
ICON_REC = "🔴"
ICON_WORK = "⏳"
ICON_DONE = "✅"
DONE_FLASH_SEC = 10          # how long the ✅ status stays in the panel

BG = "#1C1C1E"
BG_SOFT = "#2C2C2E"
FG = "#FFFFFF"
MUTED = "#8E8E93"
DIM = "#636366"
RED = "#FF453A"
GREEN = "#30D158"
GOLD = "#B0814E"
FONT = "SF Pro Text"

# ─────────────────────────────── Helpers ──────────────────────────────


def tc(seconds: float) -> str:
    """Seconds → MM:SS or H:MM:SS."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def unique_path(directory: str, stem: str, ext: str) -> str:
    """A path that does not overwrite an existing file."""
    path = os.path.join(directory, stem + ext)
    n = 2
    while os.path.exists(path):
        path = os.path.join(directory, f"{stem}_{n}{ext}")
        n += 1
    return path


def notify(title: str, subtitle: str, message: str) -> None:
    """macOS push notification via osascript.

    On some systems the banner never appears (notification permission is
    off), so it is not the only signal: the status is always visible in the
    app panel too.
    """
    try:
        text = message.replace('"', "'")
        sub = subtitle.replace('"', "'")
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{text}" with title "{title}" '
             f'subtitle "{sub}"'],
            check=False, timeout=10,
        )
    except Exception:                                # noqa: BLE001
        pass


def hotkeys_enabled() -> bool:
    """Whether the process has the Accessibility permission.

    Without it the global hotkeys (Cmd+E / Cmd+Shift+H) silently do not
    work: NSEvent returns a monitor, but no events arrive.
    """
    try:
        import ctypes
        import ctypes.util
        path = ctypes.util.find_library("ApplicationServices")
        lib = ctypes.cdll.LoadLibrary(path)
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(lib.AXIsProcessTrusted())
    except Exception:                                # noqa: BLE001
        return True          # cannot check — do not show the hint


def open_accessibility_settings() -> None:
    subprocess.run(
        ["open", "x-apple.systempreferences:com.apple.preference.security"
                 "?Privacy_Accessibility"], check=False)


def running_instance_pid():
    """PID of an already running engine (not this process), or None.

    Two independent sources, because each one alone is unreliable:

    1) The bundle id via NSRunningApplication finds an instance started from
       ANY bundle copy, even if PID_FILE is missing. It works only with the
       native launcher (build_app.sh): Homebrew's framework Python
       re-launches itself as Python.app and registers as org.python.python,
       which this lookup cannot see.
    2) PID_FILE plus the process command line covers runs through
       ./start.sh, which have no bundle id at all.
    """
    me = os.getpid()
    try:
        from AppKit import NSRunningApplication
        apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(
            BUNDLE_ID)
        for app in apps or []:
            pid = int(app.processIdentifier())
            if pid != me and not app.isTerminated():
                return pid
    except Exception:                                # noqa: BLE001
        pass

    try:
        with open(PID_FILE, "r", encoding="utf-8") as fh:
            pid = int(fh.read().strip())
    except (OSError, ValueError):
        return None
    if pid == me:
        return None
    try:
        os.kill(pid, 0)          # signal 0 only checks that the process exists
    except OSError:
        return None
    # os.kill(pid, 0) alone is not enough: if the previous process died
    # without a clean quit_app() (kill -9, crash, reboot), PID_FILE keeps a
    # stale number that sooner or later is reused by an unrelated process,
    # and the engine would exit silently on every launch. So the command line
    # is checked as well.
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=3, check=False,
        ).stdout
    except Exception:                                # noqa: BLE001
        return pid               # cannot check — assume it is alive

    # The command line depends on how the app was started:
    #   ./start.sh       → "….venv/bin/python3.10 app/recorder.py"
    #   app bundle       → ".../EQ Recorder.app/Contents/MacOS/EQ Recorder"
    # Matching "EQ Recorder.app" covers the bundle case.
    if "recorder.py" in out or f"{APP_NAME}.app" in out:
        return pid
    return None


def already_running() -> bool:
    """True if the engine is already running (so two processes never start)."""
    return running_instance_pid() is not None


def activate_instance(pid: int) -> bool:
    """Bring the already running instance to the front (instead of an alert).

    It shows its own panel: AppDelegate.applicationDidBecomeActive_.
    """
    try:
        from AppKit import NSRunningApplication
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is None:
            return False
        # 1 << 1 = NSApplicationActivateIgnoringOtherApps
        return bool(app.activateWithOptions_(1 << 1))
    except Exception:                                # noqa: BLE001
        return False


def claim_pid() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(PID_FILE, "w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))


def stamp() -> str:
    """Timestamp for file names."""
    return time.strftime("%Y-%m-%d_%H-%M")
