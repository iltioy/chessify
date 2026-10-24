"""Два языка: русский и английский.

Язык интерфейса берётся из запроса (заголовок X-Lang) и запоминается в задаче — на нём пишутся
сообщения и журнал. Язык ролика — отдельно: на нём распознаётся речь, пишет модель и сделаны
надписи в ролике (Meta.language).
"""

from contextvars import ContextVar
from typing import Literal

Lang = Literal["ru", "en"]
current: ContextVar[str] = ContextVar("ui_lang", default="ru")


def norm(value: object) -> Lang:
    return "en" if str(value or "").strip().lower().startswith("en") else "ru"


def pick(ru: str, en: str, lang: str | None = None) -> str:
    """Строка на языке lang (по умолчанию — на языке текущего запроса)."""
    return en if (lang or current.get()) == "en" else ru
