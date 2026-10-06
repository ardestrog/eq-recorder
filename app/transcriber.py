"""Transcription: audio cleanup, chunked processing of long files, Markdown output."""

import contextlib
import datetime
import json
import os
import subprocess
import sys
import threading
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as C                                          # noqa: E402
import strings as S                                         # noqa: E402

_model = None
_model_lock = threading.Lock()


# ─────────────────────────────── Model ────────────────────────────────


def preload_model() -> None:
    """Warm-up at app start (called from a background thread in recorder.py).

    ENGINE=mlx only makes sure the model files are in the HF cache (downloading
    them if missing) and does NOT build the model. MLX GPU streams are bound
    to the thread that created them: some of the model's arrays (positional
    embeddings, decoder mask) stay lazy and belong to that thread. A model
    built here and used by the queue thread would crash the whole process on
    the first transcription:
        libc++abi: … There is no Stream(gpu, 1) in current thread.
    So get_model() builds the MLX model from the queue thread, which lives
    for the whole process (TranscriptionQueue._worker).
    """
    if C.ENGINE == "mlx":
        from huggingface_hub import snapshot_download
        snapshot_download(C.MLX_MODEL_REPO)
    else:
        get_model()


def get_model(name: str = None):
    """Lazily loads and caches the Whisper model (thread-safe).

    ENGINE=mlx loads the MLX model through mlx_whisper's own ModelHolder. That
    is the same cache mlx_whisper.transcribe() takes its model from (key:
    repo + dtype fp16), so language detection and decoding share ONE instance
    in memory instead of loading 1.5 GB twice. Call only from the queue
    thread; see preload_model().
    """
    global _model
    with _model_lock:
        if _model is None:
            if C.ENGINE == "mlx":
                import mlx.core as mx
                from mlx_whisper.transcribe import ModelHolder
                _model = ModelHolder.get_model(name or C.MLX_MODEL_REPO,
                                               mx.float16)
            else:
                import whisper
                _model = whisper.load_model(name or C.MODEL_NAME)
        return _model


