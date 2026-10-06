# models/

Whisper weights are **not** stored here. A model weighs hundreds of
megabytes to several gigabytes, and keeping it in git would make every
`git clone` download it again.

The model is downloaded once, on first launch, into the standard cache of
the respective ML library:

| Engine (`EQ_ENGINE`) | Library          | Download location        |
|---|---|---|
| `mlx` (default)      | `mlx_whisper`    | `~/.cache/huggingface/`  |
| `whisper`            | `openai-whisper` | `~/.cache/whisper/`      |

`app/config.py` selects the model (`MODEL_NAME`, default `large-v3-turbo`),
or set the environment variable:

```bash
EQ_WHISPER_MODEL=small ./start.sh   # lighter and faster, but loops more often
```

With the `mlx` engine the same model both decodes and detects the language
on 30-second windows.

Size on disk (`mlx`): `large-v3-turbo` ≈ 1.6 GB, `small` ≈ 0.46 GB. The
download happens at app startup (background preload), not in the middle of
the first transcription.

To remove the cache and re-download the model on the next launch, delete
the corresponding folder above; nothing in the repository is affected.
