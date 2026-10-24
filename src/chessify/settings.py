"""Ключи и параметры подключения, заданные в веб-интерфейсе.

Хранятся в settings/settings.env (в Docker — том data/settings) и перекрывают .env и окружение:
вписанное в интерфейсе — последнее явное решение пользователя. Конвейер по-прежнему читает os.environ,
поэтому настройки действуют сразу, без перезапуска.

Настройки разбиты на разделы: модели для разбора партии (раздел = профиль из config/providers.yaml)
и распознавание речи.
"""

import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values

from chessify.paths import ROOT

SETTINGS_PATH = ROOT / "settings" / "settings.env"
MAX_LEN = 4000
DEFAULT_PROFILE_KEY = "CHESSIFY_DEFAULT_PROFILE"
# Имена из прошлых версий: сохранённые под ними значения переносятся при чтении.
LEGACY = {"WORK_LLM_BASE_URL": "CUSTOM_LLM_BASE_URL", "WORK_LLM_API_KEY": "CUSTOM_LLM_API_KEY",
          "WORK_LLM_MODEL": "CUSTOM_LLM_MODEL"}


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: Literal["text", "url", "secret"] = "secret"
    hint: str = ""
    placeholder: str = ""


@dataclass(frozen=True)
class Section:
    id: str  # для моделей — имя профиля
    title: str
    kind: Literal["llm", "speech"]
    about: str
    link: str = ""
    check: str | None = None  # что проверять кнопкой: провайдер из providers.yaml или "hf"
    fields: tuple[Field, ...] = field(default_factory=tuple)


def _model(key: str, default: str) -> Field:
    return Field(key, "Модель", "text", f"Пусто — {default}.", placeholder=default)


SECTIONS = [
    Section("custom", "Свой сервер", "llm",
            "Любой OpenAI-совместимый сервер: vLLM, SGLang, Ollama, LM Studio или прокси. Подходит, если модель "
            "развёрнута у вас или вам выдали адрес и ключ.", check="custom", fields=(
                Field("CUSTOM_LLM_BASE_URL", "Адрес API", "url", "Обычно заканчивается на /v1.",
                      placeholder="http://localhost:8000/v1"),
                Field("CUSTOM_LLM_API_KEY", "Ключ", hint="Если сервер без ключа — впишите любое слово, например none."),
                Field("CUSTOM_LLM_MODEL", "Модель", "text",
                      "Не знаете — нажмите «Проверить»: появится список моделей на сервере.", placeholder="qwen"),
            )),
    Section("deepseek", "DeepSeek", "llm",
            "Платно, но дёшево: порядка 3–15 центов за ролик, ночью по UTC и в выходные вдвое дешевле. "
            "Разметка — DeepSeek Flash, оценки и комментарии — DeepSeek V4 Pro.",
            "https://platform.deepseek.com/api_keys", check="deepseek", fields=(Field("DEEPSEEK_API_KEY", "Ключ"),)),
    Section("gemini", "Google Gemini", "llm",
            "Бесплатный тариф AI Studio. На нём Google может использовать запросы для улучшения своих моделей.",
            "https://aistudio.google.com/apikey", check="gemini",
            fields=(Field("GEMINI_API_KEY", "Ключ"), _model("GEMINI_MODEL", "gemini-3.8-flash"))),
    Section("openai", "OpenAI", "llm", "Платный API OpenAI.",
            "https://platform.openai.com/api-keys", check="openai",
            fields=(Field("OPENAI_API_KEY", "Ключ"), _model("OPENAI_MODEL", "gpt-6.1-sol"))),
    Section("openrouter", "OpenRouter", "llm",
            "Один ключ — сотни моделей разных компаний. Модель — в формате компания/модель, цена зависит от неё.",
            "https://openrouter.ai/settings/keys", check="openrouter",
            fields=(Field("OPENROUTER_API_KEY", "Ключ"), _model("OPENROUTER_MODEL", "deepseek/deepseek-v4-pro"))),
    Section("anthropic", "Anthropic API", "llm", "Claude по платному API Anthropic.",
            "https://platform.claude.com/settings/keys", check="anthropic",
            fields=(Field("ANTHROPIC_API_KEY", "Ключ"), _model("ANTHROPIC_MODEL", "claude-opus-5-5"))),
    Section("claude", "Claude по подписке", "llm",
            "Через Claude Code, без API-ключа. Вход один раз из терминала: docker compose exec app claude, "
            "затем /login. Подписка подходит для личного использования.", check="claude_sub"),
    Section("hf", "Разметка спикеров", "speech",
            "Бесплатный токен Hugging Face (тип Read) и принятые условия модели "
            "pyannote/speaker-diarization-community-1. Без него ролики собираются, но стороны диалога "
            "модель определяет только по смыслу.",
            "https://huggingface.co/settings/tokens", check="hf", fields=(Field("HF_TOKEN", "Токен Hugging Face"),)),
]
FIELDS = [f for s in SECTIONS for f in s.fields]
KEYS = {f.key: f for f in FIELDS} | {DEFAULT_PROFILE_KEY: Field(DEFAULT_PROFILE_KEY, "Основная модель", "text")}
SECTION_OF = {f.key: s for s in SECTIONS for f in s.fields}

