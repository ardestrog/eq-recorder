"""FIFO transcription queue: recording never waits for whisper.

MODULE NAME. Deliberately not `queue.py`: app/ is on sys.path (recorder.py
calls sys.path.insert(0, app_dir)), so app/queue.py would shadow the stdlib
`queue` for the whole app, while recorder.py itself does `import queue` and
uses queue.Queue/queue.Empty. A file with that name would crash the app at
startup with a symptom ("ImportError: cannot import name Empty") that does
not point at the cause.

ONE WORKER. Two whisper runs in parallel on the CPU are not faster: they
compete for the same cores and both take about twice as long. A FIFO queue
with one thread: while the first file is processed the second waits, and
recording a new one is always available.

The queue is a deque under a Condition rather than a queue.Queue: the panel
must be able to remove a waiting item, and queue.Queue does not allow
inspecting or rearranging its contents.
"""

import collections
import datetime
import os
import sys
import threading
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import strings as S                                          # noqa: E402
import transcriber                                           # noqa: E402


class TranscriptionQueue:
    """Queue of files to transcribe, served by a single worker thread.

    Callbacks are invoked FROM THE WORKER THREAD, not the main thread. They
    must be cheap and must not touch the UI: in recorder.py they only put
    events into engine.events, and the panel's AppKit timer does the drawing.
    """

    def __init__(self, on_done=None, on_progress=None, on_status=None,
                 on_empty=None, on_error=None):
        # Callbacks are set BEFORE the thread starts. In the opposite order the
        # worker could pick up the first file before the constructor has set
        # the attributes and fail with AttributeError in the first
        # on_progress.
        self.on_done = on_done
        self.on_progress = on_progress
        self.on_status = on_status
        self.on_empty = on_empty
        self.on_error = on_error

        # One lock (via the Condition) guards all visible state: the main
        # thread reads it (every 0.5 s from the panel timer) and the worker
        # writes it.
        self._cond = threading.Condition()
        self._pending = collections.deque()
        self._current = None
        self._current_pct = 0.0
        self._done_count = 0
        self._seq = 0

        self._thread = threading.Thread(target=self._worker, daemon=True,
                                        name="eq-transcribe")
        self._thread.start()

    # ── public API ────────────────────────────────────────────────────

    def add(self, wav_path: str, source_label: str = None,
            started: datetime.datetime = None,
            duration: float = None) -> dict:
        """Puts a file in the queue. Returns the created item."""
        item = {
            "wav": wav_path,
            "label": source_label or os.path.basename(wav_path),
            "source": source_label or wav_path,
            # started/duration belong to the SPECIFIC file, not the engine:
            # while the first one is transcribed the user may already be
            # recording the second, and a shared engine._started_at would be
            # overwritten with another file's time.
            "started": started or datetime.datetime.now(),
            "duration": duration,
        }
        with self._cond:
            self._seq += 1
            item["id"] = self._seq
            self._pending.append(item)
            self._cond.notify()
        return item

    def remove_pending(self, item_id: int) -> bool:
        """Removes an item that has not started yet. Leaves the active one alone."""
        with self._cond:
            for index, item in enumerate(self._pending):
                if item["id"] == item_id:
                    del self._pending[index]
                    return True
        return False

    def snapshot(self) -> dict:
        """State snapshot for the UI (safe from any thread)."""
        with self._cond:
            return {
                "busy": self._current is not None,
                "current": self._current["label"] if self._current else "",
                "current_id": self._current["id"] if self._current else None,
                "current_wav": self._current["wav"] if self._current else "",
                "progress": round(self._current_pct, 1),
                "pending": [{"id": item["id"], "label": item["label"],
                            "wav": item["wav"]} for item in self._pending],
                "pending_count": len(self._pending),
                "done_count": self._done_count,
            }

    @property
    def busy(self) -> bool:
        with self._cond:
            return self._current is not None

    # ── worker ────────────────────────────────────────────────────────

    def _worker(self):
        while True:
            with self._cond:
                while not self._pending:
                    self._cond.wait()
                item = self._pending.popleft()
                self._current = item
                self._current_pct = 0.0
            try:
                self._process(item)
            except Exception as exc:                 # noqa: BLE001
                # One bad file must not kill the worker; otherwise the queue
                # goes silent for good and looks like a hang from outside.
                traceback.print_exc()
                self._fire(self.on_error, item, str(exc))
            finally:
                with self._cond:
                    self._current = None
                    self._current_pct = 0.0

    @staticmethod
    def _fire(callback, *args):
        if not callback:
            return
        try:
            callback(*args)
        except Exception:                            # noqa: BLE001
            traceback.print_exc()                    # a UI failure must not kill the worker

    def _process(self, item: dict):
        enhanced = None
        try:
            self._fire(self.on_status, item, S.PROGRESS_CLEANING_AUDIO)
            audio_for_asr = transcriber.enhance_audio(item["wav"])
            if audio_for_asr != item["wav"]:
                enhanced = audio_for_asr

            duration = item["duration"]
            if not duration:
                duration = transcriber.get_duration(item["wav"])

            def on_progress(pct):
                with self._cond:
                    self._current_pct = pct
                self._fire(self.on_progress, item, pct)

            def on_status(text):
                self._fire(self.on_status, item, text)

            result = transcriber.transcribe_with_progress(
                audio_for_asr, on_progress=on_progress, on_status=on_status,
                # The checkpoint is bound to the ORIGINAL, not to _enhanced.wav,
                # which is temporary and whose path can change between runs.
                checkpoint_key=item["wav"])

            # The MD name is time first, then date ("18-02_25-09-26"). It does
            # not affect the WAV in recordings/, which keeps %Y-%m-%d_%H-%M
            # (parsed by _stamp_to_dt() and matched by orphaned_recordings()).
            # Since the date is not at the start of the MD name, the prefix
            # fast path in orphaned_recordings() does not match; the slower
            # fallback through _md_sources() covers that case.
            stem = transcriber.smart_filename(item["started"])
            title = f"Зустріч {item['started'].strftime('%Y-%m-%d %H:%M')}"
            md = transcriber.build_md(result, item["started"], duration,
                                      item["source"], title)
            saved = transcriber.save_markdown(md, stem)

            # Only once the MD is on disk is the checkpoint no longer needed.
            # The path is taken from result rather than recomputing the key,
            # so the smallest mismatch (e.g. a different duration) cannot
            # leave a stale file behind.
            ckpt = result.get("checkpoint")
            if ckpt and os.path.exists(ckpt):
                try:
                    os.remove(ckpt)
                except OSError:
                    pass

            # The MD is always saved, even when empty; otherwise it would look
            # like "processed, but no file". The WAV stays for a retry.
            if (result.get("text") or "").strip():
                with self._cond:
                    self._done_count += 1
                self._fire(self.on_done, item, saved, md)
            else:
                self._fire(self.on_empty, item, saved)
        finally:
            if enhanced and os.path.exists(enhanced):
                try:
                    os.remove(enhanced)
                except OSError:
                    pass
