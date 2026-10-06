#!/usr/bin/env python3
# Run via ./start.sh or .venv/bin/python3.10 app/recorder.py; the shebang
# does not hardcode a personal path (the venv lives inside the project).
"""
🎙️ EQ Recorder — Dock app: record / import → Whisper → Markdown.

Runs locally: no API keys, no internet after the model is downloaded.

ARCHITECTURE:
    One process, one NSApplication. The app icon lives in the Dock (a regular
    app, LSUIElement=false); clicking it shows/hides the control panel. The
    AppKit panel (app/ui.py) is itself the NSApplication, so the engine
    (Engine) and the UI live in the same process and the panel reads the
    engine's state directly, with no second process or file-based IPC.

Mode:
    python3 app/recorder.py           # Dock app + engine
"""

import datetime
import os
import queue
import sys
import threading
import time
import traceback
import wave

# Apple Accelerate (vecLib), torch's BLAS backend here, occasionally breaks
# a native call when used with several threads on macOS (torch fails inside
# permute()/set_grad_enabled() with a meaningless TypeError). Whisper
# transcription runs in a background thread while the AppKit loop lives on
# the main thread, and that combination provokes the race. Single-threaded
# BLAS avoids it; these are set BEFORE numpy/torch are imported, since later
# is too late.
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np
import sounddevice as sd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as C                                          # noqa: E402
import strings as S                                         # noqa: E402
import transcriber                                          # noqa: E402
from transcribe_queue import TranscriptionQueue              # noqa: E402


def _stamp_to_dt(wav_path: str) -> datetime.datetime:
    """`meet_2026-01-15_10-00.wav` → datetime. Falls back to the file's mtime.

    The recording time comes from the name, not "now": otherwise the MD header
    of a re-transcribed file would show the re-transcription date.
    """
    name = os.path.splitext(os.path.basename(wav_path))[0]
    for part in ("_".join(name.split("_")[1:3]), name):
        try:
            return datetime.datetime.strptime(part, "%Y-%m-%d_%H-%M")
        except ValueError:
            continue
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(wav_path))
    except OSError:
        return datetime.datetime.now()