_shadowed: dict[str, str | None] = {}  # ключ → значение из окружения, которое перекрыли настройки


def read(path: Path | None = None) -> dict[str, str]:
    path = path or SETTINGS_PATH
    if not path.exists():
        return {}
    raw = dotenv_values(path, encoding="utf-8")
    values = {LEGACY.get(k, k): v for k, v in raw.items() if v}
    return {k: v for k, v in values.items() if k in KEYS}


def describe(keys: Iterable[str]) -> str:
    """Как недостающие ключи называются в «Настройках»: раздел → поле (переменная)."""
    return "; ".join(f"{SECTION_OF[k].title} → {KEYS[k].label} ({k})" if k in SECTION_OF else k for k in keys)


def apply(path: Path | None = None) -> None:
    """Перенести сохранённые настройки в os.environ; очищенные — вернуть к значению из .env/окружения."""
    for old, new in LEGACY.items():  # старые имена в .env/окружении
        if os.environ.get(old) and not os.environ.get(new):
            os.environ[new] = os.environ[old]
    saved = read(path)
    for key, value in saved.items():
        if key not in _shadowed:
            _shadowed[key] = os.environ.get(key)
        os.environ[key] = value
    for key in [k for k in _shadowed if k not in saved]:
        previous = _shadowed.pop(key)
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def validate(key: str, value: str) -> str:
    if key not in KEYS:
        raise ValueError(f"неизвестная настройка {key}")
    value = value.strip()
    if "\n" in value or "\r" in value or len(value) > MAX_LEN:
        raise ValueError(f"{KEYS[key].label}: одна строка до {MAX_LEN} символов")
    if KEYS[key].kind == "url" and value and not value.startswith(("http://", "https://")):
        raise ValueError(f"{KEYS[key].label}: адрес начинается с http:// или https://")
    return value


def save(values: dict[str, str], clear: Iterable[str] = (), path: Path | None = None) -> None:
    """Записать изменения: пустое значение не меняет сохранённое, clear — удаляет."""
    path = path or SETTINGS_PATH
    current = read(path)
    for key in clear:
        validate(key, "")
        current.pop(key, None)
    for key, value in values.items():
        if value := validate(key, value):
            current[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    body = "".join(f'{k}="{_quote(v)}"\n' for k, v in current.items())
    tmp.write_text("# Настройки из веб-интерфейса Chessify. Перекрывают .env.\n" + body, encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(path)
    apply(path)


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def mask(value: str) -> str:
    return "••••" + value[-4:] if len(value) >= 12 else "••••"


def status(path: Path | None = None) -> list[dict]:
    """Разделы с состоянием полей для интерфейса. Секреты целиком наружу не отдаются."""
    saved = read(path)
    out = []
    for sec in SECTIONS:
        fields = []
        for f in sec.fields:
            value = os.environ.get(f.key, "")
            source = "web" if f.key in saved else "env" if value else None
            shown = {"masked": mask(value)} if f.kind == "secret" and value else {"value": value}
            fields.append({**asdict(f), "source": source, **shown})
        out.append({**{k: v for k, v in asdict(sec).items() if k != "fields"}, "fields": fields})
    return out
