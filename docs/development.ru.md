# Chessify — для разработчиков

Техническая сторона: как устроен конвейер, профили моделей, командная строка и запуск без Docker.
Инструкция для пользователя — в [README](../README.ru.md). [English version](development.md).

## Как это устроено

```
видео → нормализация (ffmpeg) → распознавание речи (faster-whisper large-v3, GPU)
      → разметка спикеров (pyannote, GPU) → вычитка расшифровки (LLM: имена, ослышки)
      → разбор партии (LLM, 3 прохода: ходы → оценки → редактура)
      → шкала, точность, темп карточек (код) → аватары (OpenCV) → рендер (Remotion) → ролик 1080×1920
```

- `src/chessify/` — конвейер, CLI (`chessify`) и веб-сервер (`chessify web`, FastAPI + статическая страница).
- `render/` — шаблон ролика на Remotion.
- `config/providers.yaml` — профили: какие модели выполняют какие роли. Провайдеры сменяемые.
- `prompts/` — промпты на русском, `prompts/en/` — на английском и переведённые примеры ходов.
- Шкала, точность, счётчики категорий и темп карточек считаются кодом из ходов, а не моделью.

## Языки

- **Язык интерфейса** (переключатель RU / EN в шапке) хранится в браузере и уходит на сервер в заголовке
  `X-Lang`: на нём ошибки API, тексты настроек и журнал новых задач (`src/chessify/i18n.py`,
  `src/chessify/web/static/i18n.js`).
- **Язык ролика** выбирается у каждой задачи: распознавание речи, промпты и надписи в ролике
  (`Meta.language` в сцене, подписи — в `render/src/theme.ts`).

## Профили моделей

Профиль — модель, которая разбирает партию. Выбирается в форме нового ролика, основная — в «Настройках».
После правки `config/providers.yaml` достаточно `docker compose restart`.

| Профиль | Модель | Что нужно |
|---|---|---|
| `custom` | свой OpenAI-совместимый сервер (vLLM, SGLang, Ollama, LM Studio…) | адрес, ключ и модель |
| `deepseek` | разметка — DeepSeek Flash, оценки и редактура — DeepSeek V4 Pro | ключ DeepSeek |
| `gemini` | Google Gemini 3.8 Flash, бесплатный тариф | ключ Gemini |
| `openai` | OpenAI, по умолчанию `gpt-6.1-sol` | ключ OpenAI |
| `openrouter` | любая модель OpenRouter, по умолчанию `deepseek/deepseek-v4-pro` | ключ OpenRouter |
| `anthropic` | Claude по API, по умолчанию `claude-opus-5-5` | ключ Anthropic |
| `claude` | Claude по подписке через Claude Code | вход: `docker compose exec app claude` → `/login` |

Ключи хранятся в `data/settings/settings.env` (пишет веб-интерфейс) или в `.env` (шаблон — `.env.example`);
заданное в интерфейсе важнее. Проверка подключения из терминала:

```powershell
docker compose exec app uv run chessify llm-check --provider <профиль>
```

## Docker

- `compose.yaml` — с видеокартой NVIDIA, `compose.cpu.yaml` — без неё:
  `docker compose -f compose.yaml -f compose.cpu.yaml up -d --build`.
- Порт на хосте — `CHESSIFY_PORT` в `.env` (по умолчанию 37415), внутри контейнера — 8000.
- Код (`src`, `prompts`, `render/src`, `render/public/sfx`, `modules`) подключён с диска: после правки кода хватает
  `docker compose restart`. Пересборка (`--build`) нужна при изменении зависимостей или `Dockerfile`.
- Данные — в `data/`: `out` — ролики, `jobs` — задачи, `media` — клипы и аватары, `music` — музыка,
  `settings` — ключи из «Настроек» и аккаунты TikTok (`tiktok.json`). Модели распознавания кэшируются в томе `cache`.

```powershell
docker compose logs -f                                   # журнал сервера
docker compose exec app uv run chessify doctor           # проверка GPU, CUDA, ffmpeg, Remotion
```

## Публикация в TikTok

- `modules/tiktok-publisher/` — самостоятельный модуль без зависимостей (официальный Content Posting API, OAuth с PKCE,
  хранилище токенов нескольких аккаунтов). Рассчитан и на другие проекты: [README](../modules/tiktok-publisher/README.ru.md),
  [INTEGRATION.md](../modules/tiktok-publisher/INTEGRATION.md) — для агентов.
- В зависимостях `pyproject.toml` его нет (правка lock-файла пересобрала бы тяжёлый слой образа):
  `src/chessify/tiktok.py` импортирует его из папки. Тот же путь — в `pyrightconfig.json`.
- Хранилище — `settings/tiktok.json` (в Docker — `data/settings`), приложение TikTok сохраняется под именем `chessify`.
- API: `/api/tiktok` (приложение, аккаунты), `/api/tiktok/connect` → TikTok → `/api/tiktok/callback/`,
  `/api/tiktok/finish` (адрес, вставленный вручную, если интерфейс открыт с другой машины),
  `/api/jobs/<id>/tiktok` (публикация), `/api/jobs/<id>/tiktok/refresh` (статус и ссылка).
- `JobParams.tiktok` — опубликовать после первого рендера; итог — в `JobState.tiktok`. Публикация идёт в своём
  потоке и задачу не роняет.
- Командная строка: `chessify run … --tiktok main [--tiktok-caption "…"] [--tiktok-inbox]`;
  `chessify tiktok <команда>` — командная строка модуля с хранилищем Chessify (`account list`, `info main`, `publish …`).

## Без Docker

Установка Python, Node и ffmpeg — `scripts/setup.ps1`, затем:

```
uv run chessify web                      # веб-интерфейс на http://127.0.0.1:37415
uv run chessify run сцена.mp4 --series "Во все тяжкие" --length shorts      # --language en — английский ролик
uv run chessify run серия.mkv --series "Во все тяжкие" --auto-scene --music theme.mp3
uv run chessify find-scenes серия.mkv --series "Во все тяжкие"     # только показать кандидатов
uv run chessify batch папка_с_видео/ --series "Во все тяжкие" --length shorts
```

## Тесты и проверки

```
uv run --group dev --extra web pytest      # тесты, без сети и ключей
uv run python scripts/stt_wer.py <words.json>…   # точность распознавания по эталону
```

После правки `src/chessify/schema.py`: `uv run chessify export-schema` и `npm run types` в `render/`.
