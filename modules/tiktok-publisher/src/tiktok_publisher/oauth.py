"""Подключение аккаунта TikTok по OAuth 2.0 с PKCE (схема для программ без публичного https-адреса).

TikTok возвращает пользователя на redirect_uri вида http://127.0.0.1:<порт>/<путь>/ — такой адрес разрешён
для приложений с платформой Desktop; зарегистрировать его нужно в Login Kit (можно с портом «*»).
Код подтверждения по документации TikTok — шестнадцатеричный SHA-256 от verifier.
"""

from __future__ import annotations

import hashlib
import secrets
import urllib.parse

from tiktok_publisher.client import AUTHORIZE_URL

_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"


def new_pkce() -> tuple[str, str]:
    verifier = "".join(secrets.choice(_ALPHABET) for _ in range(64))
    return verifier, hashlib.sha256(verifier.encode()).hexdigest()


def authorize_url(client_key: str, redirect_uri: str, scopes: list[str], state: str, code_challenge: str) -> str:
    query = {
        "client_key": client_key,
        "response_type": "code",
        "scope": ",".join(scopes),
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(query)}"
