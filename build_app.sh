#!/bin/bash
# Builds "EQ Recorder.app", a thin bundle around app/recorder.py.
# The code is NOT copied: the bundle runs the files from this folder, so
# edits to app/*.py take effect on the next launch without a rebuild.
#
# The app is a Dock application (LSUIElement=false) with its own window; see
# app/ui.py.
#
# Usage:  ./build_app.sh [destination folder]   (default: /Applications)
#
# Keep ONE copy of the bundle, in /Applications (what the Dock points to).
# Every extra copy runs the same code from this folder and only adds another
# Dock icon and another bundle for TCC to track.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEST_DIR="${1:-/Applications}"
APP="$DEST_DIR/EQ Recorder.app"
# The project's own venv, never the system/Homebrew python3.10: it isolates
# the package versions in requirements.txt from every other tool on the machine.
PY="$PROJECT_DIR/.venv/bin/python3.10"

if [ ! -x "$PY" ]; then
  echo "✗ Немає venv: $PY" >&2
  echo "  Створи його:" >&2
  echo "    /opt/homebrew/bin/python3.10 -m venv \"$PROJECT_DIR/.venv\"" >&2
  echo "    \"$PROJECT_DIR/.venv/bin/pip\" install -r \"$PROJECT_DIR/requirements.txt\"" >&2
  exit 1
fi

echo "→ Збираю: $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# ── launcher ──────────────────────────────────────────────────────────
# The launcher is a tiny native binary (launcher/launcher.m) that embeds
# Python.framework and runs the interpreter IN ITS OWN process:
#  - No exec. Homebrew's framework python (bin/python3.10) is a stub that
#    execv's into Python.framework/.../Resources/Python.app/Contents/MacOS/Python.
#    A bash or shebang launcher therefore registers with LaunchServices as
#    org.python.python (Python.app) instead of com.eq.recorder: a second,
#    generic Dock icon appears, clicking the bundle starts a new process
#    instead of activating the running one, and a second exec after
#    registration confuses RunningBoard's PID version, so WindowServer draws
#    no Dock icon or window.
#  - The executable lives inside the bundle, so NSBundle.mainBundle() is
#    EQ Recorder.app and the bundle id is com.eq.recorder.
#  - The venv is picked up through __PYVENV_LAUNCHER__, the same way the
#    python3.10 stub does it.
#  - Before Python starts, the launcher checks whether com.eq.recorder is
#    already running (see launcher.m), so a duplicate never touches ~/Desktop
#    or triggers a TCC prompt.
# Verify with `lsappinfo list` and `ps` on a running process.
PYCONFIG="/opt/homebrew/bin/python3.10-config"
clang -O2 -fobjc-arc $("$PYCONFIG" --cflags --embed) \
  -DVENV_PYTHON="\"$PY\"" \
  "$PROJECT_DIR/launcher/launcher.m" \
  -o "$APP/Contents/MacOS/EQ Recorder" \
  $("$PYCONFIG" --ldflags --embed) -framework AppKit 2>&1 | grep -v "warning:" || true
rm -rf "$APP/Contents/MacOS/EQ Recorder.dSYM"   # --cflags contains -g
if [ ! -x "$APP/Contents/MacOS/EQ Recorder" ]; then
  echo "✗ Не вдалось зібрати launcher (потрібен Xcode Command Line Tools: xcode-select --install)" >&2
  exit 1
fi

# The PATH fix for ffmpeg (Finder passes a reduced PATH without
# /opt/homebrew/bin) is done by app/config.py (ensure_tool_path()); boot.py
# only redirects stdout/stderr to the log file.
cat > "$APP/Contents/Resources/boot.py" <<BOOT
import os, sys
sys.path.insert(0, "$PROJECT_DIR/app")
_log_fd = os.open("$PROJECT_DIR/app.log",
                  os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
os.dup2(_log_fd, 1)
os.dup2(_log_fd, 2)
import recorder
sys.exit(recorder.main())
BOOT

# ── icon ────────────────────────────────────────────────────────────
if [ -f "$PROJECT_DIR/resources/icon.icns" ]; then
  cp "$PROJECT_DIR/resources/icon.icns" "$APP/Contents/Resources/icon.icns"
fi

# ── font (Roboto Mono, OFL) ─────────────────────────────────────────────
# ATSApplicationFontsPath in Info.plist makes macOS activate the fonts from
# this folder for the app's process only, without installing them system-wide;
# no code is needed for it (this environment has no pyobjc CoreText bindings,
# so registering through CTFontManager is not available).
if [ -d "$PROJECT_DIR/resources/fonts" ]; then
  mkdir -p "$APP/Contents/Resources/Fonts"
  cp "$PROJECT_DIR"/resources/fonts/*.ttf "$APP/Contents/Resources/Fonts/" 2>/dev/null || true
fi

# ── Info.plist ────────────────────────────────────────────────────────
# NSMicrophoneUsageDescription is required: without it macOS shows no
# microphone prompt and the recording is silent.
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>              <string>EQ Recorder</string>
    <key>CFBundleDisplayName</key>       <string>EQ Recorder</string>
    <key>CFBundleExecutable</key>        <string>EQ Recorder</string>
    <key>CFBundleIdentifier</key>        <string>com.eq.recorder</string>
    <key>CFBundleIconFile</key>          <string>icon</string>
    <key>ATSApplicationFontsPath</key>   <string>Fonts</string>
    <key>CFBundlePackageType</key>       <string>APPL</string>
    <key>CFBundleShortVersionString</key><string>2.0</string>
    <key>CFBundleVersion</key>           <string>2.0</string>
    <key>LSMinimumSystemVersion</key>    <string>12.0</string>
    <key>NSHighResolutionCapable</key>   <true/>
    <key>LSUIElement</key>               <false/>
    <key>NSMicrophoneUsageDescription</key>
    <string>EQ Recorder записує аудіо зустрічей для локальної транскрибації.</string>
</dict>
</plist>
PLIST

# ── signing ───────────────────────────────────────────────────────────
# Without a signature spctl rejects the bundle ("no usable signature").
# Ad-hoc (-) is enough for local use without an Apple Developer account.
#
# -r (designated requirement) is essential with the native launcher: without
# it an ad-hoc signature is identified by its cdhash, which changes on EVERY
# build, so macOS (TCC) treats each rebuild as a new app and asks again for
# Desktop access (the project and .venv live there) while the process blocks
# on open(). A requirement tied to the bundle id keeps the permissions
# (Desktop, microphone, Accessibility) stable across builds.
codesign --force --deep --sign - \
  -r='designated => identifier "com.eq.recorder"' "$APP" 2>&1 || true

touch "$APP"
echo "✓ Готово: $APP"
echo "  Перевір: lsappinfo list | grep -A2 '\"EQ Recorder\"'   (має бути bundleID=\"com.eq.recorder\")"
