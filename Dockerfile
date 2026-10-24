# syntax=docker/dockerfile:1.7
# Chessify: анализ, рендер и веб-интерфейс в одном образе.
# Основа — CUDA 12.8 + cuDNN 9: нужна для RTX 50-й серии (Blackwell) и для faster-whisper/pyannote.
# Без видеокарты образ тоже работает — модели уходят на CPU (медленнее).

FROM node:22.23.4-bookworm-slim AS node

FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    PYTHONUTF8=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    XDG_CACHE_HOME=/cache \
    HF_HOME=/cache/huggingface \
    CLAUDE_CONFIG_DIR=/root/.claude \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility,video \
    CHESSIFY_RENDER_HWACCEL=off

# ffmpeg + библиотеки для headless Chrome, которым рендерит Remotion (список из документации Remotion).
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg ca-certificates curl \
      libnss3 libdbus-1-3 libatk1.0-0 libgbm-dev libasound2t64 libxrandr2 libxkbcommon-dev libxfixes3 \
      libxcomposite1 libxdamage1 libatk-bridge2.0-0 libpango-1.0-0 libcairo2 libcups2 \
      fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Node.js 22 и npm — из официального образа Node.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# uv — менеджер Python; сам скачает Python 3.12.
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /usr/local/bin/

WORKDIR /app

# Зависимости отдельными слоями, чтобы правка кода не пересобирала PyTorch и node_modules.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-install-project --extra asr --extra diar --extra web

COPY render/package.json render/package-lock.json render/
RUN cd render && npm ci && npx remotion browser ensure

# Claude Code CLI: профиль quality/dev работает через подписку Claude (вход: docker compose exec app claude).
ARG INSTALL_CLAUDE=1
RUN if [ "$INSTALL_CLAUDE" = "1" ]; then npm install -g @anthropic-ai/claude-code; fi

COPY . .
RUN uv sync --frozen --extra asr --extra diar --extra web --extra anthropic \
 && uv run --no-sync chessify export-schema \
 && cd render && npm run types

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD curl -fsS http://localhost:8000/api/config >/dev/null || exit 1
CMD ["uv", "run", "--no-sync", "chessify", "web", "--host", "0.0.0.0", "--port", "8000"]
