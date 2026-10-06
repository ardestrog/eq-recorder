#!/bin/bash
# Regenerates the EQ Recorder icon from a single input PNG and propagates it
# to every place macOS caches the app icon (Dock, Finder, About).
#
# Usage:
#   ./scripts/update_icon.sh                       # uses assets/app_icon_source.png
#   ./scripts/update_icon.sh path/to/your/logo.png # or an explicit path
#
# Steps:
#   1. Validates the input PNG (square, ideally 1024×1024).
#   2. Applies the standard macOS rounded-square mask (scripts/_squircle_mask.py),
#      so any logo without its own transparency gets the same rounded corners
#      as neighbouring Dock icons instead of a bare square.
#   3. Generates the full set of sizes (.iconset) with sips.
#   4. Builds the .icns with iconutil into resources/icon.icns (the name
#      Info.plist already uses as CFBundleIconFile, so build_app.sh needs no
#      change).
#   5. Updates resources/icon.png (the logo in the panel header).
#   6. Rebuilds the bundle in /Applications (the canonical copy) if it exists.
#   7. Clears the system icon cache (touch + killall Dock/Finder), otherwise
#      the old icon can stay visible after the file is replaced.
#
# The masking is part of this script, not a manual edit: whoever later drops
# in another assets/app_icon_source.png and runs update_icon.sh gets it with
# no extra steps.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_PNG="${1:-$PROJECT_DIR/assets/app_icon_source.png}"
ICONSET="$PROJECT_DIR/resources/icon.iconset"
ICNS_OUT="$PROJECT_DIR/resources/icon.icns"
PNG_OUT="$PROJECT_DIR/resources/icon.png"

if [ ! -x "$PROJECT_DIR/.venv/bin/python3.10" ]; then
  echo "✗ Немає venv: $PROJECT_DIR/.venv (потрібен для маскування іконки, Pillow)" >&2
  echo "  Створи: /opt/homebrew/bin/python3.10 -m venv \"$PROJECT_DIR/.venv\" && \"$PROJECT_DIR/.venv/bin/pip\" install -r \"$PROJECT_DIR/requirements.txt\"" >&2
  exit 1
fi

if [ ! -f "$SOURCE_PNG" ]; then
  echo "✗ Не знайдено вхідний файл: $SOURCE_PNG" >&2
  echo "  Поклади свій PNG сюди: $PROJECT_DIR/assets/app_icon_source.png" >&2
  exit 1
fi

# ── size check ─────────────────────────────────────────────────
W=$(sips -g pixelWidth "$SOURCE_PNG" | awk '/pixelWidth/{print $2}')
H=$(sips -g pixelHeight "$SOURCE_PNG" | awk '/pixelHeight/{print $2}')
if [ "$W" != "$H" ]; then
  echo "✗ Файл не квадратний (${W}×${H}). Потрібен квадратний PNG (бажано 1024×1024)." >&2
  exit 1
fi
if [ "$W" -lt 512 ]; then
  echo "⚠ Попередження: $W px — менше рекомендованих 1024px, найбільші розміри іконки будуть розмиті." >&2
fi
echo "→ Джерело: $SOURCE_PNG (${W}×${H})"

# ── squircle mask (always, applied to a working copy; SOURCE_PNG is untouched) ──
MASKED="$PROJECT_DIR/resources/.icon_masked_tmp.png"
"$PROJECT_DIR/.venv/bin/python3.10" "$PROJECT_DIR/scripts/_squircle_mask.py" \
  "$SOURCE_PNG" "$MASKED"
echo "→ Накладено squircle-маску (кути заокруглені, як у системних іконок)"

# ── .iconset (all sizes + @2x) ────────────────────────────────────────
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
for size in 16 32 64 128 256 512; do
  sips -z "$size" "$size" "$MASKED" \
    --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" "$MASKED" \
    --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
echo "→ Згенеровано $(ls "$ICONSET" | wc -l | tr -d ' ') файлів у .iconset"

# ── .icns ────────────────────────────────────────────────────────────────
iconutil -c icns "$ICONSET" -o "$ICNS_OUT"
rm -rf "$ICONSET"
echo "✓ $ICNS_OUT"

# ── icon.png for the panel header (1024, masked, same look) ─
sips -z 1024 1024 "$MASKED" --out "$PNG_OUT" >/dev/null
rm -f "$MASKED"
echo "✓ $PNG_OUT"

# ── rebuild the bundle if it exists ──────────────────────────────────
for DEST in "/Applications"; do
  if [ -d "$DEST/EQ Recorder.app" ]; then
    echo "→ Пересбираю: $DEST/EQ Recorder.app"
    "$PROJECT_DIR/build_app.sh" "$DEST"
  fi
done

# ── icon cache cleanup ───────────────────────────────────────────────────
# touch + killall Dock/Finder changes the file date but does not always drop
# the cache itself: com.apple.iconservices keeps a separate keyed store
# (store.index), located via getconf DARWIN_USER_CACHE_DIR, and that store is
# what can leave a stale icon attached to the bundle (the Dock shows one
# cache, Finder another). So the cache files are deleted outright instead of
# relying on touch to invalidate them:
for DEST in "/Applications"; do
  [ -d "$DEST/EQ Recorder.app" ] && touch "$DEST/EQ Recorder.app"
done
ICON_CACHE_DIR="$(getconf DARWIN_USER_CACHE_DIR 2>/dev/null || true)"
if [ -n "$ICON_CACHE_DIR" ] && [ -d "$ICON_CACHE_DIR" ]; then
  rm -f "$ICON_CACHE_DIR/com.apple.dock.iconcache"
  rm -rf "$ICON_CACHE_DIR/com.apple.iconservices"
  echo "→ Знищено com.apple.iconservices/dock.iconcache (не лише touch)"
fi
killall iconservicesagent 2>/dev/null || true
killall Dock 2>/dev/null || true
killall Finder 2>/dev/null || true

echo
echo "✓ Готово — кеш іконок знищено, не лише позначено застарілим."