def write_wav(path: str, frames: np.ndarray) -> None:
    """Saves float32 [-1..1] as a 16-bit PCM WAV."""
    pcm = np.clip(frames, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(C.CHANNELS)
        w.setsampwidth(2)
        w.setframerate(C.SAMPLE_RATE)
        w.writeframes(pcm.tobytes())


# ══════════════════════════════ ENGINE ═════════════════════════════════


class Engine:
    """Recording + transcription queue. No UI, only public state and callbacks.

    The engine state is ONLY about recording (idle / recording). Transcription
    lives in its own queue and thread, so there is no "working" state that
    would block the record button while whisper runs.
    """

    IDLE, RECORDING = "idle", "recording"

    def __init__(self):
        self.state = self.IDLE
        self.status = S.STATUS_READY
        self.progress = 0.0
        self.last_md = None
        self.last_name = ""

        self._chunks: list = []
        self._stream = None
        self._t0 = 0.0
        self._started_at = None
        self._duration = 0.0

        # Latest transcription errors by wav path: the file card in the UI
        # shows a separate "error" state instead of silently falling back to
        # "no transcript". Kept in process memory only and lost on restart;
        # it means "the last attempt failed", not a persistent error log.
        self.last_errors: dict = {}

        # Events for the UI (main thread): queue callbacks arrive from the
        # worker thread, so they only put events here and the panel's AppKit
        # timer does the drawing.
        self.events: "queue.Queue[tuple]" = queue.Queue()

        def _on_done(item, saved, md):
            self.last_errors.pop(item["wav"], None)
            self.events.put(("done", (item, saved)))

        def _on_empty(item, saved):
            self.last_errors.pop(item["wav"], None)
            self.events.put(("empty", (item, saved)))

        def _on_error(item, msg):
            self.last_errors[item["wav"]] = msg
            self.events.put(("error", f"{item['label']}: {msg}"))

        self.tq = TranscriptionQueue(
            on_done=_on_done,
            on_empty=_on_empty,
            on_error=_on_error,
            on_status=self._on_queue_status,
            on_progress=self._on_queue_progress,
        )

        os.makedirs(C.STATE_DIR, exist_ok=True)

        # Remove intermediate files left by a killed process. This is safe
        # here: the queue is idle, so nothing is holding them.
        left = C.clean_tmp()
        if left:
            print(f"{C.APP_NAME}: прибрано {left} проміжних файлів",
                  file=sys.stderr)

        threading.Thread(target=self._preload_model, daemon=True).start()

    # ── state ─────────────────────────────────────────────────────────

    @property
    def elapsed(self) -> float:
        if self.state == self.RECORDING:
            return time.time() - self._t0
        return self._duration

    # ── queue: callbacks from the worker thread ───────────────────────
    #
    # Progress does NOT go through self.events: whisper reports it dozens of
    # times per second and would flood the event queue. Instead it is written
    # to a field, and the panel timer reads tq.snapshot() every 0.5 s.

    def _on_queue_progress(self, item, pct):         # noqa: ARG002
        self.progress = pct

    def _on_queue_status(self, item, text):          # noqa: ARG002
        self.status = text

    # ── model ─────────────────────────────────────────────────────────

    def _preload_model(self):
        try:
            transcriber.preload_model()
            self.events.put(("model_ready", None))
        except Exception as exc:                     # noqa: BLE001
            self.events.put(("model_fail", str(exc)))

    # ── recording ─────────────────────────────────────────────────────

    def toggle(self) -> None:
        if self.state == self.IDLE:
            self.start()
        elif self.state == self.RECORDING:
            self.stop()

    def start(self) -> bool:
        self._chunks = []
        try:
            self._stream = sd.InputStream(
                samplerate=C.SAMPLE_RATE, channels=C.CHANNELS,
                dtype="float32", callback=self._audio_cb,
            )
            self._stream.start()
        except Exception as exc:                     # noqa: BLE001
            self._stream = None
            self.status = S.STATUS_MICROPHONE_ERROR.format(exc=exc)
            return False

        self.state = self.RECORDING
        self._t0 = time.time()
        self._started_at = datetime.datetime.now()
        self.progress = 0.0
        self.status = S.STATUS_RECORDING
        return True

    def _audio_cb(self, indata, frames, time_info, status):  # noqa: ARG002
        self._chunks.append(indata.copy())

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:                        # noqa: BLE001
                pass
            self._stream = None

        duration = time.time() - self._t0
        frames = (np.concatenate(self._chunks, axis=0).flatten()
                  if self._chunks else np.zeros(0, dtype=np.float32))
        self._chunks = []
        self._duration = duration

        if len(frames) < C.SAMPLE_RATE // 2:
            self.state = self.IDLE
            self._duration = 0.0
            self.status = S.STATUS_TOO_SHORT
            return

        os.makedirs(C.REC_DIR, exist_ok=True)
        stamp = self._started_at.strftime("%Y-%m-%d_%H-%M")
        wav_path = C.unique_path(C.REC_DIR, f"meet_{stamp}", ".wav")
        write_wav(wav_path, frames)

        # Queue it and go idle IMMEDIATELY: the next recording can start right
        # away while whisper finishes this file in its own thread.
        self.tq.add(wav_path, source_label=wav_path,
                    started=self._started_at, duration=duration)
        self.state = self.IDLE
        self.progress = 0.0
        self.status = S.STATUS_QUEUED_FILE.format(name=os.path.basename(wav_path))

    # ── file import ───────────────────────────────────────────────────

    def start_import(self, filepath: str) -> None:
        """Converts any audio/video file and queues it.

        There is no "busy" restriction: an import can run during a recording
        or on top of an already busy queue; the file simply becomes the next
        one.
        """
        if not filepath or not os.path.exists(filepath):
            self.status = S.STATUS_FILE_NOT_FOUND
            return

        started = datetime.datetime.now()
        self.status = S.STATUS_CONVERTING.format(name=os.path.basename(filepath))

        def worker():
            # Conversion also runs in a thread: ffmpeg on a half-hour video
            # must not freeze the app.
            import audio_import
            try:
                wav_path = audio_import.convert_to_wav(filepath)
                self.tq.add(wav_path, source_label=filepath, started=started,
                            duration=transcriber.get_duration(wav_path))
                self.events.put(("queued", os.path.basename(filepath)))
            except Exception as exc:                 # noqa: BLE001
                traceback.print_exc()
                self.events.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def shutdown(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:                        # noqa: BLE001
                pass
            self._stream = None


# ─────────────────────────────── main ─────────────────────────────────


def run_app():
    other = C.running_instance_pid()
    if other is not None:
        # Instead of an "ALREADY RUNNING" alert, bring the running instance
        # forward like any regular Mac app. The alert is only a fallback when
        # activation fails.
        if C.activate_instance(other):
            print(f"{C.APP_NAME}: рушій уже запущено (pid {other}) — "
                  f"активував його, виходжу.", file=sys.stderr)
        else:
            C.notify(C.APP_NAME, S.NOTIFY_ALREADY_RUNNING_TITLE,
                     S.NOTIFY_ALREADY_RUNNING_BODY.format(app=C.APP_NAME.upper()))
            print(f"{C.APP_NAME}: рушій уже запущено (pid {other}) — виходжу.",
                  file=sys.stderr)
        return
    C.claim_pid()

    # ffmpeg is checked IMMEDIATELY: when launched from Finder PATH is
    # trimmed, and without this check the problem would only surface after a
    # long recording.
    tools_ok, tools_msg = C.media_tools_ok()
    print(f"{C.APP_NAME}: {tools_msg}", file=sys.stderr)

    import ui
    ui.run_app(Engine, tools_ok, tools_msg)


def main():
    return run_app()


if __name__ == "__main__":
    sys.exit(main())
