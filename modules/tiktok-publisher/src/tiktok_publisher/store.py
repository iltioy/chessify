"""Хранилище приложений TikTok и подключённых аккаунтов.

Один JSON-файл (путь — аргумент или TIKTOK_PUBLISHER_STORE, по умолчанию ~/.config/tiktok-publisher/store.json):

- apps — приложения с developers.tiktok.com: client_key, client_secret, redirect_uri, scopes;
- accounts — аккаунты под своими именами («main», «chessify-ru»): токены, open_id, имя в TikTok, приватность
  по умолчанию. Разные сервисы публикуют на разные аккаунты, просто указывая имя;
- pending — начатые подключения (state → code_verifier), живут 15 минут.

Файл пишется атомарно, с правами 0600, под файловой блокировкой — им могут пользоваться несколько процессов.
Если задан ключ (TIKTOK_PUBLISHER_KEY, Fernet) и установлен пакет cryptography — файл шифруется.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Generator

from tiktok_publisher.errors import ConfigError

DEFAULT_SCOPES = ["user.info.basic", "video.publish", "video.upload"]
PENDING_TTL = 15 * 60
PRIVACY_LEVELS = ("PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY")


@dataclass
class App:
    name: str
    client_key: str
    client_secret: str
    redirect_uri: str = ""  # по умолчанию http://127.0.0.1:<порт>/callback/ (зарегистрировать в TikTok)
    scopes: list[str] = field(default_factory=lambda: list(DEFAULT_SCOPES))


@dataclass
class Account:
    name: str
    app: str
    open_id: str
    access_token: str
    access_expires_at: float
    refresh_token: str
    refresh_expires_at: float
    scopes: list[str] = field(default_factory=list)
    username: str = ""
    display_name: str = ""
    default_privacy: str = "SELF_ONLY"
    connected_at: float = 0.0

    def public(self) -> dict:
        """Без токенов — для показа в интерфейсах и логах."""
        return {"name": self.name, "app": self.app, "username": self.username, "display_name": self.display_name,
                "scopes": self.scopes, "default_privacy": self.default_privacy, "connected_at": self.connected_at,
                "access_expires_at": self.access_expires_at, "refresh_expires_at": self.refresh_expires_at}


def default_path() -> Path:
    if env := os.environ.get("TIKTOK_PUBLISHER_STORE"):
        return Path(env)
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "tiktok-publisher" / "store.json"


class AccountStore:
    def __init__(self, path: str | Path | None = None, key: str | None = None) -> None:
        self.path = Path(path) if path else default_path()
        self.key = key if key is not None else os.environ.get("TIKTOK_PUBLISHER_KEY") or None

    # ---------- приложения ----------

    def set_app(self, app: App) -> None:
        if not app.client_key or not app.client_secret:
            raise ConfigError("client_key and client_secret are required")
        with self._edit() as data:
            data["apps"][app.name] = asdict(app)

    def get_app(self, name: str) -> App:
        apps = self._read()["apps"]
        if name not in apps:
            raise ConfigError(f"unknown TikTok app {name!r}; add it first")
        return App(**apps[name])

    def list_apps(self) -> list[App]:
        return [App(**a) for a in self._read()["apps"].values()]

    def remove_app(self, name: str) -> None:
        with self._edit() as data:
            data["apps"].pop(name, None)

    # ---------- аккаунты ----------

    def save_account(self, account: Account) -> None:
        with self._edit() as data:
            data["accounts"][account.name] = asdict(account)

    def get_account(self, name: str) -> Account:
        accounts = self._read()["accounts"]
        if name not in accounts:
            raise ConfigError(f"unknown TikTok account {name!r}; connect it first")
        return Account(**accounts[name])

    def list_accounts(self) -> list[Account]:
        return [Account(**a) for a in self._read()["accounts"].values()]

    def remove_account(self, name: str) -> None:
        with self._edit() as data:
            data["accounts"].pop(name, None)

    def set_default_privacy(self, name: str, privacy: str) -> None:
        if privacy not in PRIVACY_LEVELS:
            raise ConfigError(f"privacy must be one of {', '.join(PRIVACY_LEVELS)}")
        with self._edit() as data:
            if name not in data["accounts"]:
                raise ConfigError(f"unknown TikTok account {name!r}")
            data["accounts"][name]["default_privacy"] = privacy

    # ---------- начатые подключения ----------

    def add_pending(self, state: str, info: dict) -> None:
        with self._edit() as data:
            now = time.time()
            data["pending"] = {k: v for k, v in data["pending"].items() if now - v.get("created_at", 0) < PENDING_TTL}
            data["pending"][state] = {**info, "created_at": now}

    def pop_pending(self, state: str) -> dict:
        with self._edit() as data:
            info = data["pending"].pop(state, None)
        if not info or time.time() - info.get("created_at", 0) > PENDING_TTL:
            raise ConfigError("unknown or expired authorization state; start connecting the account again")
        return info

    # ---------- файл ----------

    def _empty(self) -> dict:
        return {"version": 1, "apps": {}, "accounts": {}, "pending": {}}

    def _read(self) -> dict:
        if not self.path.exists():
            return self._empty()
        raw = self.path.read_bytes()
        if self.key:
            raw = self._fernet().decrypt(raw)
        data = json.loads(raw or b"{}")
        return {**self._empty(), **data}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(data, ensure_ascii=False, indent=1).encode()
        if self.key:
            raw = self._fernet().encrypt(raw)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".store-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    @contextmanager
    def _edit(self) -> Generator[dict, None, None]:
        with self._lock():
            data = self._read()
            yield data
            self._write(data)

    @contextmanager
    def _lock(self, timeout: float = 15, stale: float = 60) -> Generator[None, None, None]:
        """Блокировка файлом рядом с хранилищем: работает на Windows, Linux и macOS."""
        lock = self.path.with_name(self.path.name + ".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + timeout
        while True:
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                break
            except FileExistsError:
                try:
                    if time.time() - lock.stat().st_mtime > stale:  # процесс упал, не сняв блокировку
                        lock.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.time() > deadline:
                    raise ConfigError(f"store is locked: {lock}") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            lock.unlink(missing_ok=True)

    def _fernet(self):
        try:
            from cryptography.fernet import Fernet  # pyright: ignore[reportMissingImports] — необязательная зависимость
        except ImportError as e:
            raise ConfigError("TIKTOK_PUBLISHER_KEY is set, but the 'cryptography' package is not installed") from e
        return Fernet(str(self.key).encode())
