"""Публикация готовых роликов в TikTok — через модуль modules/tiktok-publisher.

Модуль хранит креды (приложение TikTok и токены аккаунтов) в settings/tiktok.json — в Docker это том
data/settings, рядом с ключами из «Настроек». Chessify знает только имена аккаунтов, а видео, подпись
и приватность передаёт сам. Модуль не входит в зависимости проекта (иначе правка uv.lock пересобрала бы
тяжёлый слой образа): если он не установлен пакетом, импортируется из папки modules.
"""

import re
import sys
from urllib.parse import parse_qs, urlparse

from chessify.paths import ROOT
from chessify.schema import Scene

MODULE_SRC = ROOT / "modules" / "tiktok-publisher" / "src"
try:
    import tiktok_publisher  # noqa: F401
except ImportError:
    sys.path.insert(0, str(MODULE_SRC))

from tiktok_publisher import (PRIVACY_LEVELS, AccountStore, App, ConfigError, PostOptions,  # noqa: E402
                              Publisher, PublishResult, TikTokError)

STORE_PATH = ROOT / "settings" / "tiktok.json"
APP = "chessify"  # имя приложения TikTok в хранилище модуля
CALLBACK_PATH = "/api/tiktok/callback/"
ACCOUNT_NAME = re.compile(r"[\w-]{1,40}")
TAGS = {"ru": "#шахматы #сериалы", "en": "#chess #tvshow"}

__all__ = ["ACCOUNT_NAME", "APP", "CALLBACK_PATH", "ConfigError", "PRIVACY_LEVELS", "PostOptions", "PublishResult",
           "TikTokError", "default_caption", "parse_callback", "publisher", "save_app", "status"]


def publisher() -> Publisher:
    return Publisher(AccountStore(STORE_PATH))


def _mask(value: str) -> str:
    return "••••" + value[-4:] if len(value) >= 12 else "••••"


def status() -> dict:
    """Приложение и аккаунты для интерфейса: секрет — только маской, токенов нет."""
    store = AccountStore(STORE_PATH)
    try:
        app = store.get_app(APP)
    except ConfigError:
        app = None
    return {
        "app": {"client_key": app.client_key, "secret_masked": _mask(app.client_secret)} if app else None,
        "accounts": [a.public() for a in store.list_accounts()],
        "privacy_levels": list(PRIVACY_LEVELS),
        "callback_path": CALLBACK_PATH,
    }


def save_app(client_key: str, client_secret: str = "") -> None:
    """Сохранить приложение TikTok; пустой секрет — оставить прежний."""
    store = AccountStore(STORE_PATH)
    client_key, client_secret = client_key.strip(), client_secret.strip()
    if not client_secret:
        try:
            client_secret = store.get_app(APP).client_secret
        except ConfigError:
            pass
    store.set_app(App(APP, client_key, client_secret))


def parse_callback(url: str) -> dict[str, str]:
    """Параметры из адреса, на который TikTok вернул пользователя (если страница не открылась — его вставляют)."""
    return {k: v[0] for k, v in parse_qs(urlparse(url.strip()).query).items()}


def default_caption(scene: Scene) -> str:
    """Подпись по умолчанию: заголовок ролика, хэштег сериала и общие теги на языке ролика."""
    title = " ".join(scene.meta.title.split())
    series = re.sub(r"\W+", "", scene.meta.series.title(), flags=re.UNICODE)
    tags = " ".join(t for t in (f"#{series}" if series else "", TAGS[scene.meta.language]) if t)
    return f"{title}\n\n{tags}".strip()