def _decode_options(language=None) -> dict:
    """Decoder options. language=None → whisper detects the language itself.

    The language is a parameter, not a constant: the per-segment pipeline
    passes each piece its own, already detected language (see
    transcribe_with_progress).
    """
    return {
        "language": language,
        "task": "transcribe",
        # 0.0 on the first pass = deterministic; higher temperatures are only
        # a fallback when a segment fails the thresholds (otherwise whisper
        # gets stuck in repetition loops).
        "temperature": (0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
        "best_of": 5,                    # applies when T > 0
        "beam_size": 5,                  # applies when T = 0

        # Both are disabled on purpose:
        #
        # word_timestamps: costs an extra DTW pass per segment, and nothing
        #   reads per-word data — build_md() only uses seg["start"]. Pure
        #   overhead of about 19 % of the runtime.
        #
        # condition_on_previous_text: feeds the previous text back as
        #   context, so one slip into repetition poisons the rest of the file
        #   and multiplies temperature fallbacks. The cost of disabling it is
        #   slightly worse coherence between segments; the gain is much
        #   faster decoding and no repetition loops.
        "word_timestamps": False,
        "condition_on_previous_text": False,

        "no_speech_threshold": 0.6,
        "compression_ratio_threshold": 2.4,
        # A Ukrainian prompt pulls the output towards Ukrainian when
        # language=en is known — see C.PROMPT_IS_CUSTOM.
        "initial_prompt": (C.INITIAL_PROMPT
                           if language is None or C.PROMPT_IS_CUSTOM
                           else None),
        "fp16": False,                   # CPU
        "verbose": False,
    }


@contextlib.contextmanager
def _mlx_progress(on_frac):
    """Same as _whisper_progress, but for mlx_whisper.transcribe.

    mlx_whisper is a separate package with its own transcribe.py module that
    drives tqdm the same way openai-whisper does (same trick with the module
    shadowed by a function; see the comment in _whisper_progress).
    """
    import importlib
    mt = importlib.import_module("mlx_whisper.transcribe")

    real = mt.tqdm.tqdm

    class Hooked(real):
        def __init__(self, *args, **kwargs):
            self._eq_total = kwargs.get("total") or 0
            self._eq_n = 0
            kwargs["disable"] = True
            super().__init__(*args, **kwargs)

        def update(self, n=1):
            self._eq_n += n or 0
            if self._eq_total and on_frac:
                try:
                    on_frac(min(1.0, self._eq_n / self._eq_total))
                except Exception:        # noqa: BLE001
                    pass

    mt.tqdm.tqdm = Hooked
    try:
        yield
    finally:
        mt.tqdm.tqdm = real


def _mlx_transcribe_chunk(chunk_file: str, lang, on_frac) -> tuple:
    """Decodes a piece with MLX Whisper (Metal GPU). Returns (segments, lang).

    Options are the same as for openai-whisper (_decode_options): mlx_whisper's
    DecodingOptions has the same fields. fp16 is True here (not False): on the
    GPU fp16 is the standard, faster mode.
    """
    import mlx_whisper

    opts = _decode_options(lang)
    opts["fp16"] = True
    # MLX Whisper has no beam search (NotImplementedError), so only best_of
    # (sampling) is kept; openai-whisper also enables it at T > 0.
    opts.pop("beam_size", None)
    with _mlx_progress(on_frac):
        result = mlx_whisper.transcribe(
            chunk_file, path_or_hf_repo=C.MLX_MODEL_REPO, **opts)
    detected = lang or result.get("language")
    return result.get("segments") or [], detected


@contextlib.contextmanager
def _whisper_progress(on_frac):
    """Hooks tqdm inside whisper → real percentage in the UI.

    whisper.transcribe has no progress callback, but it drives
    `tqdm.tqdm(total=content_frames)` and calls `pbar.update()`. Without the
    hook, short files (< CHUNK_THRESHOLD_SEC) would sit at 0 % from start to
    finish.

    As a side effect it keeps progress-bar spam out of app.log (disable=True).
    """
    # NOT `import whisper.transcribe as wt`: whisper/__init__.py has
    # `from .transcribe import transcribe`, so the attribute
    # whisper.transcribe is the function, which shadows the module of the
    # same name (AttributeError on .tqdm).
    import importlib
    wt = importlib.import_module("whisper.transcribe")

    real = wt.tqdm.tqdm

    class Hooked(real):
        def __init__(self, *args, **kwargs):
            self._eq_total = kwargs.get("total") or 0
            self._eq_n = 0
            kwargs["disable"] = True     # do not write tqdm to the log
            super().__init__(*args, **kwargs)

        def update(self, n=1):
            # super().update() is a no-op with disable=True, so count here
            self._eq_n += n or 0
            if self._eq_total and on_frac:
                try:
                    on_frac(min(1.0, self._eq_n / self._eq_total))
                except Exception:        # noqa: BLE001
                    pass

    wt.tqdm.tqdm = Hooked
    try:
        yield
    finally:
        wt.tqdm.tqdm = real


# ─────────────────────────────── Audio ────────────────────────────────


def get_duration(path: str) -> float:
    """Duration in seconds via ffprobe (falls back to wave for WAV files)."""
    try:
        res = subprocess.run(
            [C.FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=120,
        )
        value = float(res.stdout.strip())
        if value > 0:
            return value
    except Exception:                                # noqa: BLE001
        pass
    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:                                # noqa: BLE001
        return 0.0


def enhance_audio(audio_file: str) -> str:
    """Cleans the audio with ffmpeg. Returns the original if that fails.

    Degradation is silent on purpose (cleanup is an optional step), but the
    reason is printed to stderr so a missing ffmpeg is visible instead of
    surfacing as an unclear crash inside whisper.
    """
    # Written to TMP_DIR, not next to the original: if the process is killed
    # in the middle of whisper, a large _enhanced.wav must not be left in
    # recordings/ looking like a recording.
    stem = os.path.splitext(os.path.basename(audio_file))[0]
    enhanced = C.tmp_path(f"{stem}_enhanced.wav")
    try:
        subprocess.run(
            [C.FFMPEG, "-i", audio_file, "-af", C.AUDIO_FILTER,
             "-ar", str(C.SAMPLE_RATE), "-ac", str(C.CHANNELS),
             enhanced, "-y", "-loglevel", "quiet"],
            check=True, timeout=3600,
        )
    except Exception as exc:                         # noqa: BLE001
        print(f"[enhance_audio] пропускаю чищення: {exc}", file=sys.stderr)
        return audio_file
    if os.path.exists(enhanced) and os.path.getsize(enhanced) > 1024:
        return enhanced
    return audio_file


def extract_chunk(audio_file: str, start_sec: float, end_sec: float) -> str:
    """Cuts [start, end) into a separate 16 kHz mono WAV (in TMP_DIR)."""
    stem = os.path.splitext(os.path.basename(audio_file))[0]
    chunk_file = C.tmp_path(f"{stem}_chunk_{int(start_sec)}.wav")
    subprocess.run(
        [C.FFMPEG, "-i", audio_file,
         "-ss", str(start_sec), "-to", str(end_sec),
         "-ar", str(C.SAMPLE_RATE), "-ac", str(C.CHANNELS),
         chunk_file, "-y", "-loglevel", "quiet"],
        check=True, timeout=3600,
    )
    return chunk_file


def load_audio_range(path: str, start: float, length: float):
    """[start, start+length) as float32 numpy at 16 kHz mono.

    Same as whisper.load_audio(), but for a range: per-window language
    detection must not pull the whole file into memory (3 hours of float32
    ≈ 700 MB).
    """
    import numpy as np
    res = subprocess.run(
        [C.FFMPEG, "-nostdin", "-ss", str(start), "-t", str(length),
         "-i", path, "-f", "s16le", "-acodec", "pcm_s16le",
         "-ac", str(C.CHANNELS), "-ar", str(C.SAMPLE_RATE),
         "-loglevel", "quiet", "-"],
        capture_output=True, check=True, timeout=600,
    )
    raw = np.frombuffer(res.stdout, np.int16)
    return raw.astype(np.float32) / 32768.0


# ──────────────────── Per-window language detection ───────────────────


def _detect_window(model, audio) -> tuple:
    """({lang: p} over C.SUPPORTED_LANGS, rms) for up to 30 s of audio.

    Probabilities are RENORMALISED over the supported languages: the detector
    knows 99 languages and, on Ukrainian, consistently gives part of the mass
    to close ones (bg/sr/be/mk). Without renormalising, that mass eats the
    confidence and almost every window becomes "uncertain". Silence →
    ({}, rms).
    """
    import numpy as np

    if audio.size == 0:
        return {}, 0.0
    rms = float(np.sqrt(np.mean(np.square(audio))))
    if rms < C.LANG_MIN_RMS:
        return {}, rms          # the relative threshold lives in _mark_silence()

    # n_mels depends on the model: small/medium use 80, large-v3(-turbo) 128.
    # Hardcoding 80 would raise a shape RuntimeError after changing
    # EQ_WHISPER_MODEL.
    n_mels = getattr(getattr(model, "dims", None), "n_mels", 80)
    if C.ENGINE == "mlx":
        import mlx.core as mx
        from mlx_whisper import audio as mlx_audio
        from mlx_whisper.decoding import detect_language
        mel = mlx_audio.log_mel_spectrogram(
            mlx_audio.pad_or_trim(mx.array(audio)), n_mels)
        _, found = detect_language(model, mel)
        probs = found[0] if isinstance(found, list) else found
    else:
        import whisper
        mel = whisper.log_mel_spectrogram(
            whisper.pad_or_trim(audio), n_mels).to(model.device)
        _, probs = model.detect_language(mel)

    supported = {lang: float(probs.get(lang, 0.0))
                 for lang in C.SUPPORTED_LANGS}
    mass = sum(supported.values())
    if mass <= 0:
        return {}, rms
    return apply_uk_bias({lang: value / mass
                          for lang, value in supported.items()}), rms


def apply_uk_bias(probs: dict) -> dict:
    """Prior weight for Ukrainian against Russian (see C.LANG_UK_BIAS).

    A correction for a known detector skew, not a tweak of the result: on
    verified Ukrainian audio it returns ru 0.89 / uk 0.05. It touches ONLY
    the uk/ru pair; en is detected reliably and stays as is.
    """
    bias = C.LANG_UK_BIAS
    if bias == 1.0 or not probs.get("uk"):
        return _prefer_uk_on_tie(probs)
    weighted = dict(probs)
    weighted["uk"] = probs["uk"] * bias
    mass = sum(weighted.values())
    return _prefer_uk_on_tie(
        {lang: value / mass for lang, value in weighted.items()})


def _prefer_uk_on_tie(probs: dict) -> dict:
    """Explicit priority for Ukrainian on a near-tie with ru (see C.LANG_UK_MARGIN).

    LANG_UK_BIAS alone is not enough: it scales the prior across the whole
    range, so when the detector favours Russian by a small margin (0.52/0.40
    even AFTER the bias), argmax stays ru although the difference is within
    noise. This rule works right at the boundary: if ru wins by less than
    margin, the pair is swapped so Ukrainian becomes the argmax.

    The VALUES in the vector are swapped, not just the label, because the
    language decision is made in two places (the window argmax in
    detect_language_windows and the vector sum in _smoothed_labels); the swap
    keeps them consistent.
    """
    margin = C.LANG_UK_MARGIN
    if margin <= 0:
        return probs
    uk, ru = probs.get("uk", 0.0), probs.get("ru", 0.0)
    if ru <= uk or ru - uk >= margin:
        return probs
    swapped = dict(probs)
    swapped["uk"], swapped["ru"] = ru, uk
    return swapped


def detect_language_windows(audio_file: str, duration: float = None,
                            model=None, on_frac=None) -> list:
    """Language of every 30-second window of the file.

    30 s is not arbitrary: it is exactly how much audio the whisper encoder
    sees in one pass, so it is the finest granularity at which detection is
    defined at all.

    Returns a list of {start, end, lang, prob, probs, rms, silent}: lang is
    the argmax over the supported languages within the window, probs is the
    whole vector (smoothed later by group_language_runs).
    """
    model = model or get_model()
    duration = duration or get_duration(audio_file)
    window = C.LANG_WINDOW_SEC

    starts = []
    position = 0.0
    while position < duration - 1.0:          # nothing to detect in a tail under 1 s
        starts.append(position)
        position += window

    out = []
    for index, start in enumerate(starts):
        try:
            audio = load_audio_range(audio_file, start, window)
            probs, rms = _detect_window(model, audio)
        except Exception as exc:              # noqa: BLE001
            # One failed window must not fail the whole transcription: it just
            # becomes "uncertain" and is attached to a neighbouring run.
            print(f"[detect_language_windows] {C.tc(start)}: {exc}",
                  file=sys.stderr)
            probs, rms = {}, 0.0
        top = max(probs, key=probs.get) if probs else None
        out.append({
            "start": start,
            "end": min(start + window, duration),
            "lang": top,
            "prob": probs.get(top, 0.0) if top else 0.0,
            "probs": probs,
            "rms": rms,
            "silent": not probs,
        })
        if on_frac:
            on_frac((index + 1) / len(starts))
    return _mark_silence(out)


def _mark_silence(windows: list) -> list:
    """Mutes windows quieter than C.LANG_SILENCE_RATIO of the file's median.

    The threshold is relative on purpose: an absolute one is not enough
    because recording levels differ (microphone vs imported system audio).
    On a near-silent window the detector answers `en` with p=0.99, which
    would otherwise assign English to the whole file.
    """
    levels = sorted(win["rms"] for win in windows if win["rms"] > 0)
    if not levels:
        return windows
    middle = len(levels) // 2
    median = (levels[middle] if len(levels) % 2
              else (levels[middle - 1] + levels[middle]) / 2.0)
    floor = max(C.LANG_MIN_RMS, C.LANG_SILENCE_RATIO * median)
    for win in windows:
        if win["rms"] < floor:
            win.update(lang=None, prob=0.0, probs={}, silent=True)
    return windows


def _smoothed_labels(windows: list) -> list:
    """Language of each window after smoothing over neighbours (or None).

    The vote is the sum of probability vectors within ±R windows, not argmaxes:
    on the uk/ru boundary single windows give nearly equal 0.45/0.55 and,
    unsmoothed, flicker and chop the file into dozens of false runs.
    """
    radius = C.LANG_SMOOTH_RADIUS
    labels = []
    for index, win in enumerate(windows):
        if win["silent"]:
            labels.append(None)
            continue
        votes = {}
        for shift in range(-radius, radius + 1):
            neighbour = index + shift
            if not 0 <= neighbour < len(windows):
                continue
            weight = 2.0 if shift == 0 else 1.0
            for lang, value in (windows[neighbour]["probs"] or {}).items():
                votes[lang] = votes.get(lang, 0.0) + weight * value
        total = sum(votes.values())
        if not total:
            labels.append(None)
            continue
        top = max(votes, key=votes.get)
        labels.append(top if votes[top] / total >= C.LANG_MIN_PROB else None)
    return labels


def _global_dominant(windows: list):
    """Language with the largest probability sum over the whole file (or None)."""
    totals = {}
    for win in windows:
        for lang, value in (win["probs"] or {}).items():
            totals[lang] = totals.get(lang, 0.0) + value
    return max(totals, key=totals.get) if totals else None


def group_language_runs(windows: list, duration: float = 0.0) -> list:
    """Windows → language runs [{start, end, lang}].

    Three cleanup steps, each against a specific detector artefact:
      1) silent/uncertain windows inherit the previous language (on noise the
         detector answers anything, and each such window would cut the file);
      2) adjacent windows with the same language are merged;
      3) a run shorter than C.LANG_RUN_MIN_SEC is absorbed into a neighbour,
         otherwise a single English phrase in the middle of Ukrainian would
         add two extra cuts (and a cut means a sentence broken at the edge).
    """
    labels = _smoothed_labels(windows)

    # Uncertain windows take the previous known language. Leading ones (the
    # file starts with silence or ambiguity) take the language with the
    # largest probability sum over the whole file, NOT the first known one
    # further on: pulling a label backwards lets one quiet window in the tail
    # assign `en` to the whole file. A disputed 30 s remainder at the start is
    # absorbed into the neighbouring run anyway (_absorb_short_runs), so the
    # global guess carries no risk.
    filled, current = [], None
    for label in labels:
        current = label or current
        filled.append(current)
    fallback = _global_dominant(windows)
    labels = [label or fallback for label in filled]

    runs = []
    for win, lang in zip(windows, labels):
        if runs and runs[-1]["lang"] == lang:
            runs[-1]["end"] = win["end"]
        else:
            runs.append({"start": win["start"], "end": win["end"],
                         "lang": lang})
    if runs and duration:
        runs[-1]["end"] = max(runs[-1]["end"], duration)

    return _absorb_short_runs(runs)


def _absorb_short_runs(runs: list) -> list:
    """Merges runs shorter than C.LANG_RUN_MIN_SEC into the longer neighbour."""
    while len(runs) > 1:
        index = min(range(len(runs)),
                    key=lambda i: runs[i]["end"] - runs[i]["start"])
        if runs[index]["end"] - runs[index]["start"] >= C.LANG_RUN_MIN_SEC:
            break
        left = runs[index - 1] if index > 0 else None
        right = runs[index + 1] if index + 1 < len(runs) else None
        winner = max([r for r in (left, right) if r],
                     key=lambda r: r["end"] - r["start"])
        winner["start"] = min(winner["start"], runs[index]["start"])
        winner["end"] = max(winner["end"], runs[index]["end"])
        runs.pop(index)
        # merging may have made two equal neighbours; join them
        merged = [runs[0]]
        for run in runs[1:]:
            if run["lang"] == merged[-1]["lang"]:
                merged[-1]["end"] = run["end"]
            else:
                merged.append(run)
        runs = merged
    return runs


def language_mix(runs: list) -> list:
    """[(lang, share), …] over the language runs, largest first.

    Computed over RUNS, not raw windows: otherwise the MD header could show
    "ru 52 %, en 48 %" for a file whose segments are all tagged `[en]`. Raw
    argmax and smoothed runs are different decisions, and the reader should
    see the one that was actually used for transcription.
    """
    totals = {}
    for run in runs:
        if not run["lang"]:
            continue
        totals[run["lang"]] = (totals.get(run["lang"], 0.0)
                               + (run["end"] - run["start"]))
    total = sum(totals.values())
    if not total:
        return []
    return sorted(((lang, span / total) for lang, span in totals.items()),
                  key=lambda pair: -pair[1])


def language_hints(windows: list, runs: list) -> list:
    """Windows whose language confidently differs from their run's language.

    These are short insertions (< C.LANG_RUN_MIN_SEC) that are NOT cut out
    separately, but are flagged in the MD to show where the text may be off.
    """
    hints = []
    for win in windows:
        if win["silent"] or not win["lang"]:
            continue
        run = next((r for r in runs
                    if r["start"] <= win["start"] < r["end"]), None)
        host = run["lang"] if run else None
        if not host or win["lang"] == host:
            continue
        if win["prob"] < C.LANG_HINT_PROB:
            continue
        if hints and hints[-1]["lang"] == win["lang"] \
                and win["start"] - hints[-1]["end"] <= C.LANG_WINDOW_SEC:
            hints[-1]["end"] = win["end"]
            hints[-1]["prob"] = max(hints[-1]["prob"], win["prob"])
            continue
        hints.append({"start": win["start"], "end": win["end"],
                      "lang": win["lang"], "prob": win["prob"],
                      "host": host})
    return hints


def detect_language_file(audio_file: str, model=None, probe_sec: float = 90.0):
    """Language of the first voiced window (looks no deeper than probe_sec).

    Fallback for transcribe_chunk_with_lang() when no language was passed for
    the piece: scanning the whole piece here makes no sense, since it was
    either scanned outside already or this is "like whisper, but per piece".
    """
    model = model or get_model()
    limit = min(probe_sec, get_duration(audio_file) or probe_sec)
    for win in detect_language_windows(audio_file, duration=limit,
                                       model=model):
        if not win["silent"] and win["prob"] >= C.LANG_MIN_PROB:
            return win["lang"]
    return None


# ─────────────────────────── Transcription ────────────────────────────


def transcribe_chunk_with_lang(model, chunk_file: str, chunk_start: float = 0.0,
                               lang: str = None, on_frac=None,
                               probe_lang: bool = True) -> tuple:
    """Transcribes a piece in a known (or detected) language.

    lang=None → detect from the piece itself, not from the start of the file.
    probe_lang=False → with lang=None, do not detect here but leave the
        decision to whisper (the pipeline does this: it has either already
        scanned the file or scanning is disabled via EQ_PER_CHUNK_LANG=0).
    Returns (segments, lang); timecodes are already shifted by chunk_start and
    every segment carries "language".
    """
    if lang is None and probe_lang:
        lang = detect_language_file(chunk_file, model=model)

    if C.ENGINE == "mlx":
        raw_segments, detected = _mlx_transcribe_chunk(chunk_file, lang, on_frac)
    else:
        with _whisper_progress(on_frac):
            result = model.transcribe(chunk_file, **_decode_options(lang))
        detected = lang or result.get("language")
        raw_segments = result.get("segments") or []

    segments = []
    for seg in raw_segments:
        segments.append({
            "start": seg.get("start", 0.0) + chunk_start,
            "end": seg.get("end", 0.0) + chunk_start,
            "text": seg.get("text", ""),
            "language": detected,
        })
    return segments, detected


def _plan_pieces(runs: list, duration: float) -> list:
    """Language runs → pieces for the decoder.

    Long runs are additionally split by C.CHUNK_SIZE_SEC: otherwise a
    50-minute single-language file would go through one whisper call, with no
    progress and peak memory for the whole file.
    """
    if not runs:
        return [{"start": 0.0, "end": duration, "lang": None}]

    limit = C.CHUNK_SIZE_SEC
    pieces = []
    for run in runs:
        span = run["end"] - run["start"]
        # One run covering a whole short file is decoded as the whole file:
        # no ffmpeg slicing and no context breaks (the most common case).
        if len(runs) == 1 and duration <= C.CHUNK_THRESHOLD_SEC:
            pieces.append({"start": 0.0, "end": duration, "lang": run["lang"]})
            continue
        parts = max(1, int(-(-span // limit)))       # ceil
        step = span / parts
        for index in range(parts):
            start = run["start"] + index * step
            pieces.append({
                "start": start,
                "end": run["end"] if index == parts - 1 else start + step,
                "lang": run["lang"],
            })
    return pieces


def checkpoint_path(audio_file: str, duration: float) -> str:
    """Checkpoint file for this audio (depends on file, duration and model)."""
    import hashlib
    # The language mode is part of the key: otherwise toggling FORCE_UKRAINIAN
    # would pick up pieces already decoded in another language.
    mode = "uk-forced" if C.FORCE_UKRAINIAN else "auto"
    key = (f"{os.path.abspath(audio_file)}|{int(duration)}"
           f"|{C.MODEL_NAME}|{mode}")
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    stem = os.path.splitext(os.path.basename(audio_file))[0][:40]
    os.makedirs(C.CHECKPOINT_DIR, exist_ok=True)
    return os.path.join(C.CHECKPOINT_DIR, f"{stem}-{digest}.json")


def _load_checkpoint(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_checkpoint(path: str, data: dict) -> None:
    """Atomic write: otherwise a kill in the middle of json.dump leaves a corrupt checkpoint."""
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as exc:
        print(f"[checkpoint] не зберігся: {exc}", file=sys.stderr)


def clear_checkpoint(audio_file: str, duration: float) -> None:
    """Removes the checkpoint; call ONLY after the MD has been saved successfully."""
    try:
        os.remove(checkpoint_path(audio_file, duration))
    except OSError:
        pass


def _same_piece(saved: dict, piece: dict) -> bool:
    return (saved.get("lang") == piece["lang"]
            and abs(saved.get("start", -1) - piece["start"]) < 0.5
            and abs(saved.get("end", -1) - piece["end"]) < 0.5)


def transcribe_with_progress(audio_file: str, on_progress=None,
                             on_status=None, resume: bool = True,
                             checkpoint_key: str = None) -> dict:
    """Transcribes a file with per-segment language detection.

    Three stages:
      1) detection: the language of every 30 s window (about 5 % of the time);
      2) grouping windows into language runs (see group_language_runs);
      3) decoding every run SEPARATELY in its own language.

    Stock whisper detects the language once on the first 30 seconds and
    decodes the whole file with it, so a uk+ru+en mix would go through as a
    single `ru` and mangle Ukrainian words; this pipeline avoids that.

    resume=True — after every finished piece the state is written to a
    checkpoint, and a repeated run does not redo finished work.

    checkpoint_key — what the checkpoint is bound to. Defaults to audio_file,
    but the caller should pass the ORIGINAL recording: the input here is the
    derived _enhanced.wav, whose path can change, and the checkpoint would no
    longer be found.

    on_progress(percent: float) — real progress inside whisper.
    on_status(text: str) — text status for the UI.
    """
    def status(text):
        if on_status:
            on_status(text)

    def progress(pct):
        if on_progress:
            on_progress(max(0.0, min(100.0, pct)))

    # whisper.audio.load_audio() calls ffmpeg by its short name, so PATH must
    # contain /opt/homebrew/bin, otherwise FileNotFoundError is raised in the
    # decoder.
    C.ensure_tool_path()

    status(S.PROGRESS_MODEL_LOADING.format(model=C.MODEL_NAME.upper()))
    model = get_model()
    duration = get_duration(audio_file)
    progress(0.0)

    ckpt_file = checkpoint_path(checkpoint_key or audio_file, duration)
    ckpt = _load_checkpoint(ckpt_file) if resume else {}
    if ckpt.get("pieces"):
        status(S.PROGRESS_CHECKPOINT_FOUND.format(n=len(ckpt["pieces"])))

    windows, runs, hints, mix = [], [], [], []
    if C.FORCE_UKRAINIAN:
        # Forced Ukrainian: no detection needed, the whole file is a single
        # uk run. This branch comes BEFORE the checkpoint branch on purpose:
        # otherwise a cache from an auto-detect run would return ru runs.
        # (Already decoded pieces are not mixed in either: checkpoint_path
        # keeps the mode in its key, so the checkpoint file differs here.)
        runs = [{"start": 0.0, "end": duration, "lang": "uk"}]
        scan_share = 0.0
    elif ckpt.get("runs"):
        # The language scan is not repeated: it is deterministic for the same
        # file and model, and on an hour-long file it takes minutes.
        windows = ckpt.get("windows") or []
        runs, hints = ckpt["runs"], ckpt.get("hints") or []
        mix = [tuple(pair) for pair in ckpt.get("mix") or []]
        scan_share = 0.0
    elif C.LANGUAGE or not C.PER_CHUNK_LANG:
        # The language is set explicitly (EQ_WHISPER_LANG) or detection is
        # disabled: respect that and skip the scan.
        runs = [{"start": 0.0, "end": duration, "lang": C.LANGUAGE}]
        scan_share = 0.0
    else:
        status(S.PROGRESS_DETECTING_LANGUAGE)
        scan_share = 0.06
        windows = detect_language_windows(
            audio_file, duration, model,
            on_frac=lambda f: progress(f * scan_share * 100.0))
        runs = group_language_runs(windows, duration)
        hints = language_hints(windows, runs)
        mix = language_mix(runs)
        found = " → ".join(f"{r['lang'] or '?'} {C.tc(r['start'])}"
                           for r in runs[:6])
        status(S.PROGRESS_LANGUAGES.format(found=found))
        if resume:
            _save_checkpoint(ckpt_file, {
                "duration": duration, "model": C.MODEL_NAME,
                "windows": windows, "runs": runs, "hints": hints,
                "mix": [list(pair) for pair in mix], "pieces": [],
            })

    pieces = _plan_pieces(runs, duration)
    spans = [max(0.1, p["end"] - p["start"]) for p in pieces]
    total_span = sum(spans) or 1.0

    saved_pieces = list(ckpt.get("pieces") or [])
    all_segments, made, done = [], [], 0.0
    try:
        for index, (piece, span) in enumerate(zip(pieces, spans)):
            start, end, lang = piece["start"], piece["end"], piece["lang"]
            whole = start <= 0.01 and end >= duration - 0.05
            label = f"{C.tc(start)}–{C.tc(end)}"

            # A piece that is already done is taken from the checkpoint, not decoded again.
            reused = (index < len(saved_pieces)
                      and _same_piece(saved_pieces[index], piece))
            if reused:
                all_segments.extend(saved_pieces[index].get("segments") or [])
                done += span
                status(S.PROGRESS_FROM_CHECKPOINT.format(label=label))
                progress((scan_share + (1.0 - scan_share)
                          * (done / total_span)) * 100.0)
                continue

            status(S.PROGRESS_DECODING.format(
                lang=lang or "auto", label=label, duration=C.tc(duration)))

            source = audio_file if whole else extract_chunk(
                audio_file, start, end)
            if not whole:
                made.append(source)

            base = scan_share + (1.0 - scan_share) * (done / total_span)
            share = (1.0 - scan_share) * (span / total_span)
            try:
                segments, _ = transcribe_chunk_with_lang(
                    model, source, 0.0 if whole else start, lang,
                    on_frac=lambda f, b=base, s=share:
                    progress((b + s * f) * 100.0),
                    probe_lang=False)      # the scan is already done or disabled
            finally:
                if not whole:
                    try:
                        os.remove(source)    # do not keep extras on disk
                        made.remove(source)
                    except (OSError, ValueError):
                        pass

            all_segments.extend(segments)
            done += span

            # Checkpoint IMMEDIATELY after each piece: a kill then loses at
            # most one piece (≤ 10 min), not the whole file.
            if resume:
                saved_pieces = saved_pieces[:index] + [{
                    "start": start, "end": end, "lang": lang,
                    "segments": segments,
                }]
                _save_checkpoint(ckpt_file, {
                    "duration": duration, "model": C.MODEL_NAME,
                    "windows": windows, "runs": runs, "hints": hints,
                    "mix": [list(pair) for pair in mix],
                    "pieces": saved_pieces,
                })

            progress((scan_share + (1.0 - scan_share)
                      * (done / total_span)) * 100.0)
    finally:
        for leftover in made:
            try:
                os.remove(leftover)
            except OSError:
                pass

    progress(100.0)
    return {
        "text": " ".join((seg["text"] or "").strip()
                         for seg in all_segments).strip(),
        "segments": all_segments,
        "language": _dominant_language(all_segments, mix, runs),
        "lang_mix": mix,
        "lang_runs": runs,
        "lang_hints": hints,
        "lang_windows": windows,
        # The checkpoint is NOT removed here: if the process dies between this
        # return and save_markdown(), the work must stay resumable. Whoever
        # has already written the MD removes it (clear_checkpoint).
        "checkpoint": ckpt_file if resume else "",
    }


def _dominant_language(segments: list, mix: list, runs: list):
    """The language spoken for the longest time (for the MD header)."""
    totals = {}
    for seg in segments:
        lang = seg.get("language")
        if lang:
            totals[lang] = totals.get(lang, 0.0) + max(
                0.0, seg.get("end", 0.0) - seg.get("start", 0.0))
    if totals:
        return max(totals, key=totals.get)
    if mix:
        return mix[0][0]
    return runs[0]["lang"] if runs else None


# ─────────────────────────────── Markdown ─────────────────────────────


def smart_filename(started: datetime.datetime) -> str:
    """File name: HH-MM_DD-MM-YY_DAILY (before 12:00) or _MID (from 12:00).

    Derived from the recording time only; the transcript text is NOT read.
    Names guessed from the text are unreliable (people mention absent third
    parties and rarely name the person they are talking to), and a misleading
    name is worse than a neutral one.

    Pure name generation: files already on disk are never renamed. A clash
    within the same minute gets _2, _3 (unique_path).
    """
    suffix = "DAILY" if started.hour < 12 else "MID"
    return f"{started.strftime('%H-%M_%d-%m-%y')}_{suffix}"


def _mix_line(mix: list) -> str:
    """'uk 78 %, ru 18 %, en 4 %', or empty if there is only one language."""
    if len(mix) < 2:
        return ""
    parts = [f"{lang} {round(share * 100)} %" for lang, share in mix
             if share >= 0.01]
    return ", ".join(parts)


def build_md(result: dict, started: datetime.datetime, duration: float,
             source: str, title: str) -> str:
    """Markdown with timecodes and per-segment language tags.

    The `[ru]` tag is placed ONLY where the language changes relative to the
    previous segment; otherwise it would appear on every line and become
    noise.
    """
    segments = result.get("segments") or []
    language = result.get("language") or (C.LANGUAGE or "?")
    mix = result.get("lang_mix") or []
    hints = list(result.get("lang_hints") or [])
    full = (result.get("text") or "").strip()

    mix_line = _mix_line(mix)
    lang_line = f"{language} (мікс: {mix_line})" if mix_line else str(language)

    # The actual decoder parameters, not the desired ones: MLX has no beam
    # search (_mlx_transcribe_chunk drops beam_size), so it is greedy at T=0
    # with best_of 5 only on temperature fallbacks.
    if C.ENGINE == "mlx":
        engine = "MLX / Metal GPU, локально, greedy, фолбек best_of 5"
    else:
        engine = "CPU, локально, beam search 5"

    lines = [
        f"# {title}",
        "",
        f"- **Дата:** {started.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Тривалість:** {C.tc(duration)}",
        f"- **Мова:** {lang_line}",
        f"- **Модель:** whisper `{C.MODEL_NAME}` "
        f"({engine}, мова детектується по 30-c вікнах)",
        f"- **Джерело:** `{source}`",
        "",
        "## Транскрипт",
        "",
    ]

    if segments:
        previous = None
        for seg in segments:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            start = seg.get("start", 0)

            # Short insertions in another language are not cut out separately
            # (see C.LANG_RUN_MIN_SEC), but the MD flags where the text may
            # be off.
            while hints and hints[0]["start"] <= start:
                hint = hints.pop(0)
                lines += [
                    f"> ⚠️ ~**[{C.tc(hint['start'])}]** схоже на "
                    f"`{hint['lang']}` (p={hint['prob']:.2f}), "
                    f"розпізнано як `{hint['host']}`",
                    "",
                ]

            lang = seg.get("language")
            tag = f"`[{lang}]` " if lang and lang != previous else ""
            previous = lang or previous
            lines.append(f"{tag}**[{C.tc(start)}]** {text}")
            lines.append("")
    else:
        lines += ["_Мова не розпізнана (тиша або надто короткий запис)._", ""]

    lines += ["## Повний текст", "", full if full else "_(порожньо)_", ""]
    return "\n".join(lines)


def save_markdown(md: str, stem: str) -> list:
    """Writes the MD to output/ and (if configured) to the vault. Returns the list of paths."""
    saved = []
    for directory in C.save_dirs():
        os.makedirs(directory, exist_ok=True)
        path = C.unique_path(directory, stem, ".md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(md)
        saved.append(path)
    return saved
