# Chessify — for developers

The technical side: how the pipeline works, model profiles, the command line and running without Docker.
The user guide is in the [README](../README.md). [Русская версия](development.ru.md).

## How it works

```
video → normalization (ffmpeg) → speech recognition (faster-whisper large-v3, GPU)
      → speaker diarization (pyannote, GPU) → transcript proofreading (LLM: names, mishearings)
      → game analysis (LLM, 3 passes: moves → ratings → editing)
      → eval bar, accuracy, card pacing (code) → avatars (OpenCV) → rendering (Remotion) → 1080×1920 video
```

- `src/chessify/` — the pipeline, the CLI (`chessify`) and the web server (`chessify web`, FastAPI + a static page).
- `render/` — the Remotion video template.
- `config/providers.yaml` — profiles: which models play which roles. Providers are swappable.
- `prompts/` — Russian prompts, `prompts/en/` — English prompts and translated few-shot examples.
- The eval bar, accuracy, category counts and card pacing are computed by code from the moves, not by the model.

## Languages

- **Interface language** (RU / EN switch in the header) is stored in the browser and sent to the server in the
  `X-Lang` header: API errors, settings texts and the log of new jobs follow it (`src/chessify/i18n.py`,
  `src/chessify/web/static/i18n.js`).
- **Video language** is chosen per job: speech recognition, the prompts and the on-screen text of the video
  (`Meta.language` in the scene, labels in `render/src/theme.ts`).

## Model profiles

A profile is the model that analyzes the game. It is chosen in the new video form; the main one is set in Settings.
After editing `config/providers.yaml`, `docker compose restart` is enough.

| Profile | Model | What's needed |
|---|---|---|
| `custom` | your own OpenAI-compatible server (vLLM, SGLang, Ollama, LM Studio…) | address, key and model |
| `deepseek` | moves — DeepSeek Flash, ratings and editing — DeepSeek V4 Pro | DeepSeek key |
| `gemini` | Google Gemini 3.8 Flash, free tier | Gemini key |
| `openai` | OpenAI, `gpt-6.1-sol` by default | OpenAI key |
| `openrouter` | any OpenRouter model, `deepseek/deepseek-v4-pro` by default | OpenRouter key |
| `anthropic` | Claude via the API, `claude-opus-5-5` by default | Anthropic key |
| `claude` | Claude via a subscription through Claude Code | sign in: `docker compose exec app claude` → `/login` |

Keys are stored in `data/settings/settings.env` (written by the web interface) or in `.env` (template: `.env.example`);
what is set in the interface wins. Checking a connection from a terminal:

```powershell
docker compose exec app uv run chessify llm-check --provider <profile>
```

## Docker

- `compose.yaml` — with an NVIDIA graphics card, `compose.cpu.yaml` — without one:
  `docker compose -f compose.yaml -f compose.cpu.yaml up -d --build`.
- The host port is `CHESSIFY_PORT` in `.env` (37415 by default); inside the container it is 8000.
- The code (`src`, `prompts`, `render/src`, `render/public/sfx`) is mounted from disk: after a code change,
  `docker compose restart` is enough. A rebuild (`--build`) is needed when dependencies or the `Dockerfile` change.
- Data lives in `data/`: `out` — videos, `jobs` — jobs, `media` — clips and avatars, `music` — music,
  `settings` — keys from Settings. Speech recognition models are cached in the `cache` volume.

```powershell
docker compose logs -f                                   # server log
docker compose exec app uv run chessify doctor           # check GPU, CUDA, ffmpeg, Remotion
```

## Without Docker

Install Python, Node and ffmpeg with `scripts/setup.ps1`, then:

```
uv run chessify web                      # web interface at http://127.0.0.1:37415
uv run chessify run scene.mp4 --series "Breaking Bad" --language en --length shorts
uv run chessify run episode.mkv --series "Breaking Bad" --language en --auto-scene --music theme.mp3
uv run chessify find-scenes episode.mkv --series "Breaking Bad" --language en   # only list candidates
uv run chessify batch videos/ --series "Breaking Bad" --language en --length shorts
```

## Tests and checks

```
uv run --group dev --extra web pytest            # tests, no network or keys
uv run python scripts/stt_wer.py <words.json>…   # speech recognition accuracy against the reference
```

After editing `src/chessify/schema.py`: `uv run chessify export-schema` and `npm run types` in `render/`.
