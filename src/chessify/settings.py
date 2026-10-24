"""Ключи и параметры подключения, заданные в веб-интерфейсе.

Хранятся в settings/settings.env (в Docker — том data/settings) и перекрывают .env и окружение:
вписанное в интерфейсе — последнее явное решение пользователя. Конвейер по-прежнему читает os.environ,
поэтому настройки действуют сразу, без перезапуска.

Настройки разбиты на разделы: модели для разбора партии (раздел = профиль из config/providers.yaml)
и распознавание речи.
"""

import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values

from chessify.i18n import pick
from chessify.paths import ROOT

SETTINGS_PATH = ROOT / "settings" / "settings.env"
MAX_LEN = 4000
DEFAULT_PROFILE_KEY = "CHESSIFY_DEFAULT_PROFILE"
# Имена из прошлых версий: сохранённые под ними значения переносятся при чтении.
LEGACY = {"WORK_LLM_BASE_URL": "CUSTOM_LLM_BASE_URL", "WORK_LLM_API_KEY": "CUSTOM_LLM_API_KEY",
          "WORK_LLM_MODEL": "CUSTOM_LLM_MODEL"}


Text = tuple[str, str]  # (русский, английский)


@dataclass(frozen=True)
class Field:
    key: str
    label: Text
    kind: Literal["text", "url", "secret"] = "secret"
    hint: Text = ("", "")
    placeholder: str = ""


@dataclass(frozen=True)
class Section:
    id: str  # для моделей — имя профиля
    title: Text
    kind: Literal["llm", "speech"]
    about: Text
    link: str = ""
    check: str | None = None  # что проверять кнопкой: провайдер из providers.yaml или "hf"
    fields: tuple[Field, ...] = field(default_factory=tuple)


KEY: Text = ("Ключ", "Key")


def _model(key: str, default: str) -> Field:
    return Field(key, ("Модель", "Model"), "text", (f"Пусто — {default}.", f"Empty — {default}."), placeholder=default)


SECTIONS = [
    Section("custom", ("Свой сервер", "Custom server"), "llm",
            ("Любой OpenAI-совместимый сервер: vLLM, SGLang, Ollama, LM Studio или прокси. Подходит, если модель "
             "развёрнута у вас или вам выдали адрес и ключ.",
             "Any OpenAI-compatible server: vLLM, SGLang, Ollama, LM Studio or a proxy. Use it if the model runs "
             "on your own machine or you were given an address and a key."), check="custom", fields=(
                Field("CUSTOM_LLM_BASE_URL", ("Адрес API", "API address"), "url",
                      ("Обычно заканчивается на /v1.", "Usually ends with /v1."), placeholder="http://localhost:8000/v1"),
                Field("CUSTOM_LLM_API_KEY", KEY, hint=("Если сервер без ключа — впишите любое слово, например none.",
                                                       "If the server has no key, enter any word, e.g. none.")),
                Field("CUSTOM_LLM_MODEL", ("Модель", "Model"), "text",
                      ("Не знаете — нажмите «Проверить»: появится список моделей на сервере.",
                       "Not sure? Press “Check”: you'll get the list of models on the server."), placeholder="qwen"),
            )),
    Section("deepseek", ("DeepSeek", "DeepSeek"), "llm",
            ("Платно, но дёшево: порядка 3–15 центов за ролик, ночью по UTC и в выходные вдвое дешевле. "
             "Разметка — DeepSeek Flash, оценки и комментарии — DeepSeek V4 Pro.",
             "Paid but cheap: around 3–15 cents per video, half price at night (UTC) and on weekends. "
             "Splitting into moves — DeepSeek Flash, ratings and comments — DeepSeek V4 Pro."),
            "https://platform.deepseek.com/api_keys", check="deepseek", fields=(Field("DEEPSEEK_API_KEY", KEY),)),
    Section("gemini", ("Google Gemini", "Google Gemini"), "llm",
            ("Бесплатный тариф AI Studio. На нём Google может использовать запросы для улучшения своих моделей.",
             "Free AI Studio tier. On it, Google may use your requests to improve its models."),
            "https://aistudio.google.com/apikey", check="gemini",
            fields=(Field("GEMINI_API_KEY", KEY), _model("GEMINI_MODEL", "gemini-3.8-flash"))),
    Section("openai", ("OpenAI", "OpenAI"), "llm", ("Платный API OpenAI.", "Paid OpenAI API."),
            "https://platform.openai.com/api-keys", check="openai",
            fields=(Field("OPENAI_API_KEY", KEY), _model("OPENAI_MODEL", "gpt-6.1-sol"))),
    Section("openrouter", ("OpenRouter", "OpenRouter"), "llm",
            ("Один ключ — сотни моделей разных компаний. Модель — в формате компания/модель, цена зависит от неё.",
             "One key — hundreds of models from different companies. Model in the company/model format; "
             "the price depends on it."),
            "https://openrouter.ai/settings/keys", check="openrouter",
            fields=(Field("OPENROUTER_API_KEY", KEY), _model("OPENROUTER_MODEL", "deepseek/deepseek-v4-pro"))),
    Section("anthropic", ("Anthropic API", "Anthropic API"), "llm",
            ("Claude по платному API Anthropic.", "Claude via the paid Anthropic API."),
            "https://platform.claude.com/settings/keys", check="anthropic",
            fields=(Field("ANTHROPIC_API_KEY", KEY), _model("ANTHROPIC_MODEL", "claude-opus-5-5"))),
    Section("claude", ("Claude по подписке", "Claude subscription"), "llm",
            ("Через Claude Code, без API-ключа. Вход один раз из терминала: docker compose exec app claude, "
             "затем /login. Подписка подходит для личного использования.",
             "Through Claude Code, no API key. Sign in once from a terminal: docker compose exec app claude, "
             "then /login. A subscription is meant for personal use."), check="claude_sub"),
    Section("hf", ("Разметка спикеров", "Speaker diarization"), "speech",
            ("Бесплатный токен Hugging Face (тип Read) и принятые условия модели "
             "pyannote/speaker-diarization-community-1. Без него ролики собираются, но стороны диалога "
             "модель определяет только по смыслу.",
             "A free Hugging Face token (Read type) and accepted terms of the "
             "pyannote/speaker-diarization-community-1 model. Without it videos still work, but the sides "
             "of the dialogue are guessed from the meaning of the lines only."),
            "https://huggingface.co/settings/tokens", check="hf",
            fields=(Field("HF_TOKEN", ("Токен Hugging Face", "Hugging Face token")),)),
]
FIELDS = [f for s in SECTIONS for f in s.fields]
KEYS = {f.key: f for f in FIELDS} | {DEFAULT_PROFILE_KEY: Field(DEFAULT_PROFILE_KEY, ("Основная модель", "Main model"), "text")}
SECTION_OF = {f.key: s for s in SECTIONS for f in s.fields}

