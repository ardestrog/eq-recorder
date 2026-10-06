"""Import of existing audio/video files → 16 kHz mono WAV for Whisper."""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as C                                          # noqa: E402
import strings as S                                         # noqa: E402

SUPPORTED_EXTS = ["mp3", "wav", "m4a", "aac", "ogg",
                  "mp4", "mov", "avi", "mkv"]


# ─────────────────────────── File picker ──────────────────────────────


def _make_panel():
    from AppKit import NSApp, NSOpenPanel
    NSApp().activateIgnoringOtherApps_(True)         # bring the panel to the front
    panel = NSOpenPanel.openPanel()
    panel.setTitle_(S.PICKER_TITLE)
    panel.setCanChooseFiles_(True)
    panel.setCanChooseDirectories_(False)
    panel.setAllowsMultipleSelection_(False)
    panel.setAllowedFileTypes_(SUPPORTED_EXTS)
    return panel


def _panel_path(panel) -> str:
    urls = panel.URLs()
    if not urls or len(urls) == 0:
        return ""
    return str(urls[0].path())


def pick_file_native(on_pick=None) -> str:
    """File picker via NSOpenPanel.

    If on_pick(path) is passed, the panel opens asynchronously and does not
    block the app's main thread (otherwise the app would freeze while the
    user browses for a file). Returns "" immediately.
    """
    try:
        panel = _make_panel()
    except Exception:                                # noqa: BLE001
        return ""

    if on_pick is not None:
        try:
            def completion(result):
                on_pick(_panel_path(panel) if result == 1 else "")

            panel.beginWithCompletionHandler_(completion)
            return ""
        except Exception:                            # noqa: BLE001
            pass                                     # fall back to modal mode

    try:
        if panel.runModal() != 1:                    # 1 = NSModalResponseOK
            return ""
        path = _panel_path(panel)
    except Exception:                                # noqa: BLE001
        return ""
    if on_pick is not None:
        on_pick(path)
    return path


# ─────────────────────────── Conversion ───────────────────────────────


def convert_to_wav(filepath: str) -> str:
    """Any format → 16 kHz mono WAV in recordings/.

    Cleanup (highpass/denoise/dynaudnorm) is NOT applied here: enhance_audio()
    runs later in the pipeline, and processing twice degrades quality.
    """
    if not filepath or not os.path.exists(filepath):
        raise FileNotFoundError(filepath or S.ERR_EMPTY_PATH)

    os.makedirs(C.REC_DIR, exist_ok=True)
    stem = Path(filepath).stem[:60] + "_imported"
    output_path = C.unique_path(C.REC_DIR, stem, ".wav")

    try:
        res = subprocess.run(
            [C.FFMPEG, "-i", filepath,
             "-vn",                                  # the video stream is not needed
             "-ar", str(C.SAMPLE_RATE), "-ac", str(C.CHANNELS),
             output_path, "-y", "-loglevel", "error"],
            capture_output=True, text=True, timeout=7200,
        )
    except FileNotFoundError:
        # PATH without /opt/homebrew/bin is typical when launched from Finder/.app
        raise RuntimeError(
            S.ERR_FFMPEG_MISSING.format(path=C.FFMPEG)
        ) from None

    if res.returncode != 0:
        # check=True is not used: CalledProcessError carries no stderr, so the
        # reason for the ffmpeg failure would be invisible in the UI and logs.
        detail = (res.stderr or "").strip().splitlines()
        tail = detail[-1] if detail else f"code {res.returncode}"
        raise RuntimeError(S.ERR_FFMPEG_CONVERT_FAILED.format(detail=tail))

    if not os.path.exists(output_path) or os.path.getsize(output_path) < 1024:
        raise RuntimeError(S.ERR_FFMPEG_NO_AUDIO)
    return output_path