_shadowed: dict[str, str | None] = {}  # ключ → значение из окружения, которое перекрыли настройки


def read(path: Path | None = None) -> dict[str, str]:
    path = path or SETTINGS_PATH
    if not path.exists():
        return {}
    raw = dotenv_values(path, encoding="utf-8")
    values = {LEGACY.get(k, k): v for k, v in raw.items() if v}
    return {k: v for k, v in values.items() if k in KEYS}


def tr(text: Text, lang: str | None = None) -> str:
    return pick(*text, lang)


def describe(keys: Iterable[str], lang: str | None = None) -> str:
    """Как недостающие ключи называются в «Настройках»: раздел → поле (переменная)."""
    return "; ".join(f"{tr(SECTION_OF[k].title, lang)} → {tr(KEYS[k].label, lang)} ({k})" if k in SECTION_OF else k
                     for k in keys)


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
        raise ValueError(pick(f"неизвестная настройка {key}", f"unknown setting {key}"))
    value = value.strip()
    label = tr(KEYS[key].label)
    if "\n" in value or "\r" in value or len(value) > MAX_LEN:
        raise ValueError(pick(f"{label}: одна строка до {MAX_LEN} символов", f"{label}: one line, up to {MAX_LEN} characters"))
    if KEYS[key].kind == "url" and value and not value.startswith(("http://", "https://")):
        raise ValueError(pick(f"{label}: адрес начинается с http:// или https://", f"{label}: the address starts with http:// or https://"))
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


def status(path: Path | None = None, lang: str | None = None) -> list[dict]:
    """Разделы с состоянием полей для интерфейса на языке lang. Секреты целиком наружу не отдаются."""
    saved = read(path)
    out = []
    for sec in SECTIONS:
        fields = []
        for f in sec.fields:
            value = os.environ.get(f.key, "")
            source = "web" if f.key in saved else "env" if value else None
            shown = {"masked": mask(value)} if f.kind == "secret" and value else {"value": value}
            fields.append({"key": f.key, "label": tr(f.label, lang), "kind": f.kind, "hint": tr(f.hint, lang),
                           "placeholder": f.placeholder, "source": source, **shown})
        out.append({"id": sec.id, "title": tr(sec.title, lang), "kind": sec.kind, "about": tr(sec.about, lang),
                    "link": sec.link, "check": sec.check, "fields": fields})
    return out
